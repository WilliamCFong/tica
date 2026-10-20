"""Tests for the calibration commands in tica.cli."""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from tica.cli import _common, cal_ccd2ccd, ccds2ffi

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


def test_load_calibration_requires_caldir():
    with pytest.raises(SystemExit) as exc:
        _common.load_calibration(None)
    assert exc.value.code == 1


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
