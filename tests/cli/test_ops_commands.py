"""Tests for the production commands in tica.cli: darktime, check-delivery and
production-table."""

import os
from pathlib import Path

import h5py
import numpy as np
import pytest
from astropy.io import fits

from tica.cli import check_delivery, darktime, overclock_stats, production_table

CALDIR_10MIN = Path(__file__).resolve().parents[2] / "calibration_10min"


def _log(path, lines, start="2026.10.20 01:00:00"):
    stamp_date, stamp_time = start.split()
    with open(path, "a") as f:
        for line in lines:
            f.write("{} {} {}\n".format(stamp_date, stamp_time, line))


def _header(prog):
    return ["TICA version: 1.4.0",
            "Python version: 3.12.1 (main, Jan  1 2026, 00:00:00) [Clang]",
            "Host: poc-host",
            "Locale: C",
            "python environment:  None",
            "program: {}".format(prog),
            ]


def make_sector(root, segment="o1a", sector=98):
    """A sector directory as tica-doall-automate leaves it, after WCS steps 1 and 2."""
    sdir = Path(root) / "sector{}".format(sector)
    (sdir / "tica_logs").mkdir(parents=True)
    (sdir / "refout").mkdir()
    for cam in range(1, 5):
        _log(sdir / "tica_logs" / "{}_tica.log".format(segment),
             _header("tica-cal-ffi2ccds")
             + ["working directory {}/cam{}_ccd1".format(sdir, cam),
                "argument parameters:",
                "     parallel = 57",
                "N Pools = 57",
                "Runtime: {}.00sec".format(100 + cam)],
             start="2026.10.20 0{}:00:00".format(cam))
        for ccd in range(1, 5):
            tag = "cam{}_ccd{}".format(cam, ccd)
            _log(sdir / "tica_logs" / "tica_wcs_step1_{}.log".format(tag),
                 _header("tica-wcs-step1")
                 + ["argument parameters:",
                    "     sector = {}".format(sector),
                    "     camera = {}".format(cam),
                    "     ccd = {}".format(ccd),
                    "     refimage = ./{}/tess2025001000000-00100724-{}-crm-ffi_ccd{}.cal.fits".format(tag, cam, ccd),
                    "     wing = 0.9",
                    "     contrast = 3.5",
                    "Found: 512 ref targets, 300 bright, fit resid [arcsec] bright  0.512 faint  1.234 nTrim: 7",
                    "Runtime: 50.00sec"],
                 start="2026.10.20 05:00:00")
            _log(sdir / "tica_logs" / "tica_wcs_step2_{}.log".format(tag),
                 _header("tica-wcs-step2")
                 + ["argument parameters:",
                    "     sector = {}".format(sector),
                    "     camera = {}".format(cam),
                    "     ccd = {}".format(ccd),
                    "     parallel = 10",
                    "Using fixed apertures.",
                    "Runtime: 200.00sec"],
                 start="2026.10.20 06:{:02d}:00".format(4 * (cam - 1) + ccd))

            with h5py.File(sdir / "refout" / "reftica_s{}_{}-{}.h5".format(sector, cam, ccd), "w") as f:
                f["tics"] = np.arange(512)
                f["tmags"] = np.linspace(6.5, 10.25, 512)

            diag = sdir / tag / segment / "wcs_diags2"
            diag.mkdir(parents=True)
            with h5py.File(diag / "wcs_diag_S{}_{}{}_data.h5".format(sector, cam, ccd), "w") as f:
                f["goodStarFracs"] = np.array([0.99, 0.97, 0.9, 0.5])
                f["allStds"] = np.array([2.0, 2.2, 2.4, 9.0])
                f["allPixStds"] = np.array([0.1, 0.11, 0.12, 0.4])
    return sdir


@pytest.mark.parametrize("sector", [98, 108])      # 108: the first 3-digit sector
def test_production_table_appends_one_row_per_ccd(tmp_path, monkeypatch, sector):
    sdir = make_sector(tmp_path, sector=sector)
    table = tmp_path / "production_table.md"
    monkeypatch.chdir(sdir)

    assert production_table.main(["--segments", "o1a", "--wcs1", "--output", str(table)]) == 0
    assert production_table.main(["--segments", "o1a", "--output", str(table)]) == 0

    lines = table.read_text().splitlines()
    assert len(lines) == 2 + 16 + 16          # header, alignment, two runs of 16 CCDs
    first = [c.strip() for c in lines[2].split("|")]
    assert first[1:4] == ["{:04d}".format(sector), "o1a", "2026.10.20-01:00:00"]
    assert first[4] == "2026.10.20-06:16:00"     # latest end time over all logs
    assert "00100724" in lines[2]                 # reference FFI from step 1


