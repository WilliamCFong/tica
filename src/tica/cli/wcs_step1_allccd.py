import argparse
import os
import sys

from tica.cli import _common

DESCRIPTION = """\
Run tica-wcs-step1 for all 16 CCDs in parallel.

tica-wcs-step1 identifies bright and relatively uncrowded stars in a reference
FFI and writes .h5 files tabulating good stars for the WCS fit, which
tica-wcs-step2-allcam-allccd needs. The .h5 files go to <dstem>/refout/; CCDs
whose .h5 file already exists are skipped. Logs go to
tica_logs/tica_wcs_step1_cam<i>_ccd<j>.log in the current directory.

This command assumes TSO format FFIs and naming conventions (see
tica-calibrate-tso), in <dstem>cam<i>_ccd<j>/. TSO format files are not
publicly available; see tica-calibrate-spoc and tica-wcs-spoc for SPOC FFIs.

Exit codes: 0 success; 1 at least one CCD failed; 2 configuration error."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-wcs-step1-allcam-allccd', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sector", required=True,
                        help="two digit sector number, used by tess-point to convert row/col to ra/dec")
    parser.add_argument("--reffin", required=True, metavar="FIN",
                        help="FFI index (FIN) of the reference image, as it appears in the file "
                        "names. The FFI should be free from scattered light.")
    parser.add_argument("--dstem", required=True, metavar="DIRECTORY",
                        help="directory containing the cam<i>_ccd<j> directories, with a "
                        "trailing slash (e.g. ./)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    dstem = args.dstem

    refout = os.path.join(dstem, 'refout')
    if os.path.isdir(refout):
        print("refout exists")
    else:
        os.mkdir(refout)

    DEBUGIT = 2

    jobs = []
    for iCam in range(1, 5):
        for jCcd in range(1, 5):
            USE_REF = _common.sorted_glob('{}cam{}_ccd{}/tess*{}*'.format(dstem, iCam, jCcd, args.reffin))
            USE_OUT = '{}refout/reftica_s{}_{}-{}.h5'.format(dstem, args.sector, iCam, jCcd)

            if os.path.exists(USE_OUT):
                print("skipping {}; already exists".format(USE_OUT))
                continue

            jobs.append(('wcs_step1',
                         ['-s', args.sector, '-ca', iCam, '-cd', jCcd, '-ri'] + USE_REF
                         + ['-o', USE_OUT, '-dbg', DEBUGIT,
                            '-l', 'tica_logs/tica_wcs_step1_cam{}_ccd{}.log'.format(iCam, jCcd)]))

    #set a flag if there are errors.
    #this lets us processes everything, but make a note of issues
    return 1 if any(_common.run_parallel(jobs)) else 0


if __name__ == "__main__":
    sys.exit(main())
