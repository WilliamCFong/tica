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
import os
import sys
from time import time

import tica
from tica.cli._common import (add_file_list_args, get_calibration, load_calibration,
                              map_files, read_file_list)
from tica.tica import CCD_File


def worker(in_tuple):
    filename, outdir = in_tuple
    im = CCD_File(filename, calibration=get_calibration(), outdir=outdir)

    inbasename = os.path.splitext(os.path.basename(filename))[0]

    im.report('overclock', save=True, label='overclock_' + inbasename)
    im.report('science', save=True, label='science_' + inbasename)


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-ccd-report', description="Calibrate FITS files")
    add_file_list_args(parser, parallel="flag")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    tica.setup_logging(debug=args.debug, filename=args.log)

    inlist = read_file_list(args.fileinputs)
    # setup calibration object before processing files so it is done just once
    calibration = load_calibration(args.caldir)

    starttime = time()
    map_files(worker, [(filename, args.outdir) for filename in inlist],
              processes=os.cpu_count() if args.parallel else 1, calibration=calibration)
    runtime = time() - starttime

    print("Runtime: {0:.2f}sec".format(runtime), "parallel" if args.parallel else "single")
    return 0


if __name__ == "__main__":
    sys.exit(main())
