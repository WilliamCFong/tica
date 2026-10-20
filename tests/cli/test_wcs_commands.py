"""Tests for the WCS commands in tica.cli."""

import shutil
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from tica.cli import cal_ccd2ccd, wcs_step2

REPO = Path(__file__).resolve().parents[2]
REG = REPO / "reg_test"
CALDIR_10MIN = REPO / "calibration_10min"

needs_reg_data = pytest.mark.skipif(
    not ((REG / "ref_stars").is_dir()
         and (CALDIR_10MIN / "twodbias" / "cam1_ccd1_twoDcorrect.fits").exists()),
    reason="regression data and 10-minute calibration models not pulled with DVC",
)

# header keywords that legitimately differ between runs
IGNORED_KEYS = ("COMMENT", "CHECKSUM", "DATASUM", "TICAVER")


def test_rotate_log_keeps_previous_runs(tmp_path):
    log = tmp_path / "step2.log"
    log.write_text("first")
    wcs_step2.rotate_log(str(log))
    log.write_text("second")
    wcs_step2.rotate_log(str(log))

    assert not log.exists()
    assert (tmp_path / "step2.log_run1").read_text() == "first"
    assert (tmp_path / "step2.log_run2").read_text() == "second"


@needs_reg_data
def test_wcs_step2_matches_regression_output(tmp_path):
    name = "tess2021041025908-s0035-2-3-0205-s_ffir"
    inlist = tmp_path / "inlist"
    inlist.write_text(str(REG / "input" / (name + ".fits.gz")) + "\n")
    assert cal_ccd2ccd.main([str(inlist), "--outdir", str(tmp_path),
                             "--caldir", str(CALDIR_10MIN)]) == 0

    calfile = tmp_path / (name + ".cal.fits.gz")
    refdata = tmp_path / "ref.h5"
    shutil.copy(REG / "ref_stars" / "hlsp_tica_tess_ffi_s0035-cam2-ccd3_tess_v02_cat.h5", refdata)
    rc = wcs_step2.main(["-s", "35", "-ca", "2", "-cd", "3", "-rd", str(refdata),
                         "-if", str(calfile), "-fd", "6", "-l", str(tmp_path / "step2.log")])
    assert rc == 0

    with fits.open(calfile) as test_f, fits.open(REG / "output_checks" / calfile.name) as gold_f:
        np.testing.assert_array_equal(test_f[0].data, gold_f[0].data)
        for col in ("TIC", "FLXCOL", "FLXROW", "FLXVALID", "FLX", "BKG"):
            np.testing.assert_array_equal(test_f[1].data[col], gold_f[1].data[col])
        for key in gold_f[0].header:
            if key in IGNORED_KEYS:
                continue
            gold, test = gold_f[0].header[key], test_f[0].header[key]
            if isinstance(gold, float):
                assert test == pytest.approx(gold, rel=1e-8, abs=0), key
            else:
                assert test == gold, key