def test_darktime_writes_lists_and_reffin(tmp_path, monkeypatch):
    sdir = tmp_path / "sector98"
    rng = np.random.default_rng(7)
    fins = np.arange(100000, 101600)
    t = np.linspace(-1, 1, len(fins))
    for cam in range(1, 5):
        for ccd in range(1, 5):
            (sdir / "cam{}_ccd{}".format(cam, ccd)).mkdir(parents=True)
        cols = (["name"] + ["mode_ccd%d" % j for j in range(1, 5)]
                + ["output%s_ccd%d" % (c, j) for j in range(1, 5) for c in "ABCD"])
        with open(sdir / "cam{}_ccd1".format(cam) / "cal_timeseries.txt", "w") as f:
            f.write("{:>45s} ".format(cols[0]) + "".join("{:>15s}".format(c) for c in cols[1:]) + "\n")
            for k, fin in enumerate(fins):
                modes = [np.round((800 + 4000 * t[k] ** 4 + rng.normal(0, 5)) / 25) * 25 for _ in range(4)]
                bias = rng.normal(5000, 2, 16)
                f.write("{:>45s} ".format("tess2025001000000-%08d-%d-crm-ffi.fits" % (fin, cam))
                        + "".join("{:>15.2f}".format(v) for v in list(modes) + list(bias)) + "\n")
    monkeypatch.chdir(sdir)
    monkeypatch.setenv("MPLBACKEND", "Agg")

    assert darktime.main(["--save_reflist", "--save_reffin", "--use_first_ccd", "--orbit", "o1a"]) == 0

    reffin = (sdir / "reffin.txt").read_text().split()
    assert reffin[0] == "cam1_ccd1" and len(reffin) == 32
    assert len(set(reffin[1::2])) == 1                  # one frame for every CCD
    assert len((sdir / "cam1_ccd1" / "ref_list").read_text().splitlines()) == 20
    assert not (sdir / "cam2_ccd1" / "ref_list").exists()       # --use_first_ccd
    assert (sdir / "cam3_ccd4" / "rms_list").stat().st_size > 0
    assert (sdir / "cam1_ccd1" / "cal_timeseries_o1a.png").exists()


def _series(n=200, seed=3):
    """cal_timeseries data for 4 cameras: backgrounds ~20000-30000, steady overclocks."""
    rng = np.random.default_rng(seed)
    fins = np.arange(1324000, 1324000 + n)
    names = (["mode_ccd%d" % j for j in range(1, 5)]
             + ["output%s_ccd%d" % (c, j) for j in range(1, 5) for c in "ABCD"])
    out = []
    for cam in range(4):
        data = np.zeros(n, dtype=[(name, float) for name in names])
        for j in range(1, 5):
            data["mode_ccd%d" % j] = 20000 + 10000 * np.linspace(0, 1, n) ** 2 + rng.normal(0, 100, n)
            for c in "ABCD":
                data["output%s_ccd%d" % (c, j)] = rng.normal(5000, 2, n)
        out.append([fins, data, np.zeros(n, dtype=int)])
    return out


def test_choose_reffin_skips_stray_light_and_miscalibrated_frames():
    series = _series()
    # like orbit 227 FIN 01324272: camera 1 reads far too low, camera 2 is flooded
    bad = 10
    for j in range(1, 5):
        series[0][1]["mode_ccd%d" % j][bad] = [4165, 4225, 1469, 0][j - 1]
        series[1][1]["mode_ccd%d" % j][bad] = 340866
    fin, why = darktime.choose_reffin(series)
    assert fin != 1324000 + bad
    assert 1324000 <= fin < 1324050                      # early, where every CCD is dark
    assert "worst CCD" in why

    # the darkest clean frame, unless it has a stray-light flag
    best = fin
    for cam in range(4):
        series[cam][2][best - 1324000] = 0b0011
    fin2, _ = darktime.choose_reffin(series)
    assert fin2 != best

    # every frame flagged: the flags are ignored, with a note
    for cam in range(4):
        series[cam][2][:] = 1
    fin3, why3 = darktime.choose_reffin(series)
    assert fin3 == best and "flags were ignored" in why3


def test_choose_reffin_without_a_clean_frame():
    series = _series(n=20)
    for cam in range(4):
        series[cam][1]["mode_ccd2"][:] = 0
    fin, why = darktime.choose_reffin(series)
    assert fin is None and "16 CCDs" in why


