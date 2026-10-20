"""tica-cal-ffi2hlsp must deliver the same files as the multi-step path it replaces."""

import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest
from astropy.io import fits

from tica.cli import cal_ffi2ccds, cal_ffi2hlsp, production_table, wcs_step2

REPO = Path(__file__).resolve().parents[2]
CALDIR_10MIN = REPO / "calibration_10min"
REF_STARS = REPO / "reg_test" / "ref_stars" / "hlsp_tica_tess_ffi_s0035-cam2-ccd3_tess_v02_cat.h5"

pytestmark = pytest.mark.skipif(
    not (REF_STARS.exists() and (CALDIR_10MIN / "twodbias" / "cam1_ccd1_twoDcorrect.fits").exists()),
    reason="regression data and 10-minute calibration models not pulled with DVC",
)

# header keywords that legitimately differ between runs
IGNORED_KEYS = ("COMMENT", "CHECKSUM", "DATASUM")
FINS = (100001, 100002)


def write_camera_ffi(path, fin, starttjd):
    """A camera 2 FFI in POC format with the S35 cam2/ccd3 reference stars on CCD 3."""
    rng = np.random.default_rng(fin)
    data = rng.normal(6000, 30, (4156, 4272)).astype(np.float32)
    with h5py.File(REF_STARS, "r") as ref:
        cols, rows, tmags = ref["obscols"][:], ref["obsrows"][:], ref["tmags"][:]
    yy, xx = np.mgrid[-5:6, -5:6]
    for col, row, tmag in zip(cols, rows, tmags):
        # CCD 3 is the bottom left of the camera image, unflipped; positions are 1-based
        c, r = int(round(col)) - 1, int(round(row)) - 1
        dc, dr = col - 1 - c, row - 1 - r
        data[r - 5:r + 6, c - 5:c + 6] += (2e5 * 10 ** (-0.4 * (tmag - 7.5))
                                           * np.exp(-((xx - dc) ** 2 + (yy - dr) ** 2) / 1.5))
    endtjd = starttjd + 600 / 86400
    hdr = fits.Header({"CAM": 2, "INT_TIME": 600, "STARTTJD": starttjd, "ENDTJD": endtjd,
                       "MIDTJD": (starttjd + endtjd) / 2, "TJD_ZERO": 2457000.0})
    name = path / "tess2025001000000-{:08d}-2-crm-ffi.fits".format(fin)
    fits.writeto(name, data, hdr)
    return name


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    raw = [write_camera_ffi(root, fin, 2260.0 + k / 144) for k, fin in enumerate(FINS)]
    inlist = root / "inlist"
    inlist.write_text("".join(str(f) + "\n" for f in raw))
    refdir = root / "refout"
    refdir.mkdir()
    for j in range(1, 5):
        shutil.copy(REF_STARS, refdir / "reftica_s35_2-{}.h5".format(j))
    return root, inlist, refdir


def run_old_path(root, inlist, refdir):
    """tica-cal-ffi2ccds, then tica-wcs-step2 in place on each CCD."""
    out = root / "old"
    out.mkdir()
    assert cal_ffi2ccds.main([str(inlist), "--outdir", str(out), "--caldir", str(CALDIR_10MIN),
                              "--orb_seg", "o1a", "--no_gzip", "--log", str(root / "old.log")]) == 0
    for j in range(1, 5):
        files = sorted(str(f) for f in out.glob("*_ccd{}.cal.fits".format(j)))
        assert wcs_step2.main(["-s", "35", "-ca", "2", "-cd", str(j),
                               "-rd", str(refdir / "reftica_s35_2-{}.h5".format(j)),
                               "-if"] + files + ["-fd", "6", "-l", str(root / "old_wcs.log")]) == 0
    return out


def run_new_path(root, inlist, refdir, parallel=1):
    cal, work = root / "cal", root / "work"
    cal.mkdir(exist_ok=True)
    work.mkdir(exist_ok=True)
    return cal_ffi2hlsp.main([str(inlist), "--outdir", str(cal), "--caldir", str(CALDIR_10MIN),
                              "--orb_seg", "o1a", "--hlspdir", str(root / "s0035"), "--sector", "35",
                              "--refdir", str(refdir), "--workdir", str(work),
                              "--parallel", str(parallel), "--log", str(work / "tica_logs" / "o1a_tica.log")])


