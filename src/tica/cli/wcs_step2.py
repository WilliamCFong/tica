import argparse
import logging
import os
import sys
from time import time

from tica.cli._common import setup_run_logging
from wcs_build.step2_mkwcs import fit_wcs_in_imgdir

DESCRIPTION = """\
Step 2 of the WCS fit: fit a WCS to each image using the control points from
step 1 (tica-wcs-step1), and write it into the image headers in place."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-wcs-step2', description=DESCRIPTION)
    parser.add_argument("-s", "--sector", type=int,
                        help="TESS Observing Sector Number")
    parser.add_argument("-ca", "--camera", type=int, choices=range(1, 5),
                        help="Camera Number [1-4]")
    parser.add_argument("-cd", "--ccd", type=int, choices=range(1, 5),
                        help="CCD Number [1-4]")
    parser.add_argument("-rd", "--refdata", type=str,
                        help="Reference image control point data created in step1")
    parser.add_argument("-if", "--imgfiles", nargs="+",
                        help="List of input files.")
    parser.add_argument("-od", "--outputdir", default='./',
                        help="Unused; results are written next to the input files.")
    parser.add_argument("-fd", "--fitdegree", type=int,
                        help="Degree of wcs fit")
    parser.add_argument("--savediaginfo", action="store_true",
                        help="Save diagnostic info and figures")
    parser.add_argument("--flexibleapertures", action="store_true",
                        help="Allow for centroid analysis region to vary. "
                        "For most cases pointing is stable (<pixel) "
                        "in which case do not use this option. "
                        "This option would be helpful if >1-2 pixel "
                        "shifts occur.")
    parser.add_argument("-dbg", "--debug", type=int, default=0,
                        help="Debug level; integer higher has more output")
    parser.add_argument("--parallel", type=int, default=1,
                        help="run files in parallel on number of processors specified here")
    parser.add_argument("-l", "--log", metavar="LOG_FILE",
                        help="save logging output to this file")
    return parser


def rotate_log(log):
    """Move an existing log to <log>_runN, so every run gets a fresh file."""
    if log is None or not os.path.isfile(log):
        return
    ii = 1
    while os.path.isfile(log + '_run{}'.format(ii)):
        ii += 1
    os.rename(log, log + '_run{}'.format(ii))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # output directory is same as input directory
    outputDir = os.path.dirname(args.imgfiles[0])
    fixApertures = not args.flexibleapertures

    saveDiag = args.savediaginfo
    if saveDiag:
        os.makedirs(os.path.join(outputDir, 'wcs_diags2'), exist_ok=True)

    #for step 2, we usually do all of the files
    #so, move the old logs, and make a new file
    #for every run.
    rotate_log(args.log)
    setup_run_logging(parser.prog, args, args.log, log_cwd=False, skip=('imgfiles',))
    starttime = time()

    fit_wcs_in_imgdir(args.sector, args.camera, args.ccd, args.refdata,
                      args.imgfiles, outputDir, args.fitdegree,
                      fixApertures,
                      saveDiag, args.debug,
                      n_cores=args.parallel)

    runtime = time() - starttime
    logging.info("Runtime: {0:.2f}sec".format(runtime))
    return 0


if __name__ == "__main__":
    sys.exit(main())
