import argparse
import sys

from tica.cli import _common

DESCRIPTION = """\
Fit WCSs to calibrated SPOC FFIs with tica-wcs-step2, one CCD at a time.

tica-wcs-step2 measures star positions in each FFI, fits WCS coefficients, and
adds the WCS and a table of star centroids to the FFIs, modifying them in
place. This command works exclusively on SPOC FFIs calibrated with
tica-calibrate-spoc.

tica-wcs-step2 needs reference star lists with the RAs and DECs of suitable
stars. Download them from MAST (https://archive.stsci.edu/hlsp/tica; click on
the `Ref Star` link for the sector) into <dstem>/ref_stars/.

All FFIs of interest must be in <dstem>, regardless of camera or CCD. The log
goes to tica_wcs_step2_spoc.log in the current directory."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-wcs-spoc', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sector", required=True,
                        help="two digit sector number, used by tess-point to convert row/col to ra/dec")
    parser.add_argument("--dstem", required=True, metavar="DIRECTORY",
                        help="directory with the calibrated FFIs and the ref_stars directory")
    parser.add_argument("--debug", type=int, default=0,
                        help="debug level: 0 for no output, 1 to print debugging statements "
                        "(default: 0)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    dstem, SECTOR = args.dstem, args.sector

    for i in range(1, 5):
        for j in range(1, 5):
            ref_file = ' '.join(_common.sorted_glob(
                '{}/ref_stars/hlsp_tica_tess_ffi_s*{}-cam{}-ccd{}_tess_*cat.h5'.format(dstem, SECTOR, i, j)))
            print(ref_file)
            _common.run_command('wcs_step2',
                                ['-s', SECTOR, '-ca', i, '-cd', j,
                                 '-rd', '{}/{}'.format(dstem, ref_file),
                                 '-if'] + _common.sorted_glob('{}/tess*-{}-{}-*'.format(dstem, i, j))
                                + ['-fd', 6, '--savediaginfo', '-dbg', args.debug,
                                   '--log', 'tica_wcs_step2_spoc.log'])
    return 0


if __name__ == "__main__":
    sys.exit(main())
