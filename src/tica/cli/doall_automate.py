import argparse
import glob
import os
import subprocess
import sys

from tica.cli import _common

DESCRIPTION = """\
Process the newest POC orbit segment end to end; meant to run from cron.

Finds the most recently modified orbit-<N> directory under --dstem, works out
the orbit segment (o1a, o1b, o2a, ...), and skips it if --records already
lists it with the same file counts. Otherwise it refreshes the ephemeris and
runs, in <workdir>/sector<S>: tica-calibrate-tso, tica-darktime,
tica-wcs-step1-allcam-allccd (o1a only), tica-wcs-step2-allcam-allccd,
tica-stage-delivery and tica-check-delivery, then appends to --records,
updates the production table, and emails the result.

Each path, core count and recipient list can also be set with the
environment variable shown in its help. The defaults are the MIT production
settings.

Exit codes: 0 done or nothing to do; 1 off-nominal downlink, not processed;
2 a step reported a configuration error; 3 a step failed unexpectedly."""

# exit codes of the step commands
STEP_OK, STEP_ERROR, STEP_CONFIG_ERROR = 0, 1, 2

DEFAULT_MAIL_START = "mmfausnaugh@gmail.com,qlp-operators@mit.edu"
DEFAULT_MAIL_SUCCESS = ("mmfausnaugh@gmail.com,roland@space.mit.edu,qlp-operators@mit.edu,"
                        "fleming@stsci.edu,tberger@stsci.edu,jimig@stsci.edu,"
                        "grr@space.mit.edu,rethiraj@ttu.edu")
DEFAULT_MAIL_ERROR = "mmfausnaugh@gmail.com,petitpas@mit.edu"


