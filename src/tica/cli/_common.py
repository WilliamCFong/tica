"""Helpers shared by the TICA command-line tools."""

import glob
import logging
import os
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

import tica

logger = logging.getLogger(__name__)

# Calibration models used by the pool workers. Each worker process gets its own
# copy through the Pool initializer, so this works with both fork and spawn.
_calibration = None


def set_calibration(calibration):
    global _calibration
    _calibration = calibration


def get_calibration():
    return _calibration


def ref_stars_path(refdir, sector, camnum, ccdnum):
    """The WCS reference star list made by tica-wcs-step1 for one CCD."""
    return os.path.join(refdir, 'reftica_s{}_{}-{}.h5'.format(int(sector), camnum, ccdnum))


def checkout_root():
    """The TICA checkout this package is installed from (an editable install), or None."""
    root = Path(tica.__file__).resolve().parents[2]
    if (root / 'pyproject.toml').is_file() and (root / 'src' / 'tica').is_dir():
        return str(root)
    return None


def add_version_arg(parser):
    parser.add_argument("--version", action="version", version="tica %s" % tica.version)


def add_file_list_args(parser, caldir=True, parallel="count", log_default=None):
    """Arguments shared by the scripts that process a list of FITS files.

    parallel="count" takes a number of processes; parallel="flag" is a switch
    that uses every processor.
    """
    parser.add_argument("fileinputs", metavar="FILE",
                        help="text file containing a list of FITS files to process, one per line")
    parser.add_argument("--outdir", metavar="DIRECTORY", default=".",
                        help="directory in which to place the results (default: current directory)")
    if caldir:
        parser.add_argument("--caldir", metavar="DIRECTORY", default=None,
                            help="calibration directory")
    add_version_arg(parser)
    if parallel == "count":
        parser.add_argument("--parallel", type=int, default=1,
                            help="run files in parallel on number of processors specified here")
    else:
        parser.add_argument("--parallel", action="store_true",
                            help="run files in parallel on all processors")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="emit extra diagnostic information to log")
    parser.add_argument("-l", "--log", metavar="LOG_FILE", default=log_default,
                        help="save logging output to this file")


def read_file_list(path):
    """Read a text file with one file name per line."""
    try:
        return list(np.atleast_1d(np.genfromtxt(path, dtype=str)))
    except IOError:
        logger.error("input file not found: {}".format(path))
        raise SystemExit(1)


def caldir_error(caldir):
    """Why caldir is not a usable calibration directory, or None if it is."""
    from tica.tica import CalibrationError, check_calibration_dir
    try:
        check_calibration_dir(caldir)
    except CalibrationError as e:
        return str(e)
    return None


def load_calibration(caldir):
    """Load calibration models, or exit 2 (configuration error) if caldir is not usable."""
    error = caldir_error(caldir)
    if error:
        logger.error(error)
        print("Configuration Error. {}".format(error), file=sys.stderr)
        raise SystemExit(2)
    from tica.tica import Calibration
    return Calibration(calibration_dir=caldir)


def map_files(worker, items, processes=1, calibration=None):
    """Run worker on each item, in a process pool if processes > 1.

    Every item is processed before any worker exception is re-raised.
    """
    set_calibration(calibration)
    if processes > 1:
        with Pool(processes, initializer=set_calibration, initargs=(calibration,)) as pool:
            results = [pool.apply_async(worker, (item,)) for item in items]
            pool.close()
            pool.join()
            return [result.get() for result in results]
    return [worker(item) for item in items]


def setup_run_logging(prog, args, log, debug=False, log_cwd=True, skip=()):
    """Set up logging and record the run configuration.

    tica-production-table parses these lines from the logs, so keep the
    wording unchanged. It reads the camera and CCD from the "working
    directory" line, so the WCS steps, which run from the sector directory,
    leave that line out (log_cwd=False).
    """
    if log is not None:
        logdir = os.path.dirname(os.path.abspath(log))
        os.makedirs(logdir, exist_ok=True)
    tica.setup_logging(debug=debug, filename=log)
    for info_line in tica.platform_info():
        logger.info(info_line)
    logger.info('python environment:  {}'.format(os.getenv('CONDA_DEFAULT_ENV')))
    logger.info('program: {}'.format(prog))
    if log_cwd:
        logger.info('working directory {}'.format(os.getcwd()))
    logger.info('argument parameters:')
    for key, value in vars(args).items():
        if key not in skip:
            logger.info('     {} = {}'.format(key, value))


def _command(module, args):
    return [sys.executable, "-m", "tica.cli." + module] + [str(a) for a in args]


def run_command(module, args, cwd=None):
    """Run ``python -m tica.cli.<module> <args>`` and return its exit code.

    The orchestration commands run their steps through this function, so each
    step gets its own process (and logging setup), as the shell scripts did.
    """
    cmd = _command(module, args)
    logger.debug("running %s", " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd).returncode


def run_parallel(jobs, cwd=None):
    """Run several (module, args) commands at once; return their exit codes.

    This replaces the shell pattern ``cmd & ... wait``.
    """
    procs = []
    for module, args in jobs:
        cmd = _command(module, args)
        logger.debug("starting %s", " ".join(cmd))
        procs.append(subprocess.Popen(cmd, cwd=cwd))
    return [proc.wait() for proc in procs]


def sorted_glob(pattern):
    """Matching paths in the order `ls` lists them."""
    return sorted(glob.glob(pattern))
