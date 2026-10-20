import argparse
import os
import shutil
import sys

from tica.cli import _common

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

Exit codes: 0 success; 1 some files failed to calibrate (the others were
written); 2 configuration error."""


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
    return parser


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


def segment_stamps(files):
    """The distinct date stamps (tess<stamp>-...) in the file names, sorted."""
    return sorted({os.path.basename(f)[len('tess'):].split('-')[0] for f in files})


def orbit_files(dstem, orbit, cam, orbseg, slash='//'):
    """Raw FFIs of one camera in one orbit, or None if orbseg names a missing segment."""
    files = []
    if orbseg == '':
        if os.path.isdir('{}//orbit-{}/ffi_fits-haho'.format(dstem, orbit)):
            files += _common.sorted_glob('{}//orbit-{}/ffi_fits-haho/tess*-{}-crm-ffi.fits*'.format(dstem, orbit, cam))
        files += _common.sorted_glob('{}{}orbit-{}/ffi_fits/tess*-{}-crm-ffi.fits*'.format(dstem, slash, orbit, cam))
        return files

    ##check orbit segments
    stamps = segment_stamps(_common.sorted_glob('{}//orbit-{}/ffi_fits/tess*-{}-crm-ffi.fits*'.format(dstem, orbit, cam)))
    stampuse = ''
    if 'a' in orbseg and len(stamps) > 0:
        stampuse = stamps[0]
    if 'b' in orbseg:
        stampuse = stamps[1] if len(stamps) > 1 else ''
    if stampuse == '':
        return None
    return _common.sorted_glob('{}//orbit-{}/ffi_fits/tess{}*-{}-crm-ffi.fits*'.format(dstem, orbit, stampuse, cam))


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
    message = check_config(o1, o2, orbseg)
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
            found = orbit_files(dstem, orbit, i, orbseg, slash=slash)
            if found is None:
                print("Error.  Requested {} but could not find correct segment in "
                      "{}/orbit-{}/ffi_fits.".format(orbseg, dstem, orbit))
                return 2
            files += found
        with open(os.path.join(outdir, 'cam{}_ccd1'.format(i), 'inlist'), 'w') as fout:
            fout.writelines(f + '\n' for f in files)

    logfile = log_name(o1, o2, orbseg)

    #run tica
    #set a flag if there are errors.
    #this lets us processes everything, but make a note of issues
    errorflag = 0
    for i in range(1, 5):
        camdir = os.path.join(outdir, 'cam{}_ccd1'.format(i))
        rc = _common.run_command('cal_ffi2ccds',
                                 ['inlist', '--outdir', '.', '--caldir', caldir,
                                  '--parallel', args.ncores, '--log', logfile,
                                  '--orb_seg', orbseg, '--no_gzip'],
                                 cwd=camdir)
        if rc != 0:
            errorflag = 1
        for j in (2, 3, 4):
            for f in _common.sorted_glob(os.path.join(camdir, 'tess*ccd{}.cal.fits*'.format(j))):
                shutil.move(f, os.path.join(outdir, 'cam{}_ccd{}'.format(i, j), os.path.basename(f)))

    return errorflag


if __name__ == "__main__":
    sys.exit(main())