class Abort(Exception):
    """Stop the run with the given exit code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _env(name, default):
    return os.environ.get(name, default)


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-doall-automate', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orbit", help="process this orbit instead of the detected one "
                        "(the segment, file counts and stem are still detected from the newest orbit)")
    parser.add_argument("--segment", help="process this segment (e.g. o1a) instead of the detected one")
    parser.add_argument("--caldir", default=_env("TICA_CALDIR", "/pdo/users/faus/python/tica/calibration_200sec"),
                        help="calibration models [TICA_CALDIR] (default: %(default)s)")
    parser.add_argument("--ncores", type=int, default=int(_env("TICA_NCORES", "57")),
                        help="cores for tica-calibrate-tso [TICA_NCORES] (default: %(default)s)")
    parser.add_argument("--ncores-wcs", type=int, default=int(_env("TICA_NCORES_WCS", "10")),
                        help="cores per CCD for WCS step 2 [TICA_NCORES_WCS] (default: %(default)s)")
    parser.add_argument("--dstem", default=_env("TICA_POC_ORBITS", "/pdo/poc-data/orbits/"),
                        help="POC orbit directories [TICA_POC_ORBITS] (default: %(default)s)")
    parser.add_argument("--outputdir", default=_env("TICA_DELIVERY_DIR", "/pdo/qlp-data/tica-delivery/"),
                        help="delivery root; data are staged in <outputdir>/s<sector> "
                        "[TICA_DELIVERY_DIR] (default: %(default)s)")
    parser.add_argument("--workdir", default=_env("TICA_WORKDIR", "/data/tess/image_sub"),
                        help="processing root; each sector runs in <workdir>/sector<S> "
                        "[TICA_WORKDIR] (default: %(default)s)")
    parser.add_argument("--records", default=_env("TICA_RECORDS", "/data/tess/image_sub/tica-processing-records.txt"),
                        help="processing records file [TICA_RECORDS] (default: %(default)s)")
    parser.add_argument("--ephemeris-kernel", default=_env("TICA_EPHEMERIS_KERNEL", "/pdo/poc-data/kernels/pdo_tess_setup.tm"),
                        help="SPICE kernel setup file [TICA_EPHEMERIS_KERNEL] (default: %(default)s)")
    parser.add_argument("--ephemeris-outdir", default=_env("TICA_EPHEMERIS_OUTDIR", "/pdo/users/faus/python/tica/src/btjd/"),
                        help="directory with tess_ephem.txt to update [TICA_EPHEMERIS_OUTDIR] "
                        "(default: %(default)s)")
    parser.add_argument("--production-table", default=_env("TICA_PRODUCTION_TABLE", "/pdo/users/faus/python/tica/production_table.md"),
                        help="production table to update [TICA_PRODUCTION_TABLE] (default: %(default)s)")
    parser.add_argument("--mail-start", default=_env("TICA_MAIL_START", DEFAULT_MAIL_START),
                        help="comma-separated recipients of the start email [TICA_MAIL_START]")
    parser.add_argument("--mail-success", default=_env("TICA_MAIL_SUCCESS", DEFAULT_MAIL_SUCCESS),
                        help="comma-separated recipients of the success email [TICA_MAIL_SUCCESS]")
    parser.add_argument("--mail-error", default=_env("TICA_MAIL_ERROR", DEFAULT_MAIL_ERROR),
                        help="comma-separated recipients of error emails [TICA_MAIL_ERROR]")
    parser.add_argument("--no-mail", action="store_true",
                        help="print the emails instead of sending them")
    return parser


# ------------------------------------------------------------------ detection
def newest_orbit_dir(dstem):
    """The most recently modified entry of dstem with 'orbit' in its name (ls -rt | tail -1)."""
    entries = [e for e in os.listdir(dstem) if 'orbit' in e]
    if not entries:
        return None
    mtimes = {e: os.path.getmtime(os.path.join(dstem, e)) for e in entries}
    newest = max(mtimes.values())
    # ls -t breaks ties by name and -r reverses the order, so the last line is
    # the alphabetically first of the newest entries
    return min(e for e in entries if mtimes[e] == newest)


def segment_from_orbit(orbit):
    """o1/o2 for odd/even orbits, with the special o3/o4 orbits of sectors 97-98."""
    orbit = int(orbit)
    special = {203: "o3", 204: "o4", 207: "o3", 208: "o4"}
    if orbit in special:
        return special[orbit]
    return "o1" if orbit % 2 == 1 else "o2"


def file_stems(datadir):
    """The distinct date stems (first dash field) of camera-1 files, sorted."""
    return sorted({os.path.basename(f).split('-')[0] for f in glob.glob(os.path.join(datadir, '*-1-*'))})


def sector_from_orbit(orbit):
    orbit = int(orbit)
    special = {203: 97, 204: 97, 205: 98, 206: 98, 207: 98, 208: 98}
    if orbit in special:
        return special[orbit]
    if orbit > 208:
        return (orbit - 11) // 2
    #integer division
    return (orbit - 7) // 2


def record_line(sector, orbit, segment, counts, stem):
    return ' '.join(str(v) for v in [sector, orbit, segment] + list(counts) + [stem])


def already_processed(records, orbit, segment, checkstr):
    """True if a records line for this orbit and segment contains checkstr."""
    try:
        with open(records) as f:
            matches = [line.rstrip('\n') for line in f if '{} {}'.format(orbit, segment) in line]
    except OSError:
        return False
    print(' '.join(' '.join(matches).split()))
    return checkstr in '\n'.join(matches)


# ------------------------------------------------------------------ actions
class Mailer:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def send(self, subject, recipients, message):
        # the shell script sent `echo $msg`, which collapses whitespace
        body = ' '.join(message.split()) + '\n'
        recipients = [r for r in recipients.split(',') if r]
        if not self.enabled:
            print("mail to {}: {}\n{}".format(', '.join(recipients), subject, body))
            return
        try:
            subprocess.run(["mail", "-s", subject] + recipients, input=body, text=True)
        except OSError as e:
            print("could not send mail: {}".format(e))


def check_step(rc, step, args, mailer, where):
    """Apply the step exit-code contract; return 1 to flag an error, 0 if fine."""
    if rc == STEP_OK:
        return 0
    if rc == STEP_CONFIG_ERROR:
        print("Configuration error running {}, exiting.".format(step))
        mailer.send("tica proceessing error", args.mail_error,
                    "Configuration error running {}, {}, exting....".format(step, where))
        raise Abort(2)
    if rc == STEP_ERROR:
        print("Error in {}, continuing forward".format(step))
        return 1
    print("Unknown error (exit code {}), abort!".format(rc))
    mailer.send("tica proceessing error", args.mail_error,
                "Unknown error (exit code {}), {}, aborting....".format(rc, where))
    raise Abort(3)


def move_into(names, destdir):
    """mv <names> <destdir>: report and skip anything that cannot be moved."""
    for name in names:
        dest = os.path.join(destdir, os.path.basename(name))
        try:
            if os.path.isdir(name):
                os.rename(name, dest)
            else:
                os.replace(name, dest)
        except OSError as e:
            print("mv: cannot move {} to {}: {}".format(name, dest, e.strerror))


def tidy_segment(workdir, segment):
    """Move this segment's products into cam<i>_ccd<j>/<segment>/."""
    for i in range(1, 5):
        for j in range(1, 5):
            ccddir = os.path.join(workdir, 'cam{}_ccd{}'.format(i, j))
            if not os.path.isdir(ccddir):
                continue
            print(ccddir)
            segdir = os.path.join(ccddir, segment)
            os.makedirs(segdir, exist_ok=True)
            names = sorted(glob.glob(os.path.join(ccddir, 'tess*fits')))
            if not names:
                print("mv: cannot stat '{}': No such file or directory".format(os.path.join(ccddir, 'tess*fits')))
            move_into(names, segdir)
            products = ['wcs_diags2', 'rms_list']
            if j == 1:
                products += ['cal_timeseries.txt', 'cal_timeseries.png', 'bad_calibration.txt']
            move_into([os.path.join(ccddir, p) for p in products], segdir)


def read_reffin(workdir):
    """Second column of the first line of reffin.txt (cam1_ccd1's reference FIN)."""
    try:
        with open(os.path.join(workdir, 'reffin.txt')) as f:
            fields = f.readline().split()
        return fields[1] if len(fields) > 1 else ''
    except OSError:
        return ''


