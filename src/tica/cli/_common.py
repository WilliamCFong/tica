"""Helpers shared by the TICA command-line tools."""

import logging
import os
import subprocess
import sys
from multiprocessing import Pool

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


def load_calibration(caldir):
    """Load calibration models, or exit 1 if no directory was given."""
    if not caldir:
        logger.error("No calibration dir specified.  You must choose"
                     "calibration models appropriate for the exposure time")
        raise SystemExit(1)
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


def run_command(module, args):
    """Run ``python -m tica.cli.<module> <args>`` and return its exit code.

    The orchestration commands run their steps through this function, so each
    step gets its own process (and logging setup), as the shell scripts did.
    """
    cmd = [sys.executable, "-m", "tica.cli." + module] + [str(a) for a in args]
    logger.debug("running %s", " ".join(cmd))
    return subprocess.run(cmd).returncode
