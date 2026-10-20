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
# The trimmed-CCD variant (tica-trim-ccds2ffi) was distributed under:
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

import numpy as np
from astropy.io import fits

import tica
from tica.cli._common import add_version_arg
from tica.tica import CCD, FFI


def pad_trimmed_ccd(im):
    """Restore the calibration-pixel border removed by --trim."""
    im = np.c_[np.zeros((2048, 44)), im, np.zeros((2048, 44))]
    return np.r_[im, np.zeros((30, 2136))]


def combine_ccds(files, outdir, outfile, trimmed=False):
    images = [fits.getdata(f) for f in files]
    if trimmed:
        images = [pad_trimmed_ccd(im) for im in images]

    im = FFI(np.zeros((4156, 4272)))
    im.CCDs = np.asarray([CCD(image) for image in images])
    imout = im.get_frame(im.CCDs)
    fits.writeto(os.path.join(outdir, outfile), imout)


def build_parser(prog, description):
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("f1")
    parser.add_argument("f2")
    parser.add_argument("f3")
    parser.add_argument("f4")
    parser.add_argument("--outdir", metavar="DIRECTORY", default=".",
                        help="directory in which to place the results (default: current directory)")
    parser.add_argument("--outfile", required=True, help="output file name")
    add_version_arg(parser)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="emit extra diagnostic information to log")
    parser.add_argument("-l", "--log", metavar="LOG_FILE", help="log file")
    return parser


def _run(argv, prog, description, trimmed):
    args = build_parser(prog, description).parse_args(argv)

    tica.setup_logging(debug=args.debug, filename=args.log)

    starttime = time()
    combine_ccds([args.f1, args.f2, args.f3, args.f4], args.outdir, args.outfile, trimmed=trimmed)
    runtime = time() - starttime

    print("Runtime: {0:.2f}sec".format(runtime))
    return 0


def main(argv=None):
    """tica-ccds2ffi: combine four CCD images into a full camera frame."""
    return _run(argv, 'tica-ccds2ffi',
                "Combine four CCD images into one full-frame image", trimmed=False)


def main_trim(argv=None):
    """tica-trim-ccds2ffi: the same, for CCD images written with --trim."""
    return _run(argv, 'tica-trim-ccds2ffi',
                "Combine four trimmed CCD images into one full-frame image", trimmed=True)


if __name__ == "__main__":
    sys.exit(main())
