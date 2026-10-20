import argparse
import os
import sys

from tica.cli import _common

DESCRIPTION = """\
Calibrate a directory of raw SPOC FFIs with tica-cal-ccd2ccd.

This command works exclusively on raw SPOC FFIs (*ffir*fits files), which can
be downloaded from
https://archive.stsci.edu/tess/bulk_downloads/bulk_downloads_ffi-tp-lc-dv.html.

It lists every *ffir*fits file in the input directory, for all cameras and
CCDs, in ./inlist, and calibrates them into the current directory. The log is
written to ../tica.log. Calibrating FFIs from several sectors at once works,
but is not good practice because the calibration models can change between
sectors."""


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-calibrate-spoc', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", required=True, metavar="DIRECTORY",
                        help="directory where the raw FITS files are saved")
    parser.add_argument("--caldir", required=True, metavar="DIRECTORY",
                        help="directory with calibration models for the exposure time, "
                        "e.g. calibration_10min from the TICA repository")
    parser.add_argument("--ncores", type=int, default=1,
                        help="number of cores to use for parallel processing (default: 1)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    input_dir_use = os.path.realpath(args.input_dir)
    #make in list for tica
    with open('inlist', 'a') as fout:
        for i in range(1, 5):
            for j in range(1, 5):
                for f in _common.sorted_glob('{}/tess*-{}-{}-*ffir*fits*'.format(input_dir_use, i, j)):
                    fout.write(f + '\n')

    return _common.run_command('cal_ccd2ccd', ['inlist', '--outdir', '.', '--caldir', args.caldir,
                                               '--log', '../tica.log', '--parallel', args.ncores])


if __name__ == "__main__":
    sys.exit(main())
