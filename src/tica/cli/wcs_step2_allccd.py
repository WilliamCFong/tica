import argparse
import sys

from tica.cli import _common

DESCRIPTION = """\
Run tica-wcs-step2 for all 16 CCDs in parallel.

tica-wcs-step2 measures star positions in each FFI, fits WCS coefficients, and
adds the WCS and a table of star centroids to the FFIs, modifying them in
place. It needs the .h5 star lists in <dstem>/refout/ from
tica-wcs-step1-allcam-allccd. Logs go to
tica_logs/tica_wcs_step2_cam<i>_ccd<j>.log in the current directory.

This command assumes TSO format FFIs and naming conventions (see
tica-calibrate-tso), in <dstem>/cam<i>_ccd<j>/. TSO format files are not
publicly available; see tica-calibrate-spoc and tica-wcs-spoc for SPOC FFIs.

Exit codes: 0 success; 1 at least one CCD failed; 2 configuration error."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-wcs-step2-allcam-allccd', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sector", required=True,
                        help="two digit sector number, used by tess-point to convert row/col to ra/dec")
    parser.add_argument("--dstem", required=True, metavar="DIRECTORY",
                        help="directory containing the cam<i>_ccd<j> and refout directories")
    parser.add_argument("--debug", type=int, default=0,
                        help="debug level: 0 for no output, 1 to print debugging statements "
                        "(default: 0)")
    parser.add_argument("--ncores", type=int, default=1,
                        help="number of cores for each CCD's fit (default: 1)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    dstem, SECTOR = args.dstem, args.sector

    jobs = []
    for i in range(1, 5):
        for j in range(1, 5):
            imgfiles = _common.sorted_glob('{}/cam{}_ccd{}/tess*-{}-crm-ffi_ccd{}.cal.fits'.format(dstem, i, j, i, j))
            jobs.append(('wcs_step2',
                         ['-s', SECTOR, '-ca', i, '-cd', j,
                          '-rd', '{}/refout/reftica_s{}_{}-{}.h5'.format(dstem, SECTOR, i, j),
                          '-if'] + imgfiles
                         + ['-fd', 6, '-dbg', args.debug,
                            '--log', 'tica_logs/tica_wcs_step2_cam{}_ccd{}.log'.format(i, j),
                            '--savediaginfo', '--parallel', args.ncores]))

    #set a flag if there are errors.
    #this lets us processes everything, but make a note of issues
    return 1 if any(_common.run_parallel(jobs)) else 0


if __name__ == "__main__":
    sys.exit(main())
