import argparse
import os
import sys

from tica.tica import (CALIBRATION_INT_TIMES, CALIBRATION_MODEL_FILES, calibration_int_time,
                       calibration_model_paths)

DESCRIPTION = """\
Report which calibration models are missing.

TICA expects each calibration directory to be named calibration_<cadence>
(e.g. calibration_200sec) and to contain twodbias/cam<i>_ccd<j>_twoDcorrect.fits
and flatfields/cam<i>_ccd<j>_image.fits for all 16 CCDs. In the repository,
twodbias and flatfields are links into calibration_models/, whose contents are
fetched with DVC.

PATH can be one calibration directory, or a directory containing several (such
as a TICA checkout), in which case each is checked. For link targets that have
not been fetched, the matching `dvc pull` command is shown.

Exit codes: 0 all models present; 1 models missing or a directory name without a
recognised cadence; 2 no calibration directories found."""

CADENCES = [suffix for suffix, _ in CALIBRATION_INT_TIMES]
SHOW_MISSING = 4


def is_calibration_dir(path):
    """True if path holds (or links to) twodbias or flatfields."""
    return os.path.isdir(path) and any(os.path.lexists(os.path.join(path, sub))
                                       for sub, _ in CALIBRATION_MODEL_FILES)


def find_calibration_dirs(path):
    if is_calibration_dir(path):
        return [path]
    if not os.path.isdir(path):
        return []
    return [os.path.join(path, name) for name in sorted(os.listdir(path))
            if is_calibration_dir(os.path.join(path, name))]


def dvc_file_for(path):
    """The .dvc file that tracks path or one of its parents, if any."""
    candidate = os.path.normpath(os.path.abspath(path))
    while True:
        if os.path.isfile(candidate + '.dvc'):
            return candidate + '.dvc'
        parent = os.path.dirname(candidate)
        if parent == candidate:
            return None
        candidate = parent


def _display(path):
    rel = os.path.relpath(path)
    return path if rel.startswith('..') else rel


def dvc_pull_command(dvc_file):
    """`dvc pull <file>`, prefixed with a cd into the repository if we are outside it."""
    root = os.path.dirname(dvc_file)
    while not os.path.isdir(os.path.join(root, '.dvc')) and os.path.dirname(root) != root:
        root = os.path.dirname(root)
    if not os.path.isdir(os.path.join(root, '.dvc')) or not os.path.relpath(root).startswith('..'):
        return "dvc pull {}".format(_display(dvc_file))
    return "cd {} && dvc pull {}".format(root, os.path.relpath(dvc_file, root))


def check_subdir(caldir, subdir):
    """Problems with caldir/subdir, as a list of report lines (empty if complete)."""
    entry = os.path.join(caldir, subdir)
    if os.path.islink(entry) and not os.path.exists(entry):
        target = os.path.join(caldir, os.readlink(entry))
        lines = ["{}: link to {}, which does not exist".format(subdir, _display(os.path.normpath(target)))]
        dvc = dvc_file_for(target)
        if dvc:
            lines.append("    fetch it with: {}".format(dvc_pull_command(dvc)))
        return lines
    if not os.path.isdir(entry):
        return ["{}: missing".format(subdir)]

    missing = [p for p in calibration_model_paths(caldir, subdir) if not os.path.exists(p)]
    if not missing:
        return []
    names = [os.path.basename(p) for p in missing]
    shown = ', '.join(names[:SHOW_MISSING]) + (', ...' if len(names) > SHOW_MISSING else '')
    lines = ["{}: {} of 16 models missing ({})".format(subdir, len(missing), shown)]
    dvc = dvc_file_for(os.path.realpath(entry))
    if dvc:
        lines.append("    fetch them with: {}".format(dvc_pull_command(dvc)))
    return lines


def check_caldir(caldir):
    """Return (healthy, report lines) for one calibration directory."""
    int_time = calibration_int_time(caldir)
    problems = []
    if int_time is None:
        problems.append("name does not end in a recognised cadence ({}), so TICA "
                        "cannot use it".format(', '.join(CADENCES)))
    for subdir, _ in CALIBRATION_MODEL_FILES:
        problems += check_subdir(caldir, subdir)

    label = "{} ({} s)".format(_display(caldir), int_time) if int_time else _display(caldir)
    if not problems:
        return True, ["{}: OK, all 32 models present".format(label)]
    return False, ["{}:".format(label)] + ["  " + line for line in problems]


def build_parser():
    parser = argparse.ArgumentParser(prog='tica-healthcheck', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", default=".", metavar="PATH",
                        help="a calibration directory, or a directory containing several "
                        "(default: current directory)")
    parser.add_argument("--cadence", choices=CADENCES,
                        help="only check calibration directories for this cadence")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    caldirs = find_calibration_dirs(args.path)
    if args.cadence:
        caldirs = [d for d in caldirs
                   if calibration_int_time(d) == dict(CALIBRATION_INT_TIMES)[args.cadence]]
    if not caldirs:
        print("No calibration directories{} found in {}. A calibration directory is named "
              "calibration_<cadence> and contains twodbias/ and flatfields/ (see --help).".format(
                  " for " + args.cadence if args.cadence else "", args.path))
        return 2

    healthy = True
    for caldir in caldirs:
        ok, lines = check_caldir(caldir)
        healthy &= ok
        print("\n".join(lines))
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
