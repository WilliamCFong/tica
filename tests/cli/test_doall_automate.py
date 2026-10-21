"""Tests for tica-doall-automate, with every step and the mailer stubbed."""

import os
from pathlib import Path

import pytest

from tica.cli import _common, _segments, doall_automate


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
            "--ephemeris-file", str(Path(root) / "btjd" / "tess_ephem.txt"),
            "--production-table", str(Path(root) / "production_table.md"),
            "--records-copy", str(Path(root) / "repo"),
            "--caldir", str(Path(root) / "cal"), "--ncores", "8", "--ncores-wcs", "2",
            "--mail-start", "start@x", "--mail-success", "ok@x,ok2@x", "--mail-error", "err@x"]


def make_ref_stars(root, sector=98):
    """The o1a reference star lists that later segments need."""
    refout = Path(root) / "work" / "sector{}".format(sector) / "refout"
    refout.mkdir(parents=True, exist_ok=True)
    for i in range(1, 5):
        for j in range(1, 5):
            (refout / "reftica_s{}_{}-{}.h5".format(sector, i, j)).touch()


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
                    if "--fin" in args:
                        (d / "tess2025001000000-00100724-{}-crm-ffi_ccd{}.cal.fits".format(i, j)).touch()
                    if "--hlspdir" in args:
                        out = Path(args[args.index("--hlspdir") + 1]) / "cam{}-ccd{}".format(i, j)
                        out.mkdir(parents=True, exist_ok=True)
                        (out / "hlsp_tica_tess_ffi_s0098-o1-00100724-cam{}-ccd{}_tess_v01_img.fits".format(i, j)).touch()
                        (d / "wcs_diags2").mkdir(exist_ok=True)
                if "--fin" not in args and "--no_diagnostics" not in args:
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
        elif module == "wcs_step1_allccd":
            make_ref_stars(cwd.parent.parent, int(args[args.index("--sector") + 1]))
            if self.rcs.get(module, 0):
                # a failed step 1: cameras 1 and 2 got no star list
                for f in (cwd / "refout").glob("reftica_s*_[12]-*.h5"):
                    f.unlink()
        return self.rcs.get(module, 0)


@pytest.fixture
def run_doall(monkeypatch):
    def run(argv, rcs=None, cadence=200.0):
        steps = FakeSteps(rcs)
        mailer = FakeMailer()
        monkeypatch.setattr(_common, "run_command", steps)
        monkeypatch.setattr(doall_automate, "Mailer", lambda enabled: mailer)
        # the fake FFIs are empty: 200 s cadences
        monkeypatch.setattr(_segments, "cadence_seconds", lambda path: cadence)
        # the run exports TICA_EPHEMERIS for its steps; keep that out of other tests
        monkeypatch.setattr(os, "environ", dict(os.environ))
        return doall_automate.main(argv), steps.calls, mailer.sent
    return run


def test_doall_o1a_success(tmp_path, run_doall):
    rc, calls, mails = run_doall(make_site(tmp_path))

    assert rc == 0
    assert [m for m, _ in calls] == ["dump_ephemeris", "calibrate_tso", "darktime", "calibrate_tso",
                                     "wcs_step1_allccd", "calibrate_tso", "stage_delivery",
                                     "check_delivery", "production_table"]
    delivery = str(tmp_path / "delivery") + "/s0098"
    tso = [a for m, a in calls if m == "calibrate_tso"]
    assert all(a[:6] == ["--o1", "205", "--o2", "None", "--orbseg", "o1a"] for a in tso)
    assert tso[0][-1:] == ["--no_write"]
    assert tso[1][-2:] == ["--fin", "00100724"]
    assert tso[2][-5:] == ["--hlspdir", delivery, "--sector", "98", "--no_diagnostics"]
    args = dict(calls)
    ephem = str(tmp_path / "btjd" / "tess_ephem.txt")
    assert args["dump_ephemeris"] == ["--ephemeris", str(tmp_path / "kernel.tm"), "--output", ephem]
    assert os.environ["TICA_EPHEMERIS"] == ephem
    assert args["wcs_step1_allccd"] == ["--sector", "98", "--dstem", "./", "--reffin", "00100724",
                                        "--overwrite"]
    assert args["stage_delivery"] == ["v01", delivery, "o1a", "98", "--ref-stars-only"]
    assert args["production_table"] == ["--segments", "o1a", "--wcs1",
                                        "--output", str(tmp_path / "production_table.md")]
    assert [m[1] for m in mails] == ["start@x", "ok@x,ok2@x"]
    assert (tmp_path / "records.txt").read_text() == "98 205 o1a 3 3 3 3 tess2025001000000 finished\n"
    seg = tmp_path / "work" / "sector98" / "cam2_ccd1" / "o1a"
    assert sorted(p.name for p in seg.iterdir()) == [
        "cal_timeseries.txt", "cal_timeseries_o1a.png", "rms_list", "wcs_diags2"]
    # the reference frames for tica-wcs-step1 are not kept
    assert list((tmp_path / "work").rglob("tess*fits")) == []
    assert (tmp_path / "delivery" / "s0098" / "cam2-ccd1").is_dir()
    assert (tmp_path / "work" / "sector98" / "cam2_ccd3" / "o1a" / "bad_calibration.txt").exists()
    assert (tmp_path / "repo" / "records.txt").read_text() == (tmp_path / "records.txt").read_text()



