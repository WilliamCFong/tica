"""Tests for working out orbit segments from the POC's FFI files."""

from pathlib import Path

import pytest

from tica.cli import _segments


def touch_ffis(orbit_dir, stamp, fins, cams=(1, 2, 3, 4), sub="ffi_fits"):
    d = Path(orbit_dir) / sub
    d.mkdir(parents=True, exist_ok=True)
    for fin in fins:
        for cam in cams:
            (d / "tess{}-{:08d}-{}-crm-ffi.fits.gz".format(stamp, fin, cam)).touch()


@pytest.fixture
def cadence(monkeypatch):
    """Seconds per cadence, instead of reading INT_TIME from the (empty) files."""
    seconds = {"value": 200.0}
    monkeypatch.setattr(_segments, "cadence_seconds", lambda path: seconds["value"])
    return seconds


def names(segments):
    return [s.name for s in segments]


def test_orbit_labels():
    assert [_segments.orbit_label(o) for o in (227, 228, 203, 204, 207, 208)] == \
        ["o1", "o2", "o3", "o4", "o3", "o4"]


def test_redelivered_first_half_is_merged_and_latest_copy_wins(tmp_path, cadence):
    # orbit 227: the first half was delivered twice, then the second half
    orbit = tmp_path / "orbit-227"
    touch_ffis(orbit, "2026257171426", range(1323443, 1323453))
    touch_ffis(orbit, "2026258102559", range(1323443, 1323453))
    touch_ffis(orbit, "2026264010337", range(1325895, 1325900))
    (orbit / "ffi_fits" / "notes.txt").touch()

    a, b = _segments.find_segments(tmp_path, 227)

    assert (a.name, b.name) == ("o1a", "o1b")
    assert a.stamps == ("2026257171426", "2026258102559")
    assert a.counts() == [10, 10, 10, 10]
    assert all("tess2026258102559-" in Path(f).name for f in a.files[1])
    assert b.stamps == ("2026264010337",)
    assert b.files[3][0].endswith("tess2026264010337-01325895-3-crm-ffi.fits.gz")
    assert [s.orb_seg_keyword for s in (a, b)] == ["o1a", "o1b"]
    assert a.first_of_sector and not b.first_of_sector


def test_partial_redelivery_fills_in_from_both_copies(tmp_path, cadence):
    orbit = tmp_path / "orbit-228"
    touch_ffis(orbit, "2026270000000", range(100, 110))
    touch_ffis(orbit, "2026271000000", range(105, 112))   # overlaps and extends

    [a] = _segments.find_segments(tmp_path, 228)

    assert a.name == "o2a" and a.counts() == [12, 12, 12, 12]
    stamps = [Path(f).name[4:17] for f in a.files[1]]
    assert stamps == ["2026270000000"] * 5 + ["2026271000000"] * 7


def test_single_downlink_first_half_or_whole_orbit(tmp_path, cadence):
    # 3000 cadences of 200 s is ~6.9 days: the first half of a split orbit
    touch_ffis(tmp_path / "orbit-229", "2026280000000", (5000, 7999), cams=(1,))
    assert names(_segments.find_segments(tmp_path, 229)) == ["o1a"]

    # ~1827 cadences of 600 s is ~12.7 days: an older orbit downlinked whole
    cadence["value"] = 600.0
    old = tmp_path / "orbit-100"
    touch_ffis(old, "2022005113210", (192752, 194578))
    touch_ffis(old, "2022004000000", (192700,), sub="ffi_fits-haho")
    [whole] = _segments.find_segments(tmp_path, 100)
    assert whole.name == "o2" and whole.whole_orbit
    assert whole.orb_seg_keyword == ""
    assert whole.counts() == [3, 3, 3, 3]          # includes ffi_fits-haho
    assert whole.stamps == ("2022004000000", "2022005113210")
    assert not whole.first_of_sector
    assert _segments.find_segment(tmp_path, 100, "o2a") is None


def test_more_than_two_downlinks_is_off_nominal(tmp_path, cadence):
    orbit = tmp_path / "orbit-231"
    for k, stamp in enumerate(("2026300000000", "2026301000000", "2026302000000")):
        touch_ffis(orbit, stamp, range(1000 * k, 1000 * k + 5))
    with pytest.raises(_segments.OffNominal, match="3 separate downlinks"):
        _segments.find_segments(tmp_path, 231)


def test_no_ffis(tmp_path, cadence):
    (tmp_path / "orbit-232" / "ffi_fits").mkdir(parents=True)
    assert _segments.find_segments(tmp_path, 232) == []
    assert _segments.find_segments(tmp_path, 233) == []
