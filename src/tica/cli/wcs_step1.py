import argparse
import logging
import sys
from time import time

from tica.cli._common import setup_run_logging
from wcs_build.step1_get_refimg_ctrlpts import get_refimg_ctrlpts
from wcs_build.tic_catalog import PROVIDERS, TICError, get_provider
from wcs_build.tic_postgres import default_service

DESCRIPTION = """\
Step 1 of the WCS fit: find bright, isolated stars on a reference image and
save their positions as control points for step 2 (tica-wcs-step2).

Stars come from the TESS Input Catalog, by default from a PostgreSQL copy
reached through a libpq service (see wcs_build.tic_postgres); --catalog mast
uses the MAST API instead. TIC positions are propagated to the reference
image's mid-exposure time, which is recorded in the output as pm_epoch_jd.

Exit codes: 0 success; 1 failure, e.g. too few stars; 2 the TIC could not be
reached or queried."""


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
    parser.add_argument("--catalog", choices=PROVIDERS, default='postgres',
                        help="where to get the TIC from (default: %(default)s)")
    parser.add_argument("--tic-service", default=default_service(),
                        help="libpq service for --catalog postgres [TICA_TIC_SERVICE] "
                        "(default: %(default)s)")
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
    options = {'service': args.tic_service} if args.catalog == 'postgres' else {}
    try:
        with get_provider(args.catalog, **options) as catalog:
            get_refimg_ctrlpts(args.sector, args.camera, args.ccd,
                               args.refimage,
                               args.outputfile, args.debug,
                               args.wing, args.contrast,
                               catalog=catalog)
    except TICError as e:
        logging.error(str(e))
        print("Configuration Error. {}".format(e), file=sys.stderr)
        return 2
    runtime = time() - starttime
    logging.info("Runtime: {0:.2f}sec".format(runtime))
    return 0


if __name__ == "__main__":
    sys.exit(main())
