"""Tests for checking calibration directories and the CCD calibration guard."""

from pathlib import Path

import numpy as np
import pytest

from tica.tica import CCD, Calibration, CalibrationError, check_calibration_dir

REPO = Path(__file__).resolve().parents[1]


def make_caldir(path, skip=()):
    for sub, name in (("twodbias", "cam{}_ccd{}_twoDcorrect.fits"), ("flatfields", "cam{}_ccd{}_image.fits")):
        (path / sub).mkdir(parents=True)
        for cam in range(1, 5):
            for ccd in range(1, 5):
                if (sub, cam, ccd) not in skip:
                    (path / sub / name.format(cam, ccd)).touch()
    return path


@pytest.mark.parametrize("name, int_time", [("calibration_30min", 1800), ("calibration_10min", 600),
                                            ("calibration_02min", 120), ("calibration_20sec", 20),
                                            ("calibration_200sec", 200), ("models_200sec", 200)])
def test_int_time_from_directory_name(tmp_path, name, int_time):
    caldir = make_caldir(tmp_path / name)
    assert check_calibration_dir(str(caldir)) == int_time
    assert check_calibration_dir(str(caldir) + "/") == int_time


@pytest.mark.parametrize("name", ["tica-calibration-models", "calibration_04min", "calibration"])
def test_unrecognised_name_is_an_error(tmp_path, name):
    caldir = make_caldir(tmp_path / name)
    with pytest.raises(CalibrationError, match=r"must end in _<cadence>.*calibration_200sec"):
        check_calibration_dir(str(caldir))


def test_missing_models_are_listed(tmp_path):
    caldir = make_caldir(tmp_path / "calibration_200sec", skip={("flatfields", 3, 2), ("twodbias", 1, 4)})
    with pytest.raises(CalibrationError, match="2 of 32") as exc:
        check_calibration_dir(str(caldir))
    assert "cam1_ccd4_twoDcorrect.fits" in str(exc.value)
    assert "cam3_ccd2_image.fits" in str(exc.value)


@pytest.mark.parametrize("caldir", [None, "", "/no/such/calibration_200sec"])
def test_missing_directory_is_an_error(caldir):
    with pytest.raises(CalibrationError):
        Calibration(caldir)


def test_ccd_without_calibration_can_be_built_but_not_calibrated():
    ccd = CCD(np.zeros((2078, 2136)))
    assert ccd.calibration is None
    ccd.ccdnum, ccd.camnum = 1, 1
    with pytest.raises(CalibrationError, match="without calibration models"):
        ccd.calibrate()


@pytest.mark.skipif(not (REPO / "calibration_10min" / "twodbias" / "cam1_ccd1_twoDcorrect.fits").exists(),
                    reason="10-minute calibration models not pulled with DVC")
def test_repository_calibration_dir_passes():
    assert Calibration(str(REPO / "calibration_10min")).int_time == 600