def test_doall_skips_recorded_segment(tmp_path, run_doall):
    argv = make_site(tmp_path)
    (tmp_path / "records.txt").write_text("98 205 o1a 3 3 3 3 tess2025001000000 finished\n")
    assert run_doall(argv) == (0, [], [])


def test_doall_o1b_error_records_and_mails(tmp_path, run_doall):
    argv = make_site(tmp_path, stems=2)
    make_ref_stars(tmp_path)
    (tmp_path / "records.txt").write_text("98 205 o1a 3 3 3 3 tess2025001000000 finished\n")
    rc, calls, mails = run_doall(argv, rcs={"calibrate_tso": 1})

    assert rc == 0
    assert [m for m, _ in calls] == ["dump_ephemeris", "calibrate_tso", "darktime", "stage_delivery",
                                     "check_delivery"]
    assert dict(calls)["calibrate_tso"][-4:] == ["--hlspdir", str(tmp_path / "delivery") + "/s0098",
                                                 "--sector", "98"]
    assert "production_table" not in [m for m, _ in calls]
    assert mails[-1][1] == "err@x"
    assert "there were errors" in mails[-1][2]
    assert (tmp_path / "records.txt").read_text().splitlines()[-1] == \
        "98 205 o1b 3 3 3 3 tess2025002000000 error"
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
    # orbit 206 is not the newest directory, and its segment comes from its own files
    argv = make_site(tmp_path, orbits=(204, 206, 205))
    argv = argv[:argv.index("--ncores")] + argv[argv.index("--ncores") + 2:]
    monkeypatch.setenv("TICA_NCORES", "12")
    make_ref_stars(tmp_path)
    rc, calls, _ = run_doall(argv + ["--orbit", "206", "--segment", "o2a"])
    assert rc == 0
    tso = dict(calls)["calibrate_tso"]
    assert tso[:6] == ["--o1", "None", "--o2", "206", "--orbseg", "o2a"]
    assert tso[tso.index("--ncores") + 1] == "12"


def without_option(argv, name):
    i = argv.index(name)
    return argv[:i] + argv[i + 2:]


def test_doall_defaults_without_a_checkout(tmp_path, run_doall, monkeypatch, capsys):
    monkeypatch.setattr(_common, "checkout_root", lambda: None)
    for name in ("TICA_CALDIR", "TICA_RECORDS_COPY", "TICA_PRODUCTION_TABLE", "TICA_EPHEMERIS"):
        monkeypatch.delenv(name, raising=False)
    argv = make_site(tmp_path)
    for name in ("--production-table", "--records-copy", "--ephemeris-file"):
        argv = without_option(argv, name)

    # without a checkout there is no default calibration directory
    rc, calls, _ = run_doall(without_option(argv, "--caldir"))
    assert (rc, calls) == (2, [])
    assert "set --caldir or TICA_CALDIR" in capsys.readouterr().out

    rc, calls, _ = run_doall(argv)
    assert rc == 0
    args = dict(calls)
    assert args["dump_ephemeris"] == ["--ephemeris", str(tmp_path / "kernel.tm")]
    assert args["production_table"][-2:] == ["--output", str(tmp_path / "work" / "production_table.md")]
    assert not (tmp_path / "repo" / "records.txt").exists()


def test_doall_defaults_from_the_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "checkout_root", lambda: str(tmp_path / "tica"))
    for name in ("TICA_CALDIR", "TICA_RECORDS_COPY", "TICA_PRODUCTION_TABLE"):
        monkeypatch.delenv(name, raising=False)
    args = doall_automate.build_parser().parse_args([])
    assert args.caldir == str(tmp_path / "tica" / "calibration_200sec")
    assert args.records_copy == str(tmp_path / "tica")
    assert args.production_table == str(tmp_path / "tica" / "production_table.md")


