import argparse
import glob
import os
import shutil
import subprocess
import sys

from btjd import EPHEMERIS_ENV, packaged_ephemeris
from tica.cli import _common, _segments

DESCRIPTION = """\
Process a POC orbit end to end; meant to run from cron.

Takes the orbit given by --orbit, or else the most recently modified
orbit-<N> directory under --dstem, and works out its segments from the FFIs'
cadences (see tica.cli._segments): o1a and o1b (o2a, o2b, ...) for an orbit
downlinked in two halves, or o1 (o2, ...) for one downlinked whole, with
re-delivered downlinks replacing the earlier copy. Each segment that
--records doesn't already list with the same file counts and stamp is
processed in order (or only --segment), in <workdir>/sector<S>: the ephemeris
is refreshed, the segment is calibrated and delivered, then it is appended
to --records, the production table is updated, and the result emailed.

Each calibrated CCD image is written once, straight to the delivery
directory <outputdir>/s<S>, by tica-calibrate-tso --hlspdir (calibration and
WCS fit in memory). No FFIs are kept in <workdir>. For the sector's first
segment (o1a, or a whole o1), which needs a new WCS reference frame, the
steps are:
  tica-calibrate-tso --no_write    backgrounds for tica-darktime, no FFIs
  tica-darktime --save_reffin      pick the reference frame
  tica-calibrate-tso --fin         write the 16 reference CCD images
  tica-wcs-step1-allcam-allccd     reference star lists in refout/
  tica-calibrate-tso --hlspdir     calibrate, fit and deliver every FFI
For later segments, tica-calibrate-tso --hlspdir runs first, then
tica-darktime. Both finish with tica-stage-delivery --ref-stars-only and
tica-check-delivery.

Each path, core count and recipient list can also be set with the
environment variable shown in its help. tica-wcs-step1 reads the TIC through
the libpq service named by TICA_TIC_SERVICE (default: tic). The defaults are the MIT production
settings.

Exit codes: 0 done or nothing to do; 1 off-nominal downlink or no FFIs, not processed;
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


def checkout_path(*parts):
    """A path in the TICA checkout this package runs from, or None without one."""
    root = _common.checkout_root()
    return os.path.join(root, *parts) if root else None


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-doall-automate', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orbit", help="process this orbit instead of the newest one")
    parser.add_argument("--segment", help="process only this segment of the orbit (e.g. o1a, or o1 for "
                        "an orbit downlinked whole). Segments after the sector's first need its "
                        "reference star lists in <workdir>/sector<S>/refout/")
    parser.add_argument("--caldir", default=_env("TICA_CALDIR", checkout_path("calibration_200sec")),
                        help="calibration models [TICA_CALDIR] (default: calibration_200sec in "
                        "the TICA checkout this runs from: %(default)s)")
    parser.add_argument("--ncores", type=int, default=int(_env("TICA_NCORES", "57")),
                        help="cores for tica-calibrate-tso, which also fits the WCS "
                        "[TICA_NCORES] (default: %(default)s)")
    parser.add_argument("--ncores-wcs", type=int, default=int(_env("TICA_NCORES_WCS", "10")),
                        help="unused: the WCS fit now runs in the tica-calibrate-tso pool; "
                        "kept so existing settings still parse [TICA_NCORES_WCS]")
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
    parser.add_argument("--ephemeris-file", default=_env(EPHEMERIS_ENV, None), metavar="FILE",
                        help="tess_ephem.txt to update with tica-dump-ephemeris and read in the "
                        "WCS fit [{}] (default: the copy installed with TICA, {})".format(
                            EPHEMERIS_ENV, packaged_ephemeris()))
    parser.add_argument("--records-copy", default=_env("TICA_RECORDS_COPY", checkout_path() or ""),
                        help="directory to copy the records file to after each run; empty to skip "
                        "[TICA_RECORDS_COPY] (default: the TICA checkout this runs from, if any: "
                        "%(default)s)")
    parser.add_argument("--production-table", default=_env("TICA_PRODUCTION_TABLE",
                                                           checkout_path("production_table.md")),
                        help="production table to update [TICA_PRODUCTION_TABLE] (default: "
                        "production_table.md in the TICA checkout this runs from, or else in "
                        "--workdir: %(default)s)")
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


# o1/o2 (or o3/o4) for an orbit; kept here for callers of this module
segment_from_orbit = _segments.orbit_label


def sector_from_orbit(orbit):
    orbit = int(orbit)
    special = {203: 97, 204: 97, 205: 98, 206: 98, 207: 98, 208: 98}
    if orbit in special:
        return special[orbit]
    if orbit > 208:
        return (orbit - 11) // 2
    #integer division
    return (orbit - 7) // 2


def missing_ref_stars(workdir, sector):
    """The WCS reference star lists from o1a that are not in <workdir>/refout/."""
    paths = [os.path.join(workdir, 'refout', 'reftica_s{}_{}-{}.h5'.format(sector, i, j))
             for i in range(1, 5) for j in range(1, 5)]
    return [p for p in paths if not os.path.isfile(p)]


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


def remove_reference_frames(workdir):
    """Delete the calibrated reference frames written for tica-wcs-step1.

    They have no WCS, so they must not reach the delivery directory.
    """
    for name in glob.glob(os.path.join(workdir, 'cam*_ccd*', 'tess*fits')):
        os.remove(name)


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
            # FFIs, if any were written here by hand-run steps
            move_into(sorted(glob.glob(os.path.join(ccddir, 'tess*fits'))), segdir)
            products = ['wcs_diags2', 'rms_list']
            # tica-darktime writes bad_calibration.txt only for CCDs that have bad cadences
            if os.path.exists(os.path.join(ccddir, 'bad_calibration.txt')):
                products.append('bad_calibration.txt')
            if j == 1:
                # tica-darktime --orbit <segment> names its plot after the segment
                products += ['cal_timeseries.txt', 'cal_timeseries_{}.png'.format(segment)]
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
    if args.orbit is not None:
        orbit = str(int(args.orbit))
    else:
        lastdir = newest_orbit_dir(dstem)
        if lastdir is None:
            print("No orbit directories found in {}.".format(dstem))
            return 1
        orbit = lastdir.split('-')[1]

    try:
        segments = _segments.find_segments(dstem, orbit)
    except _segments.OffNominal as e:
        print("{} Appears to be an off nominal downlink.  In this case, do not run data "
              "automatically.".format(e))
        return 1
    if not segments:
        print("No FFIs found in {}.".format(os.path.join(dstem, 'orbit-{}'.format(orbit), 'ffi_fits')))
        return 1
    if args.segment is not None:
        names = [seg.name for seg in segments]
        segments = [seg for seg in segments if seg.name == args.segment]
        if not segments:
            print("Configuration Error. Orbit {} has no segment {}; its FFIs make {}.".format(
                orbit, args.segment, ', '.join(names)))
            return 2

    SECTOR = sector_from_orbit(orbit)
    ephemeris_updated = False
    for segment in segments:
        #setup control for cron
        # the stem is the latest delivery's tess<stamp>, as in the records from before
        checkstr = record_line(SECTOR, orbit, segment.name, segment.counts(),
                               'tess' + segment.stamps[-1])
        print(checkstr)
        if already_processed(args.records, orbit, segment.name, checkstr):
            continue
        if not ephemeris_updated:
            update_ephemeris(args)
            ephemeris_updated = True
        rc = process_segment(args, mailer, orbit, SECTOR, segment, checkstr)
        if rc:
            return rc
    return 0


def update_ephemeris(args):
    print("Running tica-dump-ephemeris")
    dump_args = ['--ephemeris', args.ephemeris_kernel]
    if args.ephemeris_file:
        # the WCS fit in the later steps reads the same file
        os.environ[EPHEMERIS_ENV] = args.ephemeris_file
        dump_args += ['--output', args.ephemeris_file]
    _common.run_command('dump_ephemeris', dump_args)


def process_segment(args, mailer, orbit, SECTOR, seg, checkstr):
    """Calibrate, fit and deliver one segment; return a nonzero exit code to stop."""
    dstem = args.dstem
    segment = seg.name
    mod = int(orbit) % 2
    outputSECTOR = '{:04d}'.format(SECTOR)
    delivery = '{}/s{}'.format(args.outputdir, outputSECTOR)
    where = '{} {} {}'.format(SECTOR, orbit, segment)

    workdir = os.path.join(args.workdir, 'sector{}'.format(SECTOR))
    if not seg.first_of_sector:
        missing = missing_ref_stars(workdir, SECTOR)
        if missing:
            print("Configuration Error. Segment {} uses the WCS reference star lists made for the "
                  "sector's first segment (o1a, or o1 for a whole orbit), but {} of the 16 are "
                  "missing, e.g. {}. Process that segment first with this --workdir, or copy "
                  "refout/ from the work directory that did.".format(segment, len(missing), missing[0]))
            return 2

    mailer.send("tica s{} {} proceessing started".format(SECTOR, segment), args.mail_start,
                "Automated tica processing as a cron job has started. "
                "An update will be sent when the processing finishes.")

    os.makedirs(workdir, exist_ok=True)
    print(workdir)

    errorflag = 0
    o1, o2 = (orbit, "None") if mod == 1 else ("None", orbit)
    calibrate = ['--o1', o1, '--o2', o2, '--orbseg', segment,
                 '--dstem', dstem, '--caldir', args.caldir, '--ncores', args.ncores]
    deliver = ['--hlspdir', delivery, '--sector', SECTOR]

    if seg.first_of_sector:
        #the WCS reference frame is picked from the whole segment's backgrounds,
        #so record those first without writing any FFIs
        print("Running tica-calibrate-tso --no_write...")
        rc = _common.run_command('calibrate_tso', calibrate + ['--no_write'], cwd=workdir)
        errorflag |= check_step(rc, 'tica-calibrate-tso', args, mailer, where)

        print("Running tica-darktime...")
        _common.run_command('darktime', ['--save_reflist', '--save_reffin', '--use_first_ccd',
                                         '--orbit', segment], cwd=workdir)
        reffin = read_reffin(workdir)

        print("Running tica-calibrate-tso --fin {}...".format(reffin))
        rc = _common.run_command('calibrate_tso', calibrate + ['--fin', reffin], cwd=workdir)
        errorflag |= check_step(rc, 'tica-calibrate-tso', args, mailer, where)

        print("Running tica-wcs-step1-allcam-allccd...")
        rc = _common.run_command('wcs_step1_allccd', ['--sector', SECTOR, '--dstem', './',
                                                      '--reffin', reffin], cwd=workdir)
        errorflag |= check_step(rc, 'tica-wcs-step1-allcam-allccd', args, mailer, where)
        remove_reference_frames(workdir)

        print("Running tica-calibrate-tso --hlspdir...")
        rc = _common.run_command('calibrate_tso', calibrate + deliver + ['--no_diagnostics'],
                                 cwd=workdir)
        errorflag |= check_step(rc, 'tica-calibrate-tso', args, mailer, where)
    else:
        print("Running tica-calibrate-tso --hlspdir...")
        rc = _common.run_command('calibrate_tso', calibrate + deliver, cwd=workdir)
        errorflag |= check_step(rc, 'tica-calibrate-tso', args, mailer, where)

        print("Running tica-darktime...")
        _common.run_command('darktime', ['--orbit', segment], cwd=workdir)

    tidy_segment(workdir, segment)

    print("Running tica-stage-delivery --ref-stars-only...")
    _common.run_command('stage_delivery', ['v01', delivery, segment, SECTOR, '--ref-stars-only'],
                        cwd=workdir)

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
        table_args = ['--segments', segment] + (['--wcs1'] if seg.first_of_sector else [])
        table = args.production_table or os.path.join(args.workdir, 'production_table.md')
        _common.run_command('production_table', table_args + ['--output', table], cwd=workdir)
    else:
        mailer.send("tica s{} {} proceessing".format(SECTOR, segment), args.mail_error,
                    "TICA s{} {} processing complete, but there were errors. Look in {} "
                    "(This is a first test of automated tica scripts. )".format(SECTOR, segment, delivery))
        with open(args.records, 'a') as f:
            f.write(checkstr + ' error\n')

    if args.records_copy:
        try:
            shutil.copy(args.records, args.records_copy)
        except OSError as e:
            print("could not copy {} to {}: {}".format(args.records, args.records_copy, e))
    return 0



def main(argv=None):
    args = build_parser().parse_args(argv)
    if os.path.isdir(args.records):
        print("Configuration Error. --records {} is a directory; give the records file, e.g. "
              "{}".format(args.records, os.path.join(args.records, 'tica-processing-records.txt')))
        return 2
    if not args.caldir:
        print("Configuration Error. No calibration directory: TICA is not running from a "
              "checkout, so set --caldir or TICA_CALDIR.")
        return 2
    try:
        return run(args, Mailer(enabled=not args.no_mail))
    except Abort as e:
        return e.code


if __name__ == "__main__":
    sys.exit(main())
