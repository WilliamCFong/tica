"""Orbit segments of the POC's raw FFI deliveries.

The POC writes each downlink's FFIs to <dstem>/orbit-<N>/ffi_fits/ as
tess<stamp>-<fin>-<cam>-crm-ffi.fits[.gz], where <stamp> is when the downlink
was processed and <fin> is the cadence number (the CADENCE keyword, one per
FFI). Nothing in the files names the orbit segment, so it is worked out from
the cadences:

- A stamp that mostly repeats the FFIs (cadence and camera) of another is
  the same downlink delivered again. Where several stamps have the same
  cadence and camera, the file with the latest stamp is used. Overlap is
  counted per camera, since each camera's halves can end at a different
  cadence (orbit 227: camera 1 at 1325894, cameras 2-4 at 1325842).
- Two downlinks are the orbit's halves, o<k>a and o<k>b, in cadence order.
  Most orbits since sector 56 are downlinked this way.
- One downlink is either the first half, before the second has arrived, or a
  whole orbit (all orbits before sector 56, and some since). It is the first
  half if its cadences span less than WHOLE_ORBIT_DAYS, and otherwise the
  whole orbit, o<k>. Whole orbits also include ffi_fits-haho/ and are written
  with an empty ORB_SEG keyword, as tica-calibrate-tso always did.
- More than two downlinks are off nominal and raise OffNominal.

<k> is 1 or 2 for odd or even orbits, or 3 or 4 for the extra orbits of
sectors 97 and 98.
"""

import glob
import os
import re
from dataclasses import dataclass

from astropy.io import fits

# a TESS orbit is ~13.7 days; a half is ~7
WHOLE_ORBIT_DAYS = 10.0
# share of FFIs two stamps must have in common to be one downlink delivered twice
REDELIVERY_SHARE = 0.5

FILE_NAME = re.compile(r'tess(\d+)-(\d+)-(\d)-crm-ffi\.fits')


class OffNominal(ValueError):
    """An orbit's FFIs don't fall into one or two downlinks."""


def orbit_label(orbit):
    """o1/o2 for odd/even orbits, with the special o3/o4 orbits of sectors 97-98."""
    orbit = int(orbit)
    special = {203: "o3", 204: "o4", 207: "o3", 208: "o4"}
    if orbit in special:
        return special[orbit]
    return "o1" if orbit % 2 == 1 else "o2"


def parse_name(path):
    """(stamp, fin, camera) from a POC FFI file name, or None for other files."""
    m = FILE_NAME.match(os.path.basename(path))
    if m is None:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3))


def cadence_seconds(path):
    """Seconds per cadence (INT_TIME) of a raw FFI."""
    return float(fits.getheader(path)['INT_TIME'])


@dataclass
class Segment:
    name: str        # o1a, o1b, or o1 for a whole orbit
    files: dict      # camera -> sorted file paths
    stamps: tuple    # the processing stamps it came from, oldest first

    @property
    def whole_orbit(self):
        return not self.name.endswith(('a', 'b'))

    @property
    def orb_seg_keyword(self):
        """The ORB_SEG keyword value: the segment, or '' for a whole orbit."""
        return '' if self.whole_orbit else self.name

    @property
    def first_of_sector(self):
        """o1a or a whole o1: the segment that makes the sector's WCS reference star lists."""
        return self.name in ('o1', 'o1a')

    def counts(self):
        """Number of FFIs for cameras 1-4."""
        return [len(self.files.get(cam, [])) for cam in range(1, 5)]


def downlinks(paths):
    """Group FFI files into downlinks: lists of (stamp, fin, cam, path), in cadence order.

    A stamp is a re-delivery of an earlier downlink when at least
    REDELIVERY_SHARE of its FFIs (cadence and camera) are already in it, or of
    the downlink's FFIs are in the stamp. Overlap is counted per camera: each
    camera's halves can end at a different cadence. A cadence in two separate
    downlinks is kept only in the earlier one.
    """
    by_stamp = {}
    for path in paths:
        parsed = parse_name(path)
        if parsed is not None:
            by_stamp.setdefault(parsed[0], []).append(parsed + (path,))
    groups = []
    for stamp in sorted(by_stamp, key=lambda st: (min(e[1] for e in by_stamp[st]), st)):
        entries = by_stamp[stamp]
        keys = {(e[1], e[2]) for e in entries}
        for group in groups:
            shared = len(keys & group['keys'])
            if shared >= REDELIVERY_SHARE * min(len(keys), len(group['keys'])):
                group['keys'] |= keys
                group['entries'] += entries
                break
        else:
            groups.append({'keys': set(keys), 'entries': list(entries)})
    out, seen = [], set()
    for group in groups:
        out.append([e for e in group['entries'] if (e[1], e[2]) not in seen])
        seen |= group['keys']
    return out


def latest_files(entries):
    """camera -> sorted paths, keeping the latest stamp of each cadence."""
    chosen = {}
    for stamp, fin, cam, path in sorted(entries):
        chosen[(fin, cam)] = path
    files = {}
    for (fin, cam), path in chosen.items():
        files.setdefault(cam, []).append(path)
    return {cam: sorted(paths) for cam, paths in files.items()}


def make_segment(name, entries):
    return Segment(name, latest_files(entries), tuple(sorted({e[0] for e in entries})))


def find_segments(dstem, orbit):
    """The segments of <dstem>/orbit-<orbit>/, in order; [] if it has no FFIs."""
    orbit_dir = os.path.join(dstem, 'orbit-{}'.format(orbit))
    groups = downlinks(sorted(glob.glob(os.path.join(orbit_dir, 'ffi_fits', 'tess*'))))
    label = orbit_label(orbit)
    if len(groups) > 2:
        raise OffNominal("{} has {} separate downlinks in ffi_fits (stamps {}); expected one or "
                         "two. Process it by hand with --segment.".format(
                             orbit_dir, len(groups),
                             ', '.join(sorted({e[0] for g in groups for e in g}))))
    if len(groups) == 2:
        return [make_segment(label + 'a', groups[0]), make_segment(label + 'b', groups[1])]
    if not groups:
        return []

    [group] = groups
    fins = [e[1] for e in group]
    days = (max(fins) - min(fins) + 1) * cadence_seconds(group[0][3]) / 86400.0
    if days < WHOLE_ORBIT_DAYS:
        return [make_segment(label + 'a', group)]
    haho = downlinks(sorted(glob.glob(os.path.join(orbit_dir, 'ffi_fits-haho', 'tess*'))))
    return [make_segment(label, group + [e for g in haho for e in g])]


def find_segment(dstem, orbit, name):
    """The segment called name, or None."""
    return next((s for s in find_segments(dstem, orbit) if s.name == name), None)
