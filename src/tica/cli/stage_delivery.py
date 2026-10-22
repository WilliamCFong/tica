import argparse
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

from tica.cli import _common

DESCRIPTION = """\
Copy a processed orbit segment into a MAST delivery directory with HLSP names.

Run from the sector directory. For each CCD, the FFIs in cam<i>_ccd<j>/<segment>/
are copied to <outdir>/cam<i>-ccd<j>/ as

  hlsp_tica_tess_ffi_s<sector>-<orbit>-<fin>-cam<i>-ccd<j>_tess_<version>_img.fits

and refout/reftica_s<sector>_<i>-<j>.h5 is copied to <outdir>/ref-stars/ as

  hlsp_tica_tess_ffi_s<sector>-cam<i>-ccd<j>_tess_<version>_cat.h5

With --ref-stars-only, only the reference star lists are copied; use this
after tica-cal-ffi2hlsp, which writes the FFIs to the delivery directory
itself."""


def orbit_label(segment):
    """o1..o4 from a segment name such as o1a; the last match wins."""
    orbit = ''
    for label in ('o1', 'o2', 'o3', 'o4'):
        if label in segment:
            orbit = label
    return orbit


def hlsp_image_name(sector, segment, fin, camnum, ccdnum, version):
    return 'hlsp_tica_tess_ffi_s{:04d}-{}-{}-cam{}-ccd{}_tess_{}_img.fits'.format(
        int(sector), orbit_label(segment), fin, camnum, ccdnum, version)


def copy_ref_stars(camnum, ccdnum, version, outdir, sector):
    """Copy refout/reftica_s<sector>_<i>-<j>.h5 to <outdir>/ref-stars/."""
    os.makedirs(outdir + '/ref-stars', exist_ok=True)
    ref = os.path.abspath(_common.ref_stars_path('refout', sector, camnum, ccdnum))
    try:
        shutil.copyfile(ref, '{}/ref-stars/hlsp_tica_tess_ffi_s{:04d}-cam{}-ccd{}_tess_{}_cat.h5'.format(
            outdir, int(sector), camnum, ccdnum, version))
    except FileNotFoundError:
        print("No reference star list for cam{} ccd{}: {} is missing".format(camnum, ccdnum, ref))


def do_move(camnum, ccdnum, version, outdir, subdir, sector):
    indir = os.path.abspath('cam{}_ccd{}/{}'.format(camnum, ccdnum, subdir))

    outdir_use = '{}/cam{}-ccd{}'.format(outdir, camnum, ccdnum)
    os.makedirs(outdir_use, exist_ok=True)

    for path in _common.sorted_glob(os.path.join(indir, 'tess*fits')):
        ii = os.path.basename(path)
        #fin can be got from the filename
        fin = ii.split('-')[1]
        shutil.copyfile(path, os.path.join(outdir_use, hlsp_image_name(sector, subdir, fin,
                                                                       camnum, ccdnum, version)))

    #copy the reference star list
    copy_ref_stars(camnum, ccdnum, version, outdir, sector)


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-stage-delivery', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="delivery version, e.g. v01")
    parser.add_argument("outdir", help="delivery directory, e.g. <delivery root>/s0098")
    parser.add_argument("segment", help="orbit segment subdirectory, e.g. o1a")
    parser.add_argument("sector", type=int, help="sector number")
    parser.add_argument("--ref-stars-only", action="store_true",
                        help="copy only the reference star lists, not the FFIs")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    outdir = os.path.abspath(args.outdir)

    with ThreadPoolExecutor(max_workers=16) as pool:
        if args.ref_stars_only:
            futures = [pool.submit(copy_ref_stars, camnum, ccdnum, args.version, outdir, args.sector)
                       for camnum in range(1, 5) for ccdnum in range(1, 5)]
        else:
            futures = [pool.submit(do_move, camnum, ccdnum, args.version, outdir, args.segment, args.sector)
                       for camnum in range(1, 5) for ccdnum in range(1, 5)]
        for future in futures:
            future.result()
    return 0


if __name__ == "__main__":
    sys.exit(main())
