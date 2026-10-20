"""Tests for tica-healthcheck."""

import os
from pathlib import Path

import pytest

from tica.cli import healthcheck


def models(path, name, skip=()):
    path.mkdir(parents=True)
    for cam in range(1, 5):
        for ccd in range(1, 5):
            if (cam, ccd) not in skip:
                (path / name.format(cam, ccd)).touch()


def make_checkout(root):
    """A TICA checkout: calibration_<cadence> links into DVC-tracked calibration_models/."""
    root = Path(root)
    (root / ".dvc").mkdir(parents=True)
    cm = root / "calibration_models"
    models(cm / "flat_combine" / "780nm", "cam{}_ccd{}_image.fits")
    models(cm / "twodbias_200s", "cam{}_ccd{}_twoDcorrect.fits")
    models(cm / "twodbias_10min", "cam{}_ccd{}_twoDcorrect.fits", skip={(2, 3), (4, 4)})
    for dvc in ("flat_combine/780nm", "twodbias_200s", "twodbias_10min", "twodbias_20s"):
        (cm / (dvc + ".dvc")).write_text("outs: []\n")
    for name, bias in (("calibration_200sec", "twodbias_200s/"), ("calibration_10min", "twodbias_10min"),
                       ("calibration_20sec", "twodbias_20s/"), ("calibration_04min", "twodbias_200s")):
        (root / name).mkdir()
        os.symlink("../calibration_models/" + bias, root / name / "twodbias")
        os.symlink("../calibration_models/flat_combine/780nm/", root / name / "flatfields")
    return root


def test_reports_each_calibration_dir(tmp_path, monkeypatch, capsys):
    make_checkout(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert healthcheck.main([]) == 1

    out = capsys.readouterr().out
    assert "calibration_200sec (200 s): OK, all 32 models present" in out
    assert "twodbias: 2 of 16 models missing (cam2_ccd3_twoDcorrect.fits, cam4_ccd4_twoDcorrect.fits)" in out
    assert "fetch them with: dvc pull calibration_models/twodbias_10min.dvc" in out
    assert "twodbias: link to calibration_models/twodbias_20s, which does not exist" in out
    assert "fetch it with: dvc pull calibration_models/twodbias_20s.dvc" in out
    assert "calibration_04min:\n  name does not end in a recognised cadence" in out
    assert "calibration_models:" not in out          # not a calibration directory itself


def test_single_directory_and_cadence_filter(tmp_path, monkeypatch, capsys):
    make_checkout(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert healthcheck.main(["calibration_200sec"]) == 0
    assert healthcheck.main(["--cadence", "200sec"]) == 0
    assert healthcheck.main(["--cadence", "20sec"]) == 1
    assert healthcheck.main(["--cadence", "30min"]) == 2
    out = capsys.readouterr().out
    assert out.count("calibration_200sec (200 s): OK") == 2
    assert "No calibration directories for 30min found" in out


def test_dvc_hint_from_outside_the_checkout(tmp_path, monkeypatch, capsys):
    root = make_checkout(tmp_path / "tica")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")

    assert healthcheck.main([str(root), "--cadence", "20sec"]) == 1
    assert "cd {} && dvc pull calibration_models/twodbias_20s.dvc".format(root) in capsys.readouterr().out


def test_plain_directories_without_dvc(tmp_path, capsys):
    caldir = tmp_path / "calibration_200sec"
    models(caldir / "twodbias", "cam{}_ccd{}_twoDcorrect.fits")
    (caldir / "flatfields").touch()                  # a file, not a directory

    assert healthcheck.main([str(caldir)]) == 1
    out = capsys.readouterr().out
    assert "flatfields: missing" in out
    assert "dvc pull" not in out


@pytest.mark.parametrize("path", ["missing", "empty"])
def test_no_calibration_dirs_exits_2(tmp_path, capsys, path):
    (tmp_path / "empty").mkdir()
    assert healthcheck.main([str(tmp_path / path)]) == 2
    assert "contains twodbias/ and flatfields/" in capsys.readouterr().out
