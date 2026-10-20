import argparse
import logging
import sys
from time import time

from tica.cli._common import setup_run_logging
from wcs_build.step1_get_refimg_ctrlpts import get_refimg_ctrlpts

DESCRIPTION = """\
Step 1 of the WCS fit: find bright, isolated stars on a reference image and
save their positions as control points for step 2 (tica-wcs-step2)."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-wcs-step1', description=DESCRIPTION)
    parser.add_argument("-s", "--sector", type=int,
                        help="TESS Observing Sector Number")
    parser.add_argument("-ca", "--camera", type=int, choices=range(1, 5),
                        help="Camera Number [1-4]")
    parser.add_argument("-cd", "--ccd", type=int, choices=range(1, 5),
                        help="CCD Number [1-4]")
    parser.add_argument("-ri", "--refimage", type=str,
                        help="Reference Image FITS Filename With Path")
    parser.add_argument("-o", "--outputfile", type=str,
                        help="Control point data storeage filename with path")
    parser.add_argument("-dbg", "--debug", type=int, default=0,
                        help="Debug level; integer higher has more output")
    parser.add_argument("-w", "--wing", type=float, default=0.9,
                        help="For a candidate WCS star, this sets a bound on the "
                        "symmetry of the PSF; the drop in flux from the core to the "
                        "brighter PSF wing cannot be smaller than this fraction "
                        "of the drop in flux form the core to the fainter PSF wing.")
    parser.add_argument("-c", "--contrast", type=float, default=3.5,
                        help="For candidate WCS star, this sets minimum ratio of the core "
                        "of the PSF to the maximum in the wings.  Crowded stars will "
                        "tend to have a smaller ratio.")
    parser.add_argument("-l", "--log", metavar="LOG_FILE",
                        help="save logging output to thiss file")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_run_logging(parser.prog, args, args.log, log_cwd=False)
    starttime = time()

    # Call the main functionality to get
    #  bright isolated stars on a reference image
    #  that will be used on all images for a sector camera ccd
    #  to determine a wcs solution
    get_refimg_ctrlpts(args.sector, args.camera, args.ccd,
                       args.refimage,
                       args.outputfile, args.debug,
                       args.wing, args.contrast)
    runtime = time() - starttime
    logging.info("Runtime: {0:.2f}sec".format(runtime))
    return 0


if __name__ == "__main__":
    sys.exit(main())
