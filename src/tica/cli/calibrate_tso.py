import argparse
import os
import shutil
import sys

from tica.cli import _common, _segments

DESCRIPTION = """\
Calibrate full-camera FFIs from the TESS Science Office (TSO) / POC with
tica-cal-ffi2ccds, writing calibrated FFIs split by CCD.

This command assumes that all FFIs are saved under TSO formats and naming
conventions, in <dstem>/orbit-<orbit>/ffi_fits/. TSO format FFI files are not
publicly available at this time; see tica-calibrate-spoc for publicly
available SPOC FFIs.

Outputs go to <outdir> (default: the current directory): calibrated FFIs in
cam<i>_ccd<j>/ and logs in tica_logs/. Run later steps (tica-darktime,
tica-wcs-step1-allcam-allccd, tica-wcs-step2-allcam-allccd) from inside that
directory.

--orbseg selects one segment of the orbit: o1a/o1b (o2a/o2b, ...) for the
halves of an orbit downlinked in two parts, or o1 (o2, ...) for an orbit
downlinked whole. Segments are worked out from the files' cadences, and a
re-delivered downlink replaces the earlier copy (see tica.cli._segments).
Without --orbseg, every file of the orbit is used, including ffi_fits-haho.

Other modes, used by tica-doall-automate to write each FFI only once:
  --no_write   record cal_timeseries.txt and the log, but write no FFIs
  --fin FIN    write only the FFIs with this FIN (the WCS reference frame),
               without diagnostics, logging to <segment>_tica_reference.log
  --hlspdir    run tica-cal-ffi2hlsp instead of tica-cal-ffi2ccds: calibrate,
               fit the WCS, and write the delivery files to <hlspdir>; needs
               --orbseg, --sector and <outdir>/refout from tica-wcs-step1

Exit codes: 0 success; 1 some files failed to calibrate (the others were
written); 2 configuration error, here or in a camera's run."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-calibrate-tso', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--o1", required=True, metavar="ORBIT",
                        help="first orbit of the sector, as an integer, or None to skip it")
    parser.add_argument("--o2", required=True, metavar="ORBIT",
                        help="second orbit of the sector, as an integer, or None to skip it")
    parser.add_argument("--orbseg", default='', metavar="SEGMENT",
                        help="orbit segment to process (o1a, o1b, o2a, o2b), written to the "
                        "ORB_SEG keyword. Only valid when a single orbit is set.")
    parser.add_argument("--dstem", required=True, metavar="DIRECTORY",
                        help="directory in which the POC keeps the orbit-<N> directories")
    parser.add_argument("--caldir", required=True, metavar="DIRECTORY",
                        help="directory with calibration models for the exposure time, "
                        "e.g. calibration_200sec from the TICA repository")
    parser.add_argument("--ncores", type=int, default=1,
                        help="number of cores to use for parallel processing (default: 1)")
    parser.add_argument("--outdir", default='', metavar="DIRECTORY",
                        help="directory for the outputs, created if needed "
                        "(default: current directory)")
    parser.add_argument("--no_write", action="store_true",
                        help="calibrate and record diagnostics only; write no FFIs")
    parser.add_argument("--fin", metavar="FIN",
                        help="calibrate only the FFIs with this FIN, without diagnostics")
    parser.add_argument("--hlspdir", metavar="DIRECTORY",
                        help="write delivery files here with tica-cal-ffi2hlsp, "
                        "e.g. <delivery root>/s0098")
    parser.add_argument("--sector", type=int, help="sector number, for --hlspdir")
    parser.add_argument("--hlsp_version", default='v01',
                        help="delivery version, for --hlspdir (default: %(default)s)")
    parser.add_argument("--no_diagnostics", action="store_true",
                        help="do not write cal_timeseries.txt, e.g. after a --no_write run")
    return parser


def check_mode(args):
    """Return an error message for inconsistent output modes, or None."""
    if sum([args.no_write, args.fin is not None, args.hlspdir is not None]) > 1:
        return "Configuration Error. Use only one of --no_write, --fin and --hlspdir."
    if args.hlspdir is not None and (args.orbseg == '' or args.sector is None):
        return "Configuration Error. --hlspdir needs --orbseg and --sector."
    return None


def check_config(o1, o2, orbseg):
    """Return an error message for inconsistent orbit settings, or None."""
    if o1 != "None" and o2 != "None" and orbseg != "":
        return ("Configuration Error.  Both orbits are set, cannot use orbseg.  "
                "Processes individual orbits if you need this keyword set.")
    #exit if orbseg does not match expected orbit
    if 'o1' in orbseg and o1 == 'None':
        return "Configuration Error. o1 is None but orbseg is set to {}.".format(orbseg)
    if 'o2' in orbseg and o2 == 'None':
        return "Configuration Error. o2 is None but orbseg is set to {}.".format(orbseg)
    if 'o1' in orbseg and o2 != 'None':
        return ("Configuration Error. o1 is set, but orbseg requested something from orbit 1. "
                "orbseg must match the orbit that is set.")
    if 'o2' in orbseg and o1 != 'None':
        return ("Configuration Error. o1 is set, but orbseg requested something from orbit 2.  "
                "orbseg must match the orbit that is set.")
    return None


def orbit_files(dstem, orbit, cam, orbseg, slash='//'):
    """Raw FFIs of one camera in one orbit, or None if the orbit has no segment orbseg.

    Raises _segments.OffNominal if the orbit's FFIs don't fall into one or two
    downlinks.
    """
    files = []
    if orbseg == '':
        if os.path.isdir('{}//orbit-{}/ffi_fits-haho'.format(dstem, orbit)):
            files += _common.sorted_glob('{}//orbit-{}/ffi_fits-haho/tess*-{}-crm-ffi.fits*'.format(dstem, orbit, cam))
        files += _common.sorted_glob('{}{}orbit-{}/ffi_fits/tess*-{}-crm-ffi.fits*'.format(dstem, slash, orbit, cam))
        return files

    segment = _segments.find_segment(dstem, orbit, orbseg)
    return None if segment is None else segment.files.get(cam, [])


def log_name(o1, o2, orbseg):
    if orbseg == '':
        if o1 != "None":
            return "../tica_logs/o1o2_tica.log" if o2 != "None" else "../tica_logs/o1_tica.log"
        return "../tica_logs/o2_tica.log"
    return "../tica_logs/{}_tica.log".format(orbseg)


def main(argv=None):
    args = build_parser().parse_args(argv)
    o1, o2, orbseg = args.o1, args.o2, args.orbseg

    if orbseg == '':
        print("orbseg is not set, running both ffi_fits-haho and ffi_fits and will not write "
              "keyword ORB_SEG in output files.")
    message = check_mode(args) or check_config(o1, o2, orbseg)
    if message:
        print(message)
        return 2

    #make input paths absolute, since outputs go to outdir
    if not os.path.isdir(args.dstem):
        print("Configuration Error. dstem is not a directory.")
        return 2
    error = _common.caldir_error(args.caldir)
    if error:
        print("Configuration Error. {}".format(error))
        return 2
    dstem = os.path.abspath(args.dstem)
    caldir = os.path.abspath(args.caldir)

    outdir = os.path.abspath(args.outdir or '.')
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError:
        print("Configuration Error. Cannot create or enter outdir {}.".format(args.outdir))
        return 2

    for i in range(1, 5):
        for j in range(1, 5):
            os.makedirs(os.path.join(outdir, 'cam{}_ccd{}'.format(i, j)), exist_ok=True)
    os.makedirs(os.path.join(outdir, 'tica_logs'), exist_ok=True)

    #make inlist for tica
    for i in range(1, 5):
        files = []
        for orbit, name, slash in ((o1, 'o1', '//'), (o2, 'o2', '/')):
            if orbit == "None":
                continue
            try:
                found = orbit_files(dstem, orbit, i, orbseg, slash=slash)
            except _segments.OffNominal as e:
                print("Configuration Error. {}".format(e))
                return 2
            if found is None:
                names = [seg.name for seg in _segments.find_segments(dstem, orbit)]
                print("Error.  Requested {} but could not find correct segment in "
                      "{}/orbit-{}/ffi_fits; it has {}.".format(orbseg, dstem, orbit,
                                                               ', '.join(names) or 'no FFIs'))
                return 2
            files += found
        if args.fin is not None:
            files = [f for f in files if os.path.basename(f).split('-')[1] == args.fin]
            if not files:
                print("Error.  No camera {} FFI has FIN {}.".format(i, args.fin))
                return 2
        with open(os.path.join(outdir, 'cam{}_ccd1'.format(i), 'inlist'), 'w') as fout:
            fout.writelines(f + '\n' for f in files)

    logfile = log_name(o1, o2, orbseg)
    if args.fin is not None:
        logfile = logfile.replace('_tica.log', '_tica_reference.log')

    # the keyword is empty for a whole orbit (see _segments); tica-cal-ffi2hlsp
    # also needs the segment name for the file names, and works this out itself
    keyword = orbseg if orbseg.endswith(('a', 'b')) else ''
    if args.hlspdir is not None:
        keyword = orbseg
        module = 'cal_ffi2hlsp'
        options = ['--hlspdir', os.path.abspath(args.hlspdir), '--sector', args.sector,
                   '--refdir', os.path.join(outdir, 'refout'), '--workdir', outdir,
                   '--hlsp_version', args.hlsp_version]
    else:
        module = 'cal_ffi2ccds'
        options = ['--no_gzip']
        if args.no_write:
            options.append('--no_write')
    if args.no_diagnostics or args.fin is not None:
        options.append('--no_diagnostics')

    #run tica
    #set a flag if there are errors.
    #this lets us processes everything, but make a note of issues
    errorflag = 0
    for i in range(1, 5):
        camdir = os.path.join(outdir, 'cam{}_ccd1'.format(i))
        rc = _common.run_command(module,
                                 ['inlist', '--outdir', '.', '--caldir', caldir,
                                  '--parallel', args.ncores, '--log', logfile,
                                  '--orb_seg', keyword] + options,
                                 cwd=camdir)
        if rc == 2:
            # a configuration error, e.g. missing reference star lists
            errorflag = 2
        elif rc != 0 and errorflag == 0:
            errorflag = 1
        for j in (2, 3, 4):
            for f in _common.sorted_glob(os.path.join(camdir, 'tess*ccd{}.cal.fits*'.format(j))):
                shutil.move(f, os.path.join(outdir, 'cam{}_ccd{}'.format(i, j), os.path.basename(f)))

    return errorflag


if __name__ == "__main__":
    sys.exit(main())
