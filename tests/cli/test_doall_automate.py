"""Tests for tica-doall-automate, with every step and the mailer stubbed."""

import os
from pathlib import Path

import pytest

from tica.cli import _common, doall_automate


@pytest.mark.parametrize("orbit, sector", [(9, 1), (100, 46), (203, 97), (204, 97), (205, 98),
                                           (208, 98), (209, 99), (220, 104)])
def test_sector_from_orbit(orbit, sector):
    assert doall_automate.sector_from_orbit(orbit) == sector


@pytest.mark.parametrize("orbit, segment", [(205, "o1"), (206, "o2"), (203, "o3"), (204, "o4"),
                                            (207, "o3"), (208, "o4"), (219, "o1")])
def test_segment_from_orbit(orbit, segment):
    assert doall_automate.segment_from_orbit(orbit) == segment


def test_newest_orbit_dir_uses_mtime_then_name(tmp_path):
    for k, name in enumerate(["orbit-205", "orbit-206", "orbit-207", "notes"]):
        (tmp_path / name).mkdir()
        os.utime(tmp_path / name, (1000 + k, 1000 + k))
    assert doall_automate.newest_orbit_dir(tmp_path) == "orbit-207"
    os.utime(tmp_path / "orbit-205", (1002, 1002))       # tie: first name wins, like ls -rt | tail -1
    assert doall_automate.newest_orbit_dir(tmp_path) == "orbit-205"


def test_already_processed(tmp_path):
    records = tmp_path / "records.txt"
    records.write_text("98 205 o1a 3 3 3 3 tess2025001000000 finished\n")
    assert doall_automate.already_processed(records, "205", "o1a", "98 205 o1a 3 3 3 3 tess2025001000000")
    assert not doall_automate.already_processed(records, "205", "o1a", "98 205 o1a 4 3 3 3 tess2025001000000")
    assert not doall_automate.already_processed(records, "205", "o1b", "98 205 o1b 3 3 3 3 tess2025002000000")
    assert not doall_automate.already_processed(tmp_path / "missing", "205", "o1a", "x")


class Args:
    mail_error = "ops@example.org"


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, subject, recipients, message):
        self.sent.append((subject, recipients, message))


@pytest.mark.parametrize("rc, flag, abort", [(0, 0, None), (1, 1, None), (2, None, 2), (137, None, 3)])
def test_check_step_exit_code_contract(rc, flag, abort):
    mailer = FakeMailer()
    if abort is None:
        assert doall_automate.check_step(rc, "tica-x", Args(), mailer, "98 205 o1a") == flag
        assert mailer.sent == []
    else:
        with pytest.raises(doall_automate.Abort) as exc:
            doall_automate.check_step(rc, "tica-x", Args(), mailer, "98 205 o1a")
        assert exc.value.code == abort
        assert mailer.sent[0][:2] == ("tica proceessing error", "ops@example.org")


# ---------------------------------------------------------------- end to end
def make_site(root, orbits=(204, 205), stems=1):
    poc = Path(root) / "poc"
    for k, orbit in enumerate(orbits):
        d = poc / "orbit-{}".format(orbit) / "ffi_fits"
        d.mkdir(parents=True)
        for s in range(stems if orbit == orbits[-1] else 1):
            for fin in range(3):
                for cam in range(1, 5):
                    (d / "tess202500{}000000-{:08d}-{}-crm-ffi.fits".format(s + 1, orbit * 1000 + 10 * s + fin, cam)).touch()
        os.utime(poc / "orbit-{}".format(orbit), (1000 + k, 1000 + k))
    for d in ("work", "delivery", "btjd", "repo"):
        (Path(root) / d).mkdir()
    return ["--dstem", str(poc), "--workdir", str(Path(root) / "work"),
            "--outputdir", str(Path(root) / "delivery"),
            "--records", str(Path(root) / "records.txt"),
            "--ephemeris-kernel", str(Path(root) / "kernel.tm"),
            "--ephemeris-outdir", str(Path(root) / "btjd"),
            "--production-table", str(Path(root) / "production_table.md"),
            "--records-copy", str(Path(root) / "repo"),
            "--caldir", str(Path(root) / "cal"), "--ncores", "8", "--ncores-wcs", "2",
            "--mail-start", "start@x", "--mail-success", "ok@x,ok2@x", "--mail-error", "err@x"]


class FakeSteps:
    """Stands in for _common.run_command and leaves the files each step would."""

    def __init__(self, rcs=None):
        self.calls = []
        self.rcs = rcs or {}

    def __call__(self, module, args, cwd=None):
        args = [str(a) for a in args]
        self.calls.append((module, args))
        cwd = Path(cwd) if cwd else None
        if module == "calibrate_tso":
            for i in range(1, 5):
                for j in range(1, 5):
                    d = cwd / "cam{}_ccd{}".format(i, j)
                    d.mkdir(parents=True, exist_ok=True)
                    (d / "tess2025001000000-00100724-{}-crm-ffi_ccd{}.cal.fits".format(i, j)).touch()
                (cwd / "cam{}_ccd1".format(i) / "cal_timeseries.txt").touch()
        elif module == "darktime":
            orbit = args[args.index("--orbit") + 1]
            for i in range(1, 5):
                for j in range(1, 5):
                    (cwd / "cam{}_ccd{}".format(i, j) / "rms_list").touch()
                (cwd / "cam{}_ccd1".format(i) / "cal_timeseries_{}.png".format(orbit)).touch()
            (cwd / "cam2_ccd3" / "bad_calibration.txt").touch()
            if "--save_reffin" in args:
                (cwd / "reffin.txt").write_text("cam1_ccd1 00100724\ncam1_ccd2 00100725\n")
        elif module == "wcs_step2_allccd":
            for i in range(1, 5):
                for j in range(1, 5):
                    (cwd / "cam{}_ccd{}".format(i, j) / "wcs_diags2").mkdir()
        return self.rcs.get(module, 0)


