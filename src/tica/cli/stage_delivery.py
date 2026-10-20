import argparse
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

from tica.cli import _common

DESCRIPTION = """\
Copy a processed orbit segment into a MAST delivery directory with HLSP names.

Run from the sector directory. For each CCD, the FFIs in cam<i>_ccd<j>/<segment>/
are copied to <outdir>/cam<i>-ccd<j>/ as

  hlsp_tica_tess_ffi_s<sector>-<orbit>-<fin>-cam<i>-ccd<j>_tess_<version>_img.fits

and refout/reftica_s<sector>_<i>-<j>.h5 is copied to <outdir>/ref-stars/ as

  hlsp_tica_tess_ffi_s<sector>-cam<i>-ccd<j>_tess_<version>_cat.h5"""


def orbit_label(segment):
    """o1..o4 from a segment name such as o1a; the last match wins."""
    orbit = ''
    for label in ('o1', 'o2', 'o3', 'o4'):
        if label in segment:
            orbit = label
    return orbit


def do_move(camnum, ccdnum, version, outdir, subdir, sector):
    outputSECTOR = '{:04d}'.format(int(sector))
    cam, ccd = 'cam{}'.format(camnum), 'ccd{}'.format(ccdnum)
    indir = os.path.abspath('cam{}_ccd{}/{}'.format(camnum, ccdnum, subdir))

    outdir_use = '{}/{}-{}'.format(outdir, cam, ccd)
    if os.path.isdir(outdir_use):
        print(outdir_use + " exists")
    else:
        os.makedirs(outdir_use, exist_ok=True)

    orbit = orbit_label(subdir)

    for path in _common.sorted_glob(os.path.join(indir, 'tess*fits')):
        ii = os.path.basename(path)
        #fin can be got from the filename
        fin = ii.split('-')[1]
        shutil.copyfile(path, '{}/hlsp_tica_tess_ffi_s{}-{}-{}-{}-{}_tess_{}_img.fits'.format(
            outdir_use, outputSECTOR, orbit, fin, cam, ccd, version))

    #copy the reference star list
    os.makedirs(outdir + '/ref-stars', exist_ok=True)
    ref = os.path.abspath('refout/reftica_s{}_{}-{}.h5'.format(sector, camnum, ccdnum))
    try:
        shutil.copyfile(ref, '{}/ref-stars/hlsp_tica_tess_ffi_s{}-{}-{}_tess_{}_cat.h5'.format(
            outdir, outputSECTOR, cam, ccd, version))
    except FileNotFoundError as e:
        print(e)


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-stage-delivery', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="delivery version, e.g. v01")
    parser.add_argument("outdir", help="delivery directory, e.g. <delivery root>/s0098")
    parser.add_argument("segment", help="orbit segment subdirectory, e.g. o1a")
    parser.add_argument("sector", type=int, help="sector number")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    outdir = os.path.abspath(args.outdir)

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(do_move, camnum, ccdnum, args.version, outdir, args.segment, args.sector)
                   for camnum in range(1, 5) for ccdnum in range(1, 5)]
        for future in futures:
            future.result()
    return 0


if __name__ == "__main__":
    sys.exit(main())
