#
# Copyright (C) 2017 - Massachusetts Institute of Technology (MIT)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import argparse
import os
import sys
from time import time

import tica
from tica.cli._common import (add_file_list_args, get_calibration, load_calibration,
                              map_files, read_file_list)
from tica.tica import FFI_File


def worker(in_tuple):
    filename, outdir = in_tuple
    im = FFI_File(filename, calibration=get_calibration(), outdir=outdir)
    im.write_frame(im.calibrated_CCDs, '.cal')


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-cal-ffi2ffi', description="Calibrate FITS files")
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