@pytest.fixture
def run_doall(monkeypatch):
    def run(argv, rcs=None):
        steps = FakeSteps(rcs)
        mailer = FakeMailer()
        monkeypatch.setattr(_common, "run_command", steps)
        monkeypatch.setattr(doall_automate, "Mailer", lambda enabled: mailer)
        return doall_automate.main(argv), steps.calls, mailer.sent
    return run


def test_doall_o1a_success(tmp_path, run_doall):
    rc, calls, mails = run_doall(make_site(tmp_path))

    assert rc == 0
    assert [m for m, _ in calls] == ["dump_ephemeris", "calibrate_tso", "darktime", "wcs_step1_allccd",
                                     "wcs_step2_allccd", "stage_delivery", "check_delivery",
                                     "production_table"]
    args = dict(calls)
    assert args["calibrate_tso"][:6] == ["--o1", "205", "--o2", "None", "--orbseg", "o1a"]
    assert args["wcs_step1_allccd"] == ["--sector", "98", "--dstem", "./", "--reffin", "00100724"]
    assert args["stage_delivery"] == ["v01", str(tmp_path / "delivery") + "/s0098", "o1a", "98"]
    assert args["production_table"] == ["--segments", "o1a", "--wcs1",
                                        "--output", str(tmp_path / "production_table.md")]
    assert [m[1] for m in mails] == ["start@x", "ok@x,ok2@x"]
    assert (tmp_path / "records.txt").read_text() == "98 205 o1a 3 3 3 3 tess2025001000000 finished\n"
    seg = tmp_path / "work" / "sector98" / "cam2_ccd1" / "o1a"
    assert sorted(p.name for p in seg.iterdir()) == [
        "cal_timeseries.txt", "cal_timeseries_o1a.png", "rms_list",
        "tess2025001000000-00100724-2-crm-ffi_ccd1.cal.fits", "wcs_diags2"]
    assert (tmp_path / "work" / "sector98" / "cam2_ccd3" / "o1a" / "bad_calibration.txt").exists()
    assert (tmp_path / "repo" / "records.txt").read_text() == (tmp_path / "records.txt").read_text()



def test_doall_skips_recorded_segment(tmp_path, run_doall):
    argv = make_site(tmp_path)
    (tmp_path / "records.txt").write_text("98 205 o1a 3 3 3 3 tess2025001000000 finished\n")
    assert run_doall(argv) == (0, [], [])


def test_doall_o1b_error_records_and_mails(tmp_path, run_doall):
    rc, calls, mails = run_doall(make_site(tmp_path, stems=2), rcs={"wcs_step2_allccd": 1})

    assert rc == 0
    assert "wcs_step1_allccd" not in [m for m, _ in calls]
    assert "production_table" not in [m for m, _ in calls]
    assert mails[-1][1] == "err@x"
    assert "there were errors" in mails[-1][2]
    assert (tmp_path / "records.txt").read_text() == "98 205 o1b 6 6 6 6 tess2025002000000 error\n"
    assert (tmp_path / "repo" / "records.txt").read_text() == (tmp_path / "records.txt").read_text()


@pytest.mark.parametrize("rc_step, rc_exit", [(2, 2), (137, 3)])
def test_doall_aborts(tmp_path, run_doall, rc_step, rc_exit):
    rc, calls, mails = run_doall(make_site(tmp_path), rcs={"calibrate_tso": rc_step})
    assert rc == rc_exit
    assert [m for m, _ in calls] == ["dump_ephemeris", "calibrate_tso"]
    assert mails[-1][:2] == ("tica proceessing error", "err@x")
    assert not (tmp_path / "records.txt").exists()


def test_doall_off_nominal_downlink(tmp_path, run_doall):
    rc, calls, mails = run_doall(make_site(tmp_path, stems=3))
    assert (rc, calls, mails) == (1, [], [])


def test_doall_overrides_and_environment(tmp_path, run_doall, monkeypatch):
    argv = make_site(tmp_path)
    argv = argv[:argv.index("--ncores")] + argv[argv.index("--ncores") + 2:]
    monkeypatch.setenv("TICA_NCORES", "12")
    rc, calls, _ = run_doall(argv + ["--orbit", "206", "--segment", "o2a"])
    assert rc == 0
    tso = dict(calls)["calibrate_tso"]
    assert tso[:6] == ["--o1", "None", "--o2", "206", "--orbseg", "o2a"]
    assert tso[-2:] == ["--ncores", "12"]
