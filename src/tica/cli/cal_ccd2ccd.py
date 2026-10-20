#
#Copyright (c) 2021 Michael Fausnaugh
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the Software), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in all
#copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#SOFTWARE.

import argparse
import sys
from time import time

import tica
from tica.cli._common import (add_file_list_args, get_calibration, load_calibration,
                              map_files, read_file_list)
from tica.tica import CCD_File

DESCRIPTION = """

    This script calibrates raw FFI FITS files.

    The list of FITS files to calibrate should be saved in a plain text
    file, with one file per line.  The text file is the positional argument for this script.

    The input FITS files need to be saved as individual CCDs, as available in
    the SPOC raw *ffir*fits files available on MAST
    (https://archive.stsci.edu/tess/bulk_downloads/bulk_downloads_ffi-tp-lc-dv.html;
    scroll down to "Uncalibrated FFIs").

    The calibrated files will be saved as individual CCDs in FITS format, with a
    `.cal.` string added to the names.

    """


def worker(in_tuple):
    filename, outdir = in_tuple
    im = CCD_File(filename, calibration=get_calibration(), outdir=outdir)
    im.write_calibrate()


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-cal-ccd2ccd', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_file_list_args(parser)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    tica.setup_logging(debug=args.debug, filename=args.log)

    inlist = read_file_list(args.fileinputs)
    # setup calibration object before processing files so it is done just once
    calibration = load_calibration(args.caldir)

    starttime = time()
    map_files(worker, [(filename, args.outdir) for filename in inlist],
              processes=args.parallel, calibration=calibration)
    runtime = time() - starttime

    print("Runtime: {0:.2f}sec".format(runtime), "parallel" if args.parallel > 1 else "single")
    return 0


if __name__ == "__main__":
    sys.exit(main())
