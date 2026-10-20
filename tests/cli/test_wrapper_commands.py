"""Tests for the commands that orchestrate other tica commands."""

import os
from pathlib import Path

import pytest

from tica.cli import (_common, calibrate_spoc, calibrate_tso, stage_delivery, wcs_spoc,
                      wcs_step1_allccd, wcs_step2_allccd)


class Recorder:
    """Stands in for _common.run_command/run_parallel and records each call."""

    def __init__(self, fail=lambda module, args, cwd: False):
        self.calls = []
        self.fail = fail

    def run_command(self, module, args, cwd=None):
        args = [str(a) for a in args]
        cwd = cwd or os.getcwd()
        self.calls.append((module, args, cwd))
        if module == "cal_ffi2ccds":
            # write the four CCD files tica-cal-ffi2ccds would
            for f in Path(cwd, "inlist").read_text().split():
                stem = os.path.basename(f).replace(".fits", "")
                for j in range(1, 5):
                    Path(cwd, "{}_ccd{}.cal.fits".format(stem, j)).write_text(f)
        return 1 if self.fail(module, args, cwd) else 0

    def run_parallel(self, jobs, cwd=None):
        return [self.run_command(module, args, cwd) for module, args in jobs]


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(_common, "run_command", rec.run_command)
    monkeypatch.setattr(_common, "run_parallel", rec.run_parallel)
    return rec


def make_poc(root, orbit=205, stamps=("2025001000000", "2025002000000")):
    d = Path(root) / "poc" / "orbit-{}".format(orbit) / "ffi_fits"
    d.mkdir(parents=True)
    for s, stamp in enumerate(stamps):
        for fin in range(2):
            for cam in range(1, 5):
                (d / "tess{}-{:08d}-{}-crm-ffi.fits".format(stamp, orbit * 1000 + 10 * s + fin, cam)).touch()
    (Path(root) / "cal_200sec").mkdir()


