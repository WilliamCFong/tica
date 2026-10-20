"""Tests for the calibration commands in tica.cli."""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from tica.cli import _common, cal_ccd2ccd, cal_ffi2ccds, ccds2ffi

REPO = Path(__file__).resolve().parents[2]
REG_INPUT = REPO / "reg_test" / "input"
REG_CHECKS = REPO / "reg_test" / "output_checks"
CALDIR_10MIN = REPO / "calibration_10min"

needs_reg_data = pytest.mark.skipif(
    not (REG_INPUT.is_dir() and (CALDIR_10MIN / "twodbias" / "cam1_ccd1_twoDcorrect.fits").exists()),
    reason="regression data and 10-minute calibration models not pulled with DVC",
)


def test_read_file_list_single_line(tmp_path):
    inlist = tmp_path / "inlist"
    inlist.write_text("only.fits\n")
    assert _common.read_file_list(inlist) == ["only.fits"]


def test_read_file_list_missing_exits_1(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _common.read_file_list(tmp_path / "missing")
    assert exc.value.code == 1


@pytest.mark.parametrize("caldir", [None, "/no/such/calibration_10min"])
def test_load_calibration_exits_2_for_unusable_caldir(caldir):
    with pytest.raises(SystemExit) as exc:
        _common.load_calibration(caldir)
    assert exc.value.code == 2


def test_cal_ffi2ccds_exits_2_for_unnamed_caldir(tmp_path, capsys):
    caldir = tmp_path / "tica-calibration-models"
    caldir.mkdir()
    inlist = tmp_path / "inlist"
    inlist.write_text("x.fits\n")
    with pytest.raises(SystemExit) as exc:
        cal_ffi2ccds.main([str(inlist), "--caldir", str(caldir), "--log", str(tmp_path / "log")])
    assert exc.value.code == 2
    assert "must end in _<cadence>" in capsys.readouterr().err


def _fail_on_two(item):
    if item == 2:
        raise ValueError("bad item")
    return item * 10


def test_map_files_surfaces_worker_errors():
    assert _common.map_files(_fail_on_two, [1, 3], processes=2) == [10, 30]
    with pytest.raises(ValueError):
        _common.map_files(_fail_on_two, [1, 2, 3], processes=2)


@needs_reg_data
@pytest.mark.parametrize("parallel", ["1", "2"])
def test_cal_ccd2ccd_matches_regression_images(tmp_path, parallel):
    names = ["tess2021041025908-s0035-1-1-0205-s_ffir", "tess2021041025908-s0035-3-2-0205-s_ffir"]
    inlist = tmp_path / "inlist"
    inlist.write_text("".join(str(REG_INPUT / (n + ".fits.gz")) + "\n" for n in names))

    rc = cal_ccd2ccd.main([str(inlist), "--outdir", str(tmp_path),
                           "--caldir", str(CALDIR_10MIN), "--parallel", parallel])

    assert rc == 0
    for n in names:
        out = fits.getdata(tmp_path / (n + ".cal.fits.gz"))
        gold = fits.getdata(REG_CHECKS / (n + ".cal.fits.gz"))
        np.testing.assert_array_equal(out, gold)


def test_ccds2ffi_places_ccds_in_camera_frame(tmp_path):
    rng = np.random.default_rng(0)
    images = [rng.random((2078, 2136)).astype(np.float32) for _ in range(4)]
    files = []
    for k, image in enumerate(images):
        files.append(str(tmp_path / f"ccd{k + 1}.fits"))
        fits.writeto(files[-1], image)

    assert ccds2ffi.main(files + ["--outdir", str(tmp_path), "--outfile", "ffi.fits"]) == 0

    frame = fits.getdata(tmp_path / "ffi.fits")
    assert frame.shape == (4156, 4272)
    np.testing.assert_array_equal(frame[:2078, :2136], images[2])
    np.testing.assert_array_equal(frame[:2078, 2136:], images[3])
    np.testing.assert_array_equal(frame[2078:, :2136], images[1][::-1, ::-1])
    np.testing.assert_array_equal(frame[2078:, 2136:], images[0][::-1, ::-1])


def test_trim_ccds2ffi_restores_border(tmp_path):
    rng = np.random.default_rng(1)
    images = [rng.random((2048, 2048)).astype(np.float32) for _ in range(4)]
    files = []
    for k, image in enumerate(images):
        files.append(str(tmp_path / f"trim{k + 1}.fits"))
        fits.writeto(files[-1], image)

    assert ccds2ffi.main_trim(files + ["--outdir", str(tmp_path), "--outfile", "ffi.fits"]) == 0

    frame = fits.getdata(tmp_path / "ffi.fits")
    assert frame.shape == (4156, 4272)
    np.testing.assert_array_equal(frame[:2048, 44:2092], images[2])
    assert not frame[:2048, :44].any()


def write_synthetic_camera_ffi(path, fin, cam=1, starttjd=1234.5):
    """A full-camera FFI in POC format: 4 CCDs with overclock/underclock pixels."""
    rng = np.random.default_rng(fin)
    data = rng.normal(6000, 30, (4156, 4272)).astype(np.float32)
    hdr = fits.Header({"CAM": cam, "INT_TIME": 600, "STARTTJD": starttjd})
    name = path / "tess2025001000000-{:08d}-{}-crm-ffi.fits".format(fin, cam)
    fits.writeto(name, data, hdr)
    return name


needs_10min_models = pytest.mark.skipif(
    not (CALDIR_10MIN / "twodbias" / "cam1_ccd1_twoDcorrect.fits").exists(),
    reason="10-minute calibration models not pulled with DVC",
)


@needs_10min_models
def test_cal_ffi2ccds_splits_and_records_diagnostics(tmp_path):
    raw = [write_synthetic_camera_ffi(tmp_path, fin) for fin in (100002, 100001)]
    inlist = tmp_path / "inlist"
    inlist.write_text("".join(str(f) + "\n" for f in raw))
    outdir = tmp_path / "out"
    outdir.mkdir()

    rc = cal_ffi2ccds.main([str(inlist), "--outdir", str(outdir), "--caldir", str(CALDIR_10MIN),
                            "--parallel", "2", "--orb_seg", "o1a", "--no_gzip",
                            "--log", str(tmp_path / "logs" / "o1a_tica.log")])

    assert rc == 0
    outputs = sorted(p.name for p in outdir.glob("*.cal.fits"))
    assert len(outputs) == 8
    hdr = fits.getheader(outdir / "tess2025001000000-00100001-1-crm-ffi_ccd3.cal.fits")
    assert hdr["ORB_SEG"] == "o1a"
    rows = (outdir / "cal_timeseries.txt").read_text().splitlines()
    assert rows[0].split()[:2] == ["name", "mode_ccd1"]
    assert [r.split()[0] for r in rows[1:]] == [f.name for f in sorted(raw)]
    log = (tmp_path / "logs" / "o1a_tica.log").read_text()
    assert log.splitlines()[0].split()[2:4] == ["TICA", "version:"]
    assert "N Pools = 2" in log


def test_run_command_and_run_parallel_return_exit_codes(tmp_path):
    assert _common.run_command("cal_ccd2ccd", ["--help"], cwd=tmp_path) == 0
    assert _common.run_parallel([("cal_ccd2ccd", ["--help"]),
                                 ("cal_ccd2ccd", ["--no-such-option"])]) == [0, 2]
