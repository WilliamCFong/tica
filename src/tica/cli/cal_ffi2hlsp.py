import argparse
import logging
import os
import sys
from time import time

from astropy.io import fits

import tica
from tica.cli._common import (add_file_list_args, get_calibration, load_calibration,
                              map_files, read_file_list, ref_stars_path, setup_run_logging)
from tica.cli._segments import orb_seg_keyword
from tica.cli.cal_ffi2ccds import ffi_diagnostics, write_timeseries
from tica.cli.stage_delivery import hlsp_image_name
from tica.cli.wcs_step2 import rotate_log
from tica.tica import FFI_File
from wcs_build.step2_mkwcs import fit_hdulist, save_wcs_diagnostics, wcs_fit_params, worker_args

DESCRIPTION = """\
Calibrate raw full-camera FFIs, fit the TICA WCS of each CCD, and write the
results straight to the MAST delivery directory as

  <hlspdir>/cam<i>-ccd<j>/hlsp_tica_tess_ffi_s<sector>-<orbit>-<fin>-cam<i>-ccd<j>_tess_<version>_img.fits

Each CCD image is written once. This does the work of tica-cal-ffi2ccds,
tica-wcs-step2 and tica-stage-delivery without the intermediate files. The
outputs are the same as those commands give, except for the time stamp in
the calibration COMMENT.

The reference star lists from tica-wcs-step1 must already exist, as
<refdir>/reftica_s<sector>_<i>-<j>.h5. CCD images already in the delivery
directory are not refit; their WCS diagnostics are read from their headers,
so an interrupted run can be repeated. With --refit they are fitted and
written again, e.g. after the star lists were remade. Files are written under
a .part name and renamed when complete. A raw FFI that cannot be calibrated
counts as 4 failed CCD images; the others are still delivered and recorded.

Like tica-cal-ffi2ccds, it writes cal_timeseries.txt to --outdir. WCS
diagnostics go to <workdir>/cam<i>_ccd<j>/wcs_diags2/ and a log for each CCD
to <workdir>/tica_logs/tica_wcs_step2_cam<i>_ccd<j>.log, as tica-wcs-step2
writes them, for tica-production-table.

Exit codes: 0 success; 1 some CCD images failed (the others were written);
2 configuration error."""

PROG = 'tica-cal-ffi2hlsp'
FIT_DEGREE = 6


def camera_of(filename):
    """Camera number from a POC file name, tess<stamp>-<fin>-<cam>-crm-ffi.fits."""
    return int(os.path.basename(filename).split('-')[2])


def write_hlsp(hdu, path, intuple, refit=False):
    """Fit the WCS of one CCD image and write it to path; return the fit diagnostics.

    An image already at path is left as it is unless refit is set.
    """
    if os.path.exists(path) and not refit:
        # already delivered: fit_hdulist reads the diagnostics from the header
        with fits.open(path) as hdulist:
            all_hdus, result = fit_hdulist(hdulist, intuple)
    else:
        all_hdus, result = fit_hdulist(fits.HDUList([hdu]), intuple)
    if all_hdus is not None:
        part = path + '.part'
        all_hdus.writeto(part, checksum=True, overwrite=True)
        os.replace(part, path)
    return result


def worker(in_tuple):
    """Calibrate one raw FFI and deliver its 4 CCDs.

    Returns (filename, camnum, diagnostics, wcs_results), where
    wcs_results[j-1] is the fit diagnostics of CCD j, or None if it failed.
    diagnostics is None if the FFI could not be calibrated (or with
    --no_diagnostics).
    """
    filename, index, args = in_tuple
    calibration, wcs_params = get_calibration()
    logger = logging.getLogger(__name__)

    try:
        # whole orbits get an empty ORB_SEG, as tica-calibrate-tso always wrote
        im = FFI_File(filename, calibration=calibration, outdir=None,
                      orbit_segment=orb_seg_keyword(args.orb_seg))
    except Exception:
        logger.exception('failed to calibrate {}'.format(filename))
        return filename, camera_of(filename), None, [None] * 4
    fin = os.path.basename(filename).split('-')[1]

    wcs_results = []
    for ccdnum, hdu in enumerate(im.calibrated_CCD_hdus(), start=1):
        outdir = os.path.join(args.hlspdir, 'cam{}-ccd{}'.format(im.camnum, ccdnum))
        path = os.path.join(outdir, hlsp_image_name(args.sector, args.orb_seg, fin,
                                                    im.camnum, ccdnum, args.hlsp_version))
        try:
            os.makedirs(outdir, exist_ok=True)
            wcs_results.append(write_hlsp(hdu, path,
                                          worker_args(path, index, wcs_params[(im.camnum, ccdnum)]),
                                          refit=args.refit))
        except Exception:
            logger.exception('failed to deliver {} CCD {}'.format(filename, ccdnum))
            wcs_results.append(None)

    diagnostics = None if args.no_diagnostics else ffi_diagnostics(im)
    return filename, im.camnum, diagnostics, wcs_results