def test_darktime_reads_straylight_column(tmp_path, monkeypatch):
    sdir = tmp_path / "sector98"
    series = _series(n=150)
    cols = (["name"] + list(series[0][1].dtype.names) + ["straylight"])
    for cam in range(1, 5):
        for ccd in range(1, 5):
            (sdir / "cam{}_ccd{}".format(cam, ccd)).mkdir(parents=True)
        fins, data, _ = series[cam - 1]
        with open(sdir / "cam{}_ccd1".format(cam) / "cal_timeseries.txt", "w") as f:
            f.write("{:>45s} ".format(cols[0]) + "".join("{:>15s}".format(c) for c in cols[1:]) + "\n")
            for k, fin in enumerate(fins):
                f.write("{:>45s} ".format("tess2025001000000-%08d-%d-crm-ffi.fits" % (fin, cam))
                        + "".join("{:>15.2f}".format(v) for v in data[k])
                        + "{:>15d}".format(3 if k < 60 else 0) + "\n")   # early frames flagged
    monkeypatch.chdir(sdir)
    monkeypatch.setenv("MPLBACKEND", "Agg")

    assert darktime.main(["--save_reffin", "--orbit", "o1a"]) == 0
    lines = (sdir / "reffin.txt").read_text().splitlines()
    assert len(lines) == 16 and len({line.split()[1] for line in lines}) == 1
    assert int(lines[0].split()[1]) >= 1324000 + 60     # not a flagged frame


def _make_delivery(root, n_ffis=2, nan_column=None):
    ddir = Path(root) / "s0098"
    (ddir / "ref-stars").mkdir(parents=True)
    for cam in range(1, 5):
        for ccd in range(1, 5):
            stem = "cam{}-ccd{}".format(cam, ccd)
            (ddir / stem).mkdir()
            with h5py.File(ddir / "ref-stars" / "hlsp_tica_tess_ffi_s0098-{}_tess_v01_cat.h5".format(stem), "w") as f:
                for col in check_delivery.REF_COLUMNS:
                    f[col] = np.full(3, np.nan) if col == nan_column else np.arange(3.0)
            for k in range(n_ffis):
                hdr = fits.Header({"CTYPE1": "RA---TAN-SIP", "CTYPE2": "DEC--TAN-SIP",
                                   "CRPIX1": 1069.0, "CRPIX2": 1024.0, "CRVAL1": 10.0, "CRVAL2": -20.0,
                                   "A_ORDER": 6, "B_ORDER": 6})
                table = fits.BinTableHDU.from_columns(
                    [fits.Column(name=n, format="D", array=np.arange(3.0)) for n in check_delivery.FFI_COLUMNS])
                fits.HDUList([fits.PrimaryHDU(np.zeros((2078, 2136), dtype=np.float32), header=hdr),
                              table]).writeto(ddir / stem / "ffi{}.fits".format(k))
    return ddir


def test_check_delivery_accepts_complete_delivery(tmp_path, capsys):
    ddir = _make_delivery(tmp_path)
    assert check_delivery.main([str(ddir), "--processes", "2"]) == 0
    out = capsys.readouterr().out
    assert "no problems" in out
    assert "has 1 extensions" not in out


def test_check_delivery_rejects_missing_ccd(tmp_path, capsys):
    ddir = _make_delivery(tmp_path, n_ffis=0)
    os.rmdir(ddir / "cam2-ccd3")
    assert check_delivery.main([str(ddir)]) == 1
    assert "cam2-ccd3 not in expected" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["ras"])
def test_check_delivery_rejects_nan_star_list(tmp_path, capsys, bad):
    ddir = _make_delivery(tmp_path, n_ffis=0, nan_column=bad)
    assert check_delivery.main([str(ddir)]) == 1
    assert "NaN value in column {}".format(bad) in capsys.readouterr().out


@pytest.mark.skipif(
    not (CALDIR_10MIN / "twodbias" / "cam1_ccd1_twoDcorrect.fits").exists(),
    reason="10-minute calibration models not pulled with DVC",
)
def test_overclock_stats_writes_16_rows_per_ffi(tmp_path, monkeypatch):
    from astropy.table import Table
    from test_calibration_commands import write_synthetic_camera_ffi

    write_synthetic_camera_ffi(tmp_path, 100001)
    write_synthetic_camera_ffi(tmp_path, 100002, starttjd=1234.6)
    (tmp_path / "notes.txt").write_text("skipped")
    monkeypatch.chdir(tmp_path)

    assert overclock_stats.main([str(CALDIR_10MIN)]) == 0

    table = Table.read(tmp_path / "test_stats.csv")
    assert len(table) == 32
    assert list(table["sector"][:4]) == ["A", "B", "C", "D"]
    assert sorted(set(table["ccd"])) == [1, 2, 3, 4]
    np.testing.assert_allclose(table["correct"], 6000, atol=5)


def test_check_delivery_counts_ffi_problems(tmp_path, capfd):
    ddir = _make_delivery(tmp_path)
    with fits.open(ddir / "cam2-ccd3" / "ffi0.fits", mode="update") as f:
        f[0].header["A_ORDER"] = 0
    assert check_delivery.main([str(ddir)]) == 0
    out = capfd.readouterr().out          # the problem is printed by a pool worker
    assert "A_ORDER is 0" in out
    assert "Checked 32 FFIs in 16 CCD directories and 16 star lists" in out and "1 problems" in out
