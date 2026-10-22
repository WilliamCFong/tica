import argparse
import glob
import os
import sys
from multiprocessing import Pool

import h5py
import numpy as np
from astropy.io import fits

DESCRIPTION = """\
Check a staged TICA delivery directory before it is sent to MAST.

The directory must contain cam<i>-ccd<j> directories for all 16 CCDs and a
ref-stars directory with one star list per CCD. The star lists must have the
expected columns without NaNs. Every CCD directory should hold the same number
of FFIs as cam4-ccd4, each with two extensions, a SIP WCS, and a valid star
table. Problems with individual FFIs are printed but do not change the exit
code; missing directories, star lists, or columns exit with code 1."""

#every file should have:
#--valid checkusm and datasum
#--calibrated data
#   --an added plus would be that the data are correction,
#      or at least don't look bad
#--a WCS solution
#--two headers, the second being  a fits table with a valid binary table

#***what should happen if there is invalid data?? (cam1 saturated)***


#mast can check the names, and probably the checksum and datasum

#star lists should have 11 columns, like this
#'blkidxs', 'contrastcols', 'contrastrows','decs','obscols','obsrows', 'predcols', 'predrows', 'ras', 'tics','tmags'

#every delivery should have 16 ccd directories, with either N FFIs per delivery or N-1
#there should be a ref_stars directory with the star lists, 16 files, one per CCD

CCD_DIRS = ['cam1-ccd1', 'cam1-ccd2', 'cam1-ccd3', 'cam1-ccd4',
            'cam2-ccd1', 'cam2-ccd2', 'cam2-ccd3', 'cam2-ccd4',
            'cam3-ccd1', 'cam3-ccd2', 'cam3-ccd3', 'cam3-ccd4',
            'cam4-ccd1', 'cam4-ccd2', 'cam4-ccd3', 'cam4-ccd4']
REF_DIR = 'ref-stars'

REF_COLUMNS = ['blkidxs',
               'contrastcols', 'contrastrows',
               'decs',
               'obscols', 'obsrows',
               'predcols', 'predrows',
               'ras',
               'tics', 'tmags']

#because the bintables are record arrays, can't check the shape, but can use the header
#but, header has 18 columns, for some reason?
FFI_COLUMNS = ['TIC', 'FLXCOL', 'FLXROW', 'FLXVALID']


def check_directories(duse):
    """Return True if all 16 CCD directories and ref-stars exist."""
    topdirs = glob.glob(os.path.join(duse, '*'))
    for d in CCD_DIRS + [REF_DIR]:
        if os.path.join(duse, d) not in topdirs:
            print('Directory {} not in expected CCD/ref_star directories'.format(os.path.join(duse, d)))
            return False
    return True


def check_ref_stars(duse):
    """Return True if there is one complete star list per CCD."""
    ref_files = glob.glob(os.path.join(duse, REF_DIR, '*'))

    if len(ref_files) != 16:
        print('Found {} ref_star files instead of 16'.format(len(ref_files)))
        return False

    for stem in CCD_DIRS:
        if not any(stem in ref_file for ref_file in ref_files):
            print('Found unexpected file {} in ref_star directory'.format(stem))
            return False

    for ref_file in ref_files:
        with h5py.File(ref_file, 'r') as f:
            for col in REF_COLUMNS:
                if col not in f.keys():
                    print('{}: missing column {}'.format(ref_file, col))
                    return False
                if any(np.isnan(f[col])):
                    print('{}: NaN value in column {}'.format(ref_file, col))
                    return False
    return True


def check_with_message(condition, message):
    """Print message if condition fails; return 1 for a problem, 0 otherwise."""
    if not condition:
        # flushed: pool workers end with os._exit, which drops buffered output
        print(message, flush=True)
        return 1
    return 0


