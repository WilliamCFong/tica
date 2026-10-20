#
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
import logging
import os
import sys
from time import time

import numpy as np

from tica.cli._common import (add_file_list_args, get_calibration, load_calibration,
                              map_files, read_file_list, setup_run_logging)
from tica.tica import FFI_File

DESCRIPTION = """

    This script calibrates raw FFI FITS files.

    The list of FITS files to calibrate should be be saved in a plain text
    file, with one file per line.  The text file is the positional argument for this script.

    The input FITS files need to be saved as combined camera FITS files, as
    used by the TESS Science Office (TSO) and Payload Operations
    Center (POC).  These files are not publicly available at this time.

    The calibrated files will be saved as individual CCDs in FITS
    format, with a `_ccd?.cal.` string added to the names.

    """

TIMESERIES_FILE = 'cal_timeseries.txt'
TIMESERIES_COLUMNS = ('name',
                      'mode_ccd1', 'mode_ccd2', 'mode_ccd3', 'mode_ccd4',
                      'outputA_ccd1', 'outputB_ccd1', 'outputC_ccd1', 'outputD_ccd1',
                      'outputA_ccd2', 'outputB_ccd2', 'outputC_ccd2', 'outputD_ccd2',
                      'outputA_ccd3', 'outputB_ccd3', 'outputC_ccd3', 'outputD_ccd3',
                      'outputA_ccd4', 'outputB_ccd4', 'outputC_ccd4', 'outputD_ccd4')


def ffi_diagnostics(im):
    """Background modes and 1D bias corrections of a calibrated FFI_File."""
    #mode of the image, to track scattered light
    modes = []
    #1D bias corrections, by CCD output channel,
    #to track saturation/bad calibration
    bias_corrections = []
    for ccd in im.calibrated_CCDs:
        modes.append(ccd.get_image_mode(10**(np.r_[2.7:7.7:4000j])))
        bias_corrections = np.r_[bias_corrections, ccd.overclock_corrections]
    return np.r_[modes, bias_corrections]


def worker(in_tuple):
    filename, outdir, trim, orbit_segment, no_gzip, no_diagnostics, no_write = in_tuple

    im = FFI_File(filename,
                  calibration=get_calibration(),
                  outdir=outdir,
                  orbit_segment=orbit_segment)

    if no_write:
        pass
    elif trim:
        im.write_calibrated_trimmed_CCDs(no_gzip=no_gzip)
    else:
        im.write_calibrated_CCDs(no_gzip=no_gzip)

    if not no_diagnostics:
        return (filename, ffi_diagnostics(im))


def write_timeseries(outdir, results):
    """Append the per-file background modes and bias corrections."""
    out_fname = np.array([os.path.basename(fname) for fname, _ in results]).astype(str)
    out_data = np.array([data for _, data in results])
    path = os.path.join(outdir, TIMESERIES_FILE)
    with open(path, 'a') as fout:
        if fout.tell() == 0:
            fout.write('{:>45s} '.format(TIMESERIES_COLUMNS[0])
                       + ''.join('{:>15s}'.format(c) for c in TIMESERIES_COLUMNS[1:])
                       + '\n')
        for idx in np.argsort(out_fname):
            fout.write('{:>45s} '.format(out_fname[idx])
                       + ''.join('{:>15.2f}'.format(v) for v in out_data[idx][:20])
                       + '\n')


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-cal-ffi2ccds', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_file_list_args(parser, log_default='tica.log')
    parser.add_argument("--trim", action="store_true", help="trim calibration pixels from edges")
    parser.add_argument("--orb_seg", type=str,
                        help="if set, write ORB_SEG header keyword in calibrated files.")
    parser.add_argument("--no_gzip", action="store_true",
                        help="if set, do not write gzipped files regardless of input file extension.")
    parser.add_argument("--no_diagnostics", action="store_true",
                        help="if set, do not write txt file with "
                        "1D bias corrections or background estimates.")
    parser.add_argument("--no_write", action="store_true",
                        help="if set, calibrate without writing any FITS files, e.g. to "
                        "record only the diagnostics.")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_run_logging(parser.prog, args, args.log, debug=args.debug)
    logger = logging.getLogger(__name__)

    inlist = read_file_list(args.fileinputs)
    # setup calibration object before processing files so it is done just once
    calibration = load_calibration(args.caldir)

    starttime = time()
    items = [(filename, args.outdir, args.trim, args.orb_seg, args.no_gzip, args.no_diagnostics,
              args.no_write)
             for filename in inlist]
    results = map_files(worker, items, processes=args.parallel, calibration=calibration)

    if not args.no_diagnostics:
        write_timeseries(args.outdir, results)

    runtime = time() - starttime

    print("Runtime: {0:.2f}sec".format(runtime), "N Pools = {}".format(args.parallel))
    logger.info("N Pools = {}".format(args.parallel))
    logger.info("Runtime: {0:.2f}sec".format(runtime))
    return 0


if __name__ == "__main__":
    sys.exit(main())