def hlsp_path(root, fin, j):
    return (root / "s0035" / "cam2-ccd{}".format(j)
            / "hlsp_tica_tess_ffi_s0035-o1-{:08d}-cam2-ccd{}_tess_v01_img.fits".format(fin, j))


def test_matches_calibrate_then_wcs_step2(site):
    root, inlist, refdir = site
    old = run_old_path(root, inlist, refdir)
    assert run_new_path(root, inlist, refdir, parallel=2) == 0

    for fin in FINS:
        for j in range(1, 5):
            old_file = old / "tess2025001000000-{:08d}-2-crm-ffi_ccd{}.cal.fits".format(fin, j)
            with fits.open(old_file) as gold_f, fits.open(hlsp_path(root, fin, j), checksum=True) as test_f:
                assert len(test_f) == 2
                np.testing.assert_array_equal(test_f[0].data, gold_f[0].data)
                assert test_f[1].columns.names == gold_f[1].columns.names
                for col in gold_f[1].columns.names:
                    np.testing.assert_array_equal(test_f[1].data[col], gold_f[1].data[col])
                gold_keys = [k for k in gold_f[0].header if k not in IGNORED_KEYS]
                assert [k for k in test_f[0].header if k not in IGNORED_KEYS] == gold_keys
                for key in gold_keys:
                    assert test_f[0].header[key] == gold_f[0].header[key], key
                assert test_f[0].header["ORB_SEG"] == "o1a"
    # CCD 3 has the stars, so its fit must be a real one
    assert fits.getheader(hlsp_path(root, FINS[0], 3))["WCSGDF"] > 0.9
    assert list((root / "s0035").rglob("*.part")) == []

    assert ((root / "cal" / "cal_timeseries.txt").read_text()
            == (old / "cal_timeseries.txt").read_text())


def test_logs_and_diagnostics_feed_production_table(site):
    root, _, _ = site
    work = root / "work"
    for j in range(1, 5):
        log = production_table.get_from_logs(str(work / "tica_logs" / "tica_wcs_step2_cam2_ccd{}.log".format(j)))
        idx = 4 + j - 1
        assert log["wcs_sector"][idx] == "35"
        assert log["parallel"][idx] == "2"
        assert float(log["runtime"][idx]) > 0
        assert log["flexible_apertures"][idx] == "fixed"
        frac95, _, _, _ = production_table.calculate_step2_metrics(
            str(work / "cam2_ccd{}".format(j) / "wcs_diags2" / "wcs_diag_S35_2{}_data.h5".format(j)))
        assert frac95 is not None
    cal_log = (work / "tica_logs" / "o1a_tica.log").read_text()
    assert "N Pools = 2" in cal_log


def test_rerun_keeps_delivered_files(site):
    root, inlist, refdir = site
    before = {p: p.stat().st_mtime_ns for p in (root / "s0035").rglob("*.fits")}
    assert len(before) == 8
    (root / "cal" / "cal_timeseries.txt").unlink()

    assert run_new_path(root, inlist, refdir) == 0

    assert {p: p.stat().st_mtime_ns for p in (root / "s0035").rglob("*.fits")} == before
    assert len((root / "cal" / "cal_timeseries.txt").read_text().splitlines()) == 3


def test_missing_reference_stars_exit_2(site, tmp_path, capsys):
    root, inlist, _ = site
    rc = cal_ffi2hlsp.main([str(inlist), "--caldir", str(CALDIR_10MIN), "--orb_seg", "o1a",
                            "--hlspdir", str(tmp_path / "s0035"), "--sector", "35",
                            "--refdir", str(tmp_path), "--workdir", str(tmp_path),
                            "--log", str(tmp_path / "x.log")])
    assert rc == 2
    assert "reftica_s35_2-1.h5" in capsys.readouterr().err
    assert not (tmp_path / "s0035").exists()