def worker(in_tuple):
    """Check the FFIs in one CCD directory, printing any problems.

    Returns (number of FFIs, number of problems found).
    """
    d, N_cad_check = in_tuple

    problems = 0
    ffi_files = glob.glob(d + '/*fits')
    if len(ffi_files) != N_cad_check:
        # not counted as a problem: CCDs can miss different cadences in the raw data
        print('Note: {} has {} FFIs, cam4-ccd4 has {}'.format(d, len(ffi_files), N_cad_check), flush=True)
    for ffi in ffi_files:
        with fits.open(ffi) as f:
            hdr = f[0].header
            problems += check_with_message(len(f) == 2,
                               '  File {} has {} extensions'.format(ffi, len(f)))
            problems += check_with_message(hdr['NAXIS1'] == 2136,
                               '  File {} has NAXIS1 equal to {}, should be 2136'.format(ffi, hdr['NAXIS1']))
            problems += check_with_message(hdr['NAXIS2'] == 2078,
                               '  File {} has NAXIS2 equal to {}, should be 2078'.format(ffi, hdr['NAXIS2']))
            problems += check_with_message(hdr['CTYPE1'] == 'RA---TAN-SIP',
                               '  File {} has CTYPE1 equal to {}, should be "RA--TAN-SIP"'.format(ffi, hdr['CTYPE1']))
            problems += check_with_message(hdr['CTYPE2'] == 'DEC--TAN-SIP',
                               '  File {} has CTYPE2 equal to {}, should be "DEC--TAN-SIP'.format(ffi, hdr['CTYPE2']))
            problems += check_with_message(hdr['CRPIX1'] == 1069.0,
                               '  File {} has CRPIX1 equal to {}, should be 1069.0'.format(ffi, hdr['CRPIX1']))
            problems += check_with_message(hdr['CRPIX2'] == 1024.0,
                               '  File {} has CRPIX2 equal to {}, should be 1024.0'.format(ffi, hdr['CRPIX2']))
            problems += check_with_message(not np.isnan(hdr['CRVAL1']),
                               '  File {} CRVAL1 is {} (should not be Nan)'.format(ffi, hdr['CRVAL1']))
            problems += check_with_message(not np.isnan(hdr['CRVAL2']),
                               '  File {} CRVAL2 is {} (should not be Nan)'.format(ffi, hdr['CRVAL2']))
            problems += check_with_message(not hdr['A_ORDER'] == 0,
                               '  File {} A_ORDER is {} (should not be 0)'.format(ffi, hdr['A_ORDER']))
            problems += check_with_message(not np.isnan(hdr['A_ORDER']),
                               '  File {} A_ORDER is {} (should not be NaN)'.format(ffi, hdr['A_ORDER']))
            problems += check_with_message(not hdr['B_ORDER'] == 0,
                               '  File {} B_ORDER is {} (should not be 0)'.format(ffi, hdr['B_ORDER']))
            problems += check_with_message(not np.isnan(hdr['B_ORDER']),
                               '  File {} B_ORDER is {} (should not be NaN)'.format(ffi, hdr['B_ORDER']))

            for col in FFI_COLUMNS:
                if col not in f[1].data.names:
                    print('  File {} has unexpected column {} in extension 1'.format(ffi, col), flush=True)
                    problems += 1
                if any(np.isnan(f[1].data[col])):
                    print('  File {} has NaN in column {} (ext 1)'.format(ffi, col), flush=True)
                    problems += 1
    return len(ffi_files), problems


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-check-delivery', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("delivery_dir", metavar="DIRECTORY",
                        help="staged delivery directory, e.g. <outputdir>/s0098")
    parser.add_argument("--processes", type=int, default=16,
                        help="number of CCD directories to check in parallel (default: 16)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    duse = args.delivery_dir

    #start by checking the directory structure, number of files
    if not check_directories(duse):
        return 1
    #check the ref_stars files, and that no columns are none
    if not check_ref_stars(duse):
        return 1

    #check the right number of files in each directory
    N_cad_check_o1 = len(glob.glob(os.path.join(duse, 'cam4-ccd4/*fits')))

    with Pool(args.processes) as p:
        results_async = [p.apply_async(worker, ((os.path.join(duse, d), N_cad_check_o1),))
                         for d in CCD_DIRS]
        p.close()
        p.join()

        nffis = problems = 0
        for d, res in zip(CCD_DIRS, results_async):
            try:
                n, p_ = res.get()
            except Exception as e:
                print('{}: could not check: {}'.format(os.path.join(duse, d), e))
                return 1
            nffis += n
            problems += p_

    print('Checked {} FFIs in 16 CCD directories and 16 star lists in {}: {}'.format(
        nffis, duse, 'no problems' if problems == 0 else '{} problems, listed above'.format(problems)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