@pytest.mark.parametrize("orbseg, stamp", [("o1a", "2025001000000"), ("o1b", "2025002000000")])
def test_calibrate_tso_segment(tmp_path, monkeypatch, recorder, orbseg, stamp):
    make_poc(tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = calibrate_tso.main(["--o1", "205", "--o2", "None", "--orbseg", orbseg, "--dstem", "poc",
                             "--caldir", "cal_200sec", "--ncores", "8", "--outdir", "s98"])

    assert rc == 0
    out = tmp_path / "s98"
    assert len(recorder.calls) == 4
    module, args, cwd = recorder.calls[2]
    assert module == "cal_ffi2ccds" and cwd == str(out / "cam3_ccd1")
    assert args == ["inlist", "--outdir", ".", "--caldir", str(tmp_path / "cal_200sec"),
                    "--parallel", "8", "--log", "../tica_logs/{}_tica.log".format(orbseg),
                    "--orb_seg", orbseg, "--no_gzip"]
    inlist = (out / "cam3_ccd1" / "inlist").read_text().split()
    assert len(inlist) == 2 and all("tess" + stamp in f and f.endswith("-3-crm-ffi.fits") for f in inlist)
    # CCDs 2-4 were moved to their own directories
    assert len(list((out / "cam3_ccd4").glob("*_ccd4.cal.fits"))) == 2
    assert not list((out / "cam3_ccd1").glob("*_ccd4.cal.fits"))
    assert (out / "tica_logs").is_dir()


def test_calibrate_tso_reports_failed_camera(tmp_path, monkeypatch):
    rec = Recorder(fail=lambda module, args, cwd: cwd.endswith("cam2_ccd1"))
    monkeypatch.setattr(_common, "run_command", rec.run_command)
    make_poc(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = calibrate_tso.main(["--o1", "205", "--o2", "None", "--orbseg", "o1a", "--dstem", "poc",
                             "--caldir", "cal_200sec"])
    assert rc == 1
    assert len(rec.calls) == 4          # the other cameras still ran


@pytest.mark.parametrize("argv", [
    ["--o1", "205", "--o2", "206", "--orbseg", "o1a"],     # both orbits with a segment
    ["--o1", "205", "--o2", "None", "--orbseg", "o2a"],    # segment from the wrong orbit
    ["--o1", "None", "--o2", "206", "--orbseg", "o1a"],
    ["--o1", "205", "--o2", "None", "--orbseg", "o1c"],    # neither a nor b
])
def test_calibrate_tso_configuration_errors_exit_2(tmp_path, monkeypatch, recorder, argv):
    make_poc(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert calibrate_tso.main(argv + ["--dstem", "poc", "--caldir", "cal_200sec"]) == 2
    assert recorder.calls == []


def test_calibrate_tso_missing_dstem_exits_2(tmp_path, monkeypatch, recorder):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cal").mkdir()
    assert calibrate_tso.main(["--o1", "205", "--o2", "None", "--dstem", "nope", "--caldir", "cal"]) == 2


def test_calibrate_tso_requires_orbits():
    with pytest.raises(SystemExit) as exc:
        calibrate_tso.main(["--dstem", "poc", "--caldir", "cal"])
    assert exc.value.code == 2


def test_calibrate_spoc_lists_ffir_files(tmp_path, monkeypatch, recorder):
    raw = tmp_path / "raw"
    raw.mkdir()
    for cam, ccd in [(1, 1), (4, 3)]:
        (raw / "tess2021041025908-s0035-{}-{}-0205-s_ffir.fits.gz".format(cam, ccd)).touch()
    (raw / "tess2021041025908-s0035-1-1-0205-s_ffic.fits.gz").touch()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    assert calibrate_spoc.main(["--input-dir", "../raw", "--caldir", "../cal", "--ncores", "3"]) == 0

    inlist = (work / "inlist").read_text().split()
    assert [os.path.basename(f) for f in inlist] == [
        "tess2021041025908-s0035-1-1-0205-s_ffir.fits.gz", "tess2021041025908-s0035-4-3-0205-s_ffir.fits.gz"]
    assert recorder.calls == [("cal_ccd2ccd", ["inlist", "--outdir", ".", "--caldir", "../cal",
                                               "--log", "../tica.log", "--parallel", "3"], str(work))]


def make_sector(root, segment="o1a"):
    s = Path(root) / "sector98"
    for cam in range(1, 5):
        for ccd in range(1, 5):
            d = s / "cam{}_ccd{}".format(cam, ccd)
            (d / segment).mkdir(parents=True)
            for fin in (100724, 100725):
                name = "tess2025001000000-{:08d}-{}-crm-ffi_ccd{}.cal.fits".format(fin, cam, ccd)
                (d / name).write_text(name)
                (d / segment / name).write_text(name)
    (s / "refout").mkdir()
    for cam in range(1, 5):
        for ccd in range(1, 5):
            (s / "refout" / "reftica_s98_{}-{}.h5".format(cam, ccd)).write_text("ref{}{}".format(cam, ccd))
    return s


def test_wcs_step1_allccd_skips_existing_and_reports_failures(tmp_path, monkeypatch):
    s = make_sector(tmp_path)
    os.remove(s / "refout" / "reftica_s98_2-2.h5")
    os.remove(s / "refout" / "reftica_s98_3-1.h5")
    rec = Recorder(fail=lambda module, args, cwd: args[3:6] == ["3", "-cd", "1"])
    monkeypatch.setattr(_common, "run_parallel", rec.run_parallel)
    monkeypatch.chdir(s)

    assert wcs_step1_allccd.main(["--sector", "98", "--dstem", "./", "--reffin", "00100724"]) == 1

    assert [(c[1][3], c[1][5]) for c in rec.calls] == [("2", "2"), ("3", "1")]
    assert rec.calls[0][1] == ["-s", "98", "-ca", "2", "-cd", "2",
                               "-ri", "./cam2_ccd2/tess2025001000000-00100724-2-crm-ffi_ccd2.cal.fits",
                               "-o", "./refout/reftica_s98_2-2.h5", "-dbg", "2",
                               "-l", "tica_logs/tica_wcs_step1_cam2_ccd2.log"]


def test_wcs_step2_allccd_runs_all_ccds(tmp_path, monkeypatch, recorder):
    s = make_sector(tmp_path)
    monkeypatch.chdir(s)

    assert wcs_step2_allccd.main(["--sector", "98", "--dstem", ".", "--ncores", "10"]) == 0

    assert len(recorder.calls) == 16
    module, args, _ = recorder.calls[5]
    assert module == "wcs_step2"
    assert args[:9] == ["-s", "98", "-ca", "2", "-cd", "2", "-rd", "./refout/reftica_s98_2-2.h5", "-if"]
    assert args[9:11] == ["./cam2_ccd2/tess2025001000000-00100724-2-crm-ffi_ccd2.cal.fits",
                          "./cam2_ccd2/tess2025001000000-00100725-2-crm-ffi_ccd2.cal.fits"]
    assert args[11:] == ["-fd", "6", "-dbg", "0", "--log", "tica_logs/tica_wcs_step2_cam2_ccd2.log",
                         "--savediaginfo", "--parallel", "10"]


def test_wcs_step2_allccd_exit_1_on_failure(tmp_path, monkeypatch):
    s = make_sector(tmp_path)
    rec = Recorder(fail=lambda module, args, cwd: args[3] == "4" and args[5] == "2")
    monkeypatch.setattr(_common, "run_parallel", rec.run_parallel)
    monkeypatch.chdir(s)
    assert wcs_step2_allccd.main(["--sector", "98", "--dstem", "."]) == 1
    assert len(rec.calls) == 16


def test_wcs_spoc_runs_each_ccd(tmp_path, monkeypatch, recorder):
    (tmp_path / "ref_stars").mkdir()
    for cam in range(1, 5):
        for ccd in range(1, 5):
            (tmp_path / "tess2021041025908-s0035-{}-{}-0205-s_ffir.cal.fits.gz".format(cam, ccd)).touch()
            (tmp_path / "ref_stars" / "hlsp_tica_tess_ffi_s0035-cam{}-ccd{}_tess_v02_cat.h5".format(cam, ccd)).touch()
    monkeypatch.chdir(tmp_path)

    assert wcs_spoc.main(["--sector", "35", "--dstem", "."]) == 0

    assert len(recorder.calls) == 16
    args = recorder.calls[0][1]
    assert args[args.index("-if") + 1] == "./tess2021041025908-s0035-1-1-0205-s_ffir.cal.fits.gz"
    assert args[args.index("-rd") + 1].endswith("ref_stars/hlsp_tica_tess_ffi_s0035-cam1-ccd1_tess_v02_cat.h5")


def test_stage_delivery_names(tmp_path, monkeypatch):
    s = make_sector(tmp_path, segment="o2b")
    monkeypatch.chdir(s)
    out = tmp_path / "delivery" / "s0098"

    assert stage_delivery.main(["v02", str(out), "o2b", "98"]) == 0

    staged = sorted(p.name for p in (out / "cam3-ccd2").iterdir())
    assert staged == ["hlsp_tica_tess_ffi_s0098-o2-00100724-cam3-ccd2_tess_v02_img.fits",
                      "hlsp_tica_tess_ffi_s0098-o2-00100725-cam3-ccd2_tess_v02_img.fits"]
    assert (out / "cam3-ccd2" / staged[0]).read_text() == "tess2025001000000-00100724-3-crm-ffi_ccd2.cal.fits"
    ref = out / "ref-stars" / "hlsp_tica_tess_ffi_s0098-cam4-ccd1_tess_v02_cat.h5"
    assert ref.read_text() == "ref41"
    assert len(list((out / "ref-stars").iterdir())) == 16


@pytest.mark.parametrize("segment, orbit", [("o1a", "o1"), ("o2b", "o2"), ("o3", "o3"), ("x", "")])
def test_stage_delivery_orbit_label(segment, orbit):
    assert stage_delivery.orbit_label(segment) == orbit
