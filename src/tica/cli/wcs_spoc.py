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

All calibrated FFIs (*ffir*.cal.fits*) must be in <dstem>, regardless of camera
or CCD. The log goes to tica_wcs_step2_spoc.log in the current directory.

Exit codes: 0 success; 1 a CCD failed or had no star list or FFIs."""


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

    errorflag = 0
    for i in range(1, 5):
        for j in range(1, 5):
            # star lists of several versions (v01, v02, ...) may be present; use the latest
            ref_files = _common.sorted_glob('{}/ref_stars/hlsp_tica_tess_ffi_s{:04d}-cam{}-ccd{}_tess_*cat.h5'.format(
                dstem, int(SECTOR), i, j))
            imgfiles = _common.sorted_glob('{}/tess*-{}-{}-*ffir*.cal.fits*'.format(dstem, i, j))
            if not ref_files or not imgfiles:
                print('cam{} ccd{}: no {} found, skipping'.format(
                    i, j, 'reference star list' if not ref_files else 'calibrated FFIs'))
                errorflag = 1
                continue
            print(ref_files[-1])
            rc = _common.run_command('wcs_step2',
                                     ['-s', SECTOR, '-ca', i, '-cd', j, '-rd', ref_files[-1],
                                      '-if'] + imgfiles
                                     + ['-fd', 6, '--savediaginfo', '-dbg', args.debug,
                                        '--log', 'tica_wcs_step2_spoc.log'])
            if rc != 0:
                errorflag = 1
    return errorflag


if __name__ == "__main__":
    sys.exit(main())
