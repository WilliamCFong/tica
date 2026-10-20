import argparse
import glob
import os
import sys

from astropy.table import Table

from tica.cli._common import load_calibration
from tica.tica import FFI_File

DESCRIPTION = """\
Tabulate overclock statistics for full-camera FFIs.

For every CCD output channel (sector A-D) of every FFI, record the mean and
standard deviation of the overclock pixels before and after calibration, and
the 1D bias correction that was subtracted. Writes one row per channel, 16 per
FFI, to a CSV table."""

COLUMNS = ('Time', 'ccd', 'sector', 'mean', 'std', 'mean_cal', 'std_cal', 'correct')


def default_inputs():
    """Every file in the current directory except tables and profiles, as before."""
    return sorted(f for f in glob.glob('*')
                  if os.path.isfile(f)
                  and 'txt' not in f and 'csv' not in f and 'profile' not in f)


def overclock_rows(filename, calibration):
    """Return the 16 rows (4 CCDs x 4 output channels) for one camera FFI."""
    im = FFI_File(filename, calibration=calibration, outdir='.')
    rows = []
    for ccd, cal_ccd in zip(im.CCDs, im.calibrated_CCDs):
        labels, means, stds = ccd.report('overclock', save=False, plot=False)
        _, cal_means, cal_stds = cal_ccd.report('overclock', save=False, plot=False)
        _, corrections = ccd.overclock_correct()
        for kk in range(4):
            rows.append((im.header['STARTTJD'], ccd.ccdnum, labels[kk],
                         means[kk], stds[kk], cal_means[kk], cal_stds[kk], corrections[kk]))
    return rows


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-overclock-stats', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("caldir", metavar="CALDIR", help="calibration directory")
    parser.add_argument("files", metavar="FILE", nargs="*",
                        help="camera FFI files (default: every file in the current directory "
                        "whose name does not contain txt, csv, or profile)")
    parser.add_argument("-o", "--output", default="test_stats.csv",
                        help="output CSV table (default: test_stats.csv)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    calibration = load_calibration(args.caldir)

    files = args.files or default_inputs()
    rows = []
    for filename in files:
        print(filename)
        rows.extend(overclock_rows(filename, calibration))

    if not rows:
        print('No input files found.')
        return 1
    Table(rows=rows, names=COLUMNS).write(args.output, overwrite=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