def write_wcs_log(path, settings, lines):
    """A tica-wcs-step2 style log, with the lines tica-production-table reads."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rotate_log(path)
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%Y.%m.%d %H:%M:%S'))
    log = logging.getLogger('tica.cli.cal_ffi2hlsp.wcs_log')
    log.propagate = False
    log.setLevel(logging.INFO)
    log.handlers = [handler]
    for info_line in tica.platform_info():
        log.info(info_line)
    log.info('python environment:  {}'.format(os.getenv('CONDA_DEFAULT_ENV')))
    log.info('program: {}'.format(PROG))
    log.info('argument parameters:')
    for key, value in settings.items():
        log.info('     {} = {}'.format(key, value))
    for line in lines:
        log.info(line)
    log.handlers = []
    handler.close()


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_file_list_args(parser, log_default='tica.log')
    parser.add_argument("--hlspdir", required=True, metavar="DIRECTORY",
                        help="delivery directory for the sector, e.g. <delivery root>/s0098")
    parser.add_argument("--sector", required=True, type=int, help="sector number")
    parser.add_argument("--orb_seg", required=True,
                        help="orbit segment: o1a, o1b, o2a, ... for half orbits, or o1, o2, ... for "
                        "an orbit downlinked whole. Written to the ORB_SEG keyword (empty for a "
                        "whole orbit) and used for the orbit in the file names")
    parser.add_argument("--refdir", required=True, metavar="DIRECTORY",
                        help="directory with the reftica_s<sector>_<i>-<j>.h5 star lists")
    parser.add_argument("--workdir", default='..', metavar="DIRECTORY",
                        help="sector directory, for the WCS diagnostics and logs (default: %(default)s)")
    parser.add_argument("--hlsp_version", default='v01',
                        help="delivery version in the file names (default: %(default)s)")
    parser.add_argument("--no_diagnostics", action="store_true",
                        help="if set, do not write cal_timeseries.txt, e.g. because a "
                        "--no_write run of tica-cal-ffi2ccds already did.")
    parser.add_argument("--refit", action="store_true",
                        help="fit and write CCD images that are already in the delivery directory "
                        "again, e.g. after the reference star lists were remade")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_run_logging(parser.prog, args, args.log, debug=args.debug)
    logger = logging.getLogger(__name__)

    inlist = read_file_list(args.fileinputs)
    args.hlspdir = os.path.abspath(args.hlspdir)
    workdir = os.path.abspath(args.workdir)

    cameras = sorted({camera_of(f) for f in inlist})
    missing = [ref_stars_path(args.refdir, args.sector, i, j)
               for i in cameras for j in range(1, 5)
               if not os.path.isfile(ref_stars_path(args.refdir, args.sector, i, j))]
    if missing:
        message = "reference star lists not found: {}".format(', '.join(missing))
        logger.error(message)
        print("Configuration Error. {}".format(message), file=sys.stderr)
        return 2
    # setup calibration object before processing files so it is done just once
    calibration = load_calibration(args.caldir)

    starttime = time()
    wcs_params = {}
    for i in cameras:
        for j in range(1, 5):
            ccddir = os.path.join(workdir, 'cam{}_ccd{}'.format(i, j))
            os.makedirs(os.path.join(ccddir, 'wcs_diags2'), exist_ok=True)
            wcs_params[(i, j)] = wcs_fit_params(args.sector, i, j,
                                                ref_stars_path(args.refdir, args.sector, i, j),
                                                ccddir, FIT_DEGREE)

    items = [(filename, index, args) for index, filename in enumerate(sorted(inlist))]
    results = map_files(worker, items, processes=args.parallel,
                        calibration=(calibration, wcs_params))

    if not args.no_diagnostics:
        write_timeseries(args.outdir, [(f, diagnostics) for f, _, diagnostics, _ in results
                                       if diagnostics is not None])

    runtime = time() - starttime
    nfailed = 0
    for (i, j) in sorted(wcs_params):
        fits_ok = [wcs[j - 1] for _, cam, _, wcs in results if cam == i and wcs[j - 1] is not None]
        failed = sum(1 for _, cam, _, wcs in results if cam == i and wcs[j - 1] is None)
        nfailed += failed
        if fits_ok:
            save_wcs_diagnostics(fits_ok, args.sector, i, j,
                                 os.path.join(workdir, 'cam{}_ccd{}'.format(i, j)), saveDiag=True)
        write_wcs_log(os.path.join(workdir, 'tica_logs', 'tica_wcs_step2_cam{}_ccd{}.log'.format(i, j)),
                      {'sector': args.sector, 'camera': i, 'ccd': j, 'fitdegree': FIT_DEGREE,
                       'parallel': args.parallel},
                      ['Using fixed apertures.',
                       'Delivered {} images, {} failed'.format(len(fits_ok), failed),
                       'Runtime: {0:.2f}sec'.format(runtime)])

    delivered = sum(1 for _, _, _, wcs in results for w in wcs if w is not None)
    print("Camera {}: delivered {} CCD images to {}, {} failed, in {:.0f} s with {} processes".format(
        ', '.join(str(c) for c in cameras), delivered, args.hlspdir, nfailed, runtime, args.parallel),
        flush=True)
    logger.info("N Pools = {}".format(args.parallel))
    logger.info("Runtime: {0:.2f}sec".format(runtime))
    if nfailed:
        logger.error("{} CCD images failed".format(nfailed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