def test_doall_later_segment_needs_o1a_star_lists(tmp_path, run_doall, capsys):
    argv = make_site(tmp_path, stems=2)
    refout = tmp_path / "work" / "sector98" / "refout"
    refout.mkdir(parents=True)
    for k in range(15):
        (refout / "reftica_s98_{}-{}.h5".format(k // 4 + 1, k % 4 + 1)).touch()

    (tmp_path / "records.txt").write_text("98 205 o1a 3 3 3 3 tess2025001000000 finished\n")
    rc, calls, mails = run_doall(argv)

    assert rc == 2
    assert [m for m, _ in calls] == ["dump_ephemeris"]
    out = capsys.readouterr().out
    assert "1 of the 16 are missing" in out and "reftica_s98_4-4.h5" in out
    assert "Process that segment first" in out


def test_doall_records_must_be_a_file(tmp_path, run_doall, capsys):
    argv = make_site(tmp_path)
    argv[argv.index("--records") + 1] = str(tmp_path)
    rc, calls, _ = run_doall(argv)
    assert (rc, calls) == (2, [])
    assert "is a directory" in capsys.readouterr().out


def test_doall_orbit_with_both_halves_runs_them_in_order(tmp_path, run_doall):
    argv = make_site(tmp_path, orbits=(205, 206), stems=1)
    # orbit 205 is not the newest; it has both halves, neither processed yet
    orbit = tmp_path / "poc" / "orbit-205" / "ffi_fits"
    for fin in range(3):
        for cam in range(1, 5):
            (orbit / "tess2025002000000-{:08d}-{}-crm-ffi.fits".format(205010 + fin, cam)).touch()

    rc, calls, mails = run_doall(argv + ["--orbit", "205"])

    assert rc == 0
    modules = [m for m, _ in calls]
    assert modules.count("dump_ephemeris") == 1
    segments = [a[a.index("--orbseg") + 1] for m, a in calls if m == "calibrate_tso"]
    assert segments == ["o1a", "o1a", "o1a", "o1b"]
    assert (tmp_path / "records.txt").read_text().splitlines() == [
        "98 205 o1a 3 3 3 3 tess2025001000000 finished",
        "98 205 o1b 3 3 3 3 tess2025002000000 finished"]
    assert [m[1] for m in mails] == ["start@x", "ok@x,ok2@x", "start@x", "ok@x,ok2@x"]

    # rerunning finds both recorded
    assert run_doall(argv + ["--orbit", "205"])[1] == []


def test_doall_unknown_segment(tmp_path, run_doall, capsys):
    rc, calls, _ = run_doall(make_site(tmp_path) + ["--segment", "o1b"])
    assert (rc, calls) == (2, [])
    assert "Orbit 205 has no segment o1b; its FFIs make o1a" in capsys.readouterr().out


def test_doall_whole_orbit(tmp_path, run_doall):
    # an older orbit downlinked in one piece: 600 s cadences spanning ~12.7 days
    argv = make_site(tmp_path, orbits=(205,))
    orbit = tmp_path / "poc" / "orbit-205" / "ffi_fits"
    for cam in range(1, 5):
        (orbit / "tess2025001000000-00206829-{}-crm-ffi.fits".format(cam)).touch()
    rc, calls, mails = run_doall(argv, cadence=600.0)

    assert rc == 0
    tso = [a for m, a in calls if m == "calibrate_tso"]
    assert len(tso) == 3 and all(a[a.index("--orbseg") + 1] == "o1" for a in tso)
    assert "wcs_step1_allccd" in [m for m, _ in calls]
    assert dict(calls)["production_table"][:3] == ["--segments", "o1", "--wcs1"]
    assert (tmp_path / "records.txt").read_text().splitlines()[-1] == \
        "98 205 o1 4 4 4 4 tess2025001000000 finished"


def test_doall_stops_when_step1_makes_no_star_lists(tmp_path, run_doall):
    rc, calls, mails = run_doall(make_site(tmp_path), rcs={"wcs_step1_allccd": 1})

    assert rc == 3
    assert [m for m, _ in calls] == ["dump_ephemeris", "calibrate_tso", "darktime", "calibrate_tso",
                                     "wcs_step1_allccd"]
    subject, recipients, message = mails[-1]
    assert (subject, recipients) == ("tica proceessing error", "err@x")
    assert "for 8 CCDs (1-1, 1-2, 1-3, 1-4, 2-1, 2-2, 2-3, 2-4)" in message
    assert "reference FIN 00100724" in message
    assert (tmp_path / "records.txt").read_text() == "98 205 o1a 3 3 3 3 tess2025001000000 error\n"
    # the reference frames are kept to look at
    assert len(list((tmp_path / "work" / "sector98").glob("cam*_ccd*/tess*fits"))) == 16


def test_doall_reffin_override(tmp_path, run_doall):
    rc, calls, _ = run_doall(make_site(tmp_path) + ["--reffin", "100800"])
    assert rc == 0
    args = dict(calls)
    assert args["wcs_step1_allccd"][args["wcs_step1_allccd"].index("--reffin") + 1] == "00100800"
    fin_run = [a for m, a in calls if m == "calibrate_tso"][1]
    assert fin_run[-2:] == ["--fin", "00100800"]


def test_doall_stops_without_a_reference_frame(tmp_path, run_doall, monkeypatch):
    monkeypatch.setattr(doall_automate, "read_reffin", lambda workdir: "")
    rc, calls, mails = run_doall(make_site(tmp_path))
    assert rc == 3
    assert [m for m, _ in calls] == ["dump_ephemeris", "calibrate_tso", "darktime"]
    assert "Pick one by hand with --reffin" in mails[-1][2]
    assert (tmp_path / "records.txt").read_text().endswith(" error\n")