# ------------------------------------------------------------------ main
def run(args, mailer):
    dstem = args.dstem
    lastdir = newest_orbit_dir(dstem)
    if lastdir is None:
        print("No orbit directories found in {}.".format(dstem))
        return 1
    datadir = os.path.join(dstem, lastdir, 'ffi_fits')
    counts = [len(glob.glob(os.path.join(datadir, '*-{}-*fits*'.format(cam)))) for cam in range(1, 5)]

    #logic for orbit o1a, o1b, o2a, o2b
    orbit = lastdir.split('-')[1]
    segment1 = segment_from_orbit(orbit)
    stems = file_stems(datadir)
    stem = stems[-1] if stems else ''
    if len(stems) == 1:
        segment2 = "a"
    elif len(stems) == 2:
        segment2 = "b"
    else:
        print("found {} processing stems in {}.  Appears to be an off nominal downlink.  "
              "In this case, do not run data automatically.".format(len(stems), datadir))
        return 1
    segment = segment1 + segment2

    #or, can set orbit and segment by hand
    if args.orbit is not None:
        orbit = args.orbit
    if args.segment is not None:
        segment = args.segment

    mod = int(orbit) % 2
    SECTOR = sector_from_orbit(orbit)
    outputSECTOR = '{:04d}'.format(SECTOR)
    delivery = '{}/s{}'.format(args.outputdir, outputSECTOR)
    where = '{} {} {}'.format(SECTOR, orbit, segment)

    #setup control for cron
    checkstr = record_line(SECTOR, orbit, segment, counts, stem)
    processed = already_processed(args.records, orbit, segment, checkstr)
    print(checkstr)
    if processed:
        return 0

    mailer.send("tica s{} {} proceessing started".format(SECTOR, segment), args.mail_start,
                "Automated tica processing as a cron job has started. "
                "An update will be sent when the processing finishes.")

    print("Running tica-dump-ephemeris")
    _common.run_command('dump_ephemeris', ['--ephemeris', args.ephemeris_kernel,
                                           '--outdir', args.ephemeris_outdir])

    workdir = os.path.join(args.workdir, 'sector{}'.format(SECTOR))
    os.makedirs(workdir, exist_ok=True)
    print(workdir)

    errorflag = 0
    print("Running tica-calibrate-tso...")
    o1, o2 = (orbit, "None") if mod == 1 else ("None", orbit)
    rc = _common.run_command('calibrate_tso', ['--o1', o1, '--o2', o2, '--orbseg', segment,
                                               '--dstem', dstem, '--caldir', args.caldir,
                                               '--ncores', args.ncores], cwd=workdir)
    errorflag |= check_step(rc, 'tica-calibrate-tso', args, mailer, where)

    print("Running tica-darktime...")
    if 'o1a' in segment:
        _common.run_command('darktime', ['--save_reflist', '--save_reffin', '--use_first_ccd',
                                         '--orbit', segment], cwd=workdir)
        reffin = read_reffin(workdir)
        print("Running tica-wcs-step1-allcam-allccd...")
        rc = _common.run_command('wcs_step1_allccd', ['--sector', SECTOR, '--dstem', './',
                                                      '--reffin', reffin], cwd=workdir)
        errorflag |= check_step(rc, 'tica-wcs-step1-allcam-allccd', args, mailer, where)
    else:
        _common.run_command('darktime', ['--orbit', segment], cwd=workdir)

    print("Running tica-wcs-step2-allcam-allccd...")
    rc = _common.run_command('wcs_step2_allccd', ['--sector', SECTOR, '--dstem', './',
                                                  '--ncores', args.ncores_wcs], cwd=workdir)
    errorflag |= check_step(rc, 'tica-wcs-step2-allcam-allccd', args, mailer, where)

    tidy_segment(workdir, segment)

    print("Running tica-stage-delivery...")
    _common.run_command('stage_delivery', ['v01', delivery, segment, SECTOR], cwd=workdir)

    print("Running tica-check-delivery...")
    if _common.run_command('check_delivery', [delivery], cwd=workdir) != 0:
        print("Error running tica-check-delivery.")
        errorflag = 1

    print("my error flag", errorflag)
    if errorflag == 0:
        mailer.send("tica s{} {} proceessing".format(SECTOR, segment), args.mail_success,
                    "TICA s{} {} processing complete with no errors. Data can be retrieved at {}".format(
                        SECTOR, segment, delivery))
        with open(args.records, 'a') as f:
            f.write(checkstr + ' finished\n')
        table_args = ['--segments', segment] + (['--wcs1'] if 'o1a' in segment else [])
        _common.run_command('production_table', table_args + ['--output', args.production_table],
                            cwd=workdir)
    else:
        mailer.send("tica s{} {} proceessing".format(SECTOR, segment), args.mail_error,
                    "TICA s{} {} processing complete, but there were errors. Look in {} "
                    "(This is a first test of automated tica scripts. )".format(SECTOR, segment, delivery))
        with open(args.records, 'a') as f:
            f.write(checkstr + ' error\n')
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(args, Mailer(enabled=not args.no_mail))
    except Abort as e:
        return e.code


if __name__ == "__main__":
    sys.exit(main())
