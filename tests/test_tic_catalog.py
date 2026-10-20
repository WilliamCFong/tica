"""Tests for the TIC provider interface and WCS step 1's use of it."""

import os

import h5py
import numpy as np
import psycopg
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time

from tica.cli import wcs_step1
from wcs_build import step1_get_refimg_ctrlpts as step1
from wcs_build import tic_mast
from wcs_build.tic_catalog import (CCDPointing, Cone, TICCatalog, TICError, TICProvider,
                                   get_provider)
from wcs_build.tic_postgres import PostgresTIC

POINTING = CCDPointing(35, 1, 1, tuple(Cone(10.0 + k, -20.0, 1.7) for k in range(25)))


# ------------------------------------------------------------ contract
def test_from_rows_maps_null_to_nan():
    cat = TICCatalog.from_rows([(5, 1.0, 2.0, 9.0, None, 8.5, 1.0, -2.0)])
    assert cat.tic.dtype == np.int64 and cat.tic.tolist() == [5]
    assert np.isnan(cat.kmag[0]) and cat.gaiamag[0] == 8.5


def test_empty_catalog():
    cat = TICCatalog.empty()
    assert len(cat) == 0
    assert cat.tic.dtype == np.int64 and cat.ra.dtype == np.float64


def test_get_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="postgres, mast"):
        get_provider("sqlite")


# ------------------------------------------------------------ postgres
class FakeCursor:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def execute(self, query, params):
        self.con.executed.append((query, params))

    def fetchall(self):
        return self.con.rows.pop(0) if self.con.rows else []


class FakeConnection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_connect(monkeypatch):
    made = []

    def connect(rows=(), error=None):
        def _connect(**kwargs):
            if error:
                raise error
            con = FakeConnection(rows)
            made.append((kwargs, con))
            return con
        monkeypatch.setattr(psycopg, "connect", _connect)
        return made
    return connect


def test_postgres_one_connection_for_all_cones(fake_connect, monkeypatch):
    monkeypatch.delenv("TICA_TIC_SERVICE", raising=False)
    made = fake_connect(rows=[[(7, 10.0, -20.0, 8.0, None, None, 1.0, 2.0)]])

    with PostgresTIC() as tic:
        catalogs = tic.query(POINTING, 7.5, 12.0)

    assert len(made) == 1
    kwargs, con = made[0]
    assert kwargs == {"service": "tic", "autocommit": True}
    assert con.closed
    assert len(con.executed) == 25 and len(catalogs) == 25
    assert catalogs[0].tic.tolist() == [7] and np.isnan(catalogs[0].kmag[0])
    assert all(len(c) == 0 for c in catalogs[1:])     # empty cones are not an error
    query, params = con.executed[1]
    assert params == (11.0, -20.0, 1.7, 7.5, 12.0, -100.0, 100.0, -100.0, 100.0)
    text = query.as_string(None)
    assert '"ticentries"' in text and "disposition is null" in text and "order by id" in text
    assert tic.source == "postgres:service=tic table=ticentries"


def test_postgres_service_from_environment(fake_connect, monkeypatch):
    monkeypatch.setenv("TICA_TIC_SERVICE", "tic-test")
    made = fake_connect()
    PostgresTIC().close()
    assert made[0][0]["service"] == "tic-test"


def test_postgres_connection_failure_is_tic_error(fake_connect):
    fake_connect(error=psycopg.OperationalError('definition of service "tic" not found'))
    with pytest.raises(TICError, match=r"service 'tic'.*pg_service.conf.*pgpass"):
        PostgresTIC(service="tic")


@pytest.mark.skipif(not os.environ.get("TICA_TIC_TEST_SERVICE"),
                    reason="set TICA_TIC_TEST_SERVICE to a libpq service for a live TIC")
def test_postgres_live_query():
    with PostgresTIC(service=os.environ["TICA_TIC_TEST_SERVICE"]) as tic:
        [cat] = tic.query(CCDPointing(35, 1, 1, (Cone(180.0, 45.0, 0.5),)), 7.5, 12.0)
    assert len(cat) > 0
    assert np.all(np.diff(cat.tic) > 0)
    assert np.all((cat.tmag >= 7.5) & (cat.tmag <= 12.0))
    assert np.all(np.abs(cat.pmra) <= 100) and np.all(np.abs(cat.pmdec) <= 100)


# ------------------------------------------------------------ mast
def mast_row(tic, disposition=None, pmra=1.0):
    return {"ID": tic, "ra": 10.0, "dec": -20.0, "Tmag": 9.0, "Kmag": None, "GAIAmag": 9.1,
            "pmRA": pmra, "pmDEC": 0.5, "disposition": disposition}


def test_mast_applies_the_contract(monkeypatch):
    responses = [{"status": "EXECUTING"},
                 {"status": "COMPLETE", "data": [mast_row(9), mast_row(3, "DUPLICATE"),
                                                 mast_row(4, "ARTIFACT"), mast_row(5, pmra=None),
                                                 mast_row(2)]}]
    requests = []
    monkeypatch.setattr(tic_mast, "mast_query",
                        lambda request, timeout: requests.append(request) or responses.pop(0))
    sleeps = []
    [cat] = tic_mast.MastTIC(sleep=sleeps.append).query(
        CCDPointing(35, 1, 1, (Cone(10.0, -20.0, 1.7),)), 7.5, 12.0)

    assert cat.tic.tolist() == [2, 9]
    assert np.isnan(cat.kmag).all()
    assert len(sleeps) == 1
    params = requests[0]["params"]
    assert params["radius"] == " 1.7000000"
    assert params["filters"][0] == {"paramName": "Tmag", "values": [{"min": 7.5, "max": 12.0}]}


def test_mast_gives_up_with_tic_error(monkeypatch):
    def fail(request, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(tic_mast, "mast_query", fail)
    with pytest.raises(TICError, match="after 3 attempts: connection refused"):
        tic_mast.MastTIC(attempts=3, sleep=lambda s: None).cone_search(Cone(1, 2, 3), 7.5, 12.0)


# ------------------------------------------------------------ epoch
def test_reference_epoch_tso_and_spoc_headers():
    tso = fits.Header({"MIDTJD": 2260.25, "TJD_ZERO": 2457000.0})
    assert step1.reference_epoch(tso).jd == 2459260.25
    spoc = fits.Header({"TSTART": 2260.0, "TSTOP": 2260.5, "BJDREFI": 2457000, "BJDREFF": 0.0})
    assert step1.reference_epoch(spoc).jd == 2459260.25
    with pytest.raises(ValueError):
        step1.reference_epoch(fits.Header({"DATE-OBS": "2021-02-15"}))


def test_proper_motion_propagates_to_epoch():
    epoch = Time("J2010.0")
    ra, dec = step1.apply_proper_motion(np.array([30.0]), np.array([0.0]),
                                        np.array([100.0]), np.array([-50.0]), epoch)
    moved = SkyCoord(30.0, 0.0, unit="deg").spherical_offsets_to(SkyCoord(ra[0], dec[0], unit="deg"))
    assert moved[0].to_value(u.mas) == pytest.approx(1000.0, rel=1e-3)
    assert moved[1].to_value(u.mas) == pytest.approx(-500.0, rel=1e-3)


# ------------------------------------------------------------ step 1 end to end
class FakeTIC(TICProvider):
    """Stars from a table, selected per cone like the real providers."""

    source = "fake"

    def __init__(self, stars):
        self.stars = stars
        self.pointings = []

    def query(self, pointing, tmag_min, tmag_max):
        self.pointings.append(pointing)
        coords = SkyCoord(self.stars.ra, self.stars.dec, unit="deg")
        out = []
        for cone in pointing.cones:
            sep = coords.separation(SkyCoord(cone.ra, cone.dec, unit="deg")).deg
            m = (sep <= cone.radius) & (self.stars.tmag >= tmag_min) & (self.stars.tmag <= tmag_max)
            out.append(TICCatalog(*(getattr(self.stars, f)[m] for f in
                                    ("tic", "ra", "dec", "tmag", "kmag", "gaiamag", "pmra", "pmdec"))))
        return out


def make_reference(tmp_path, n=750):
    """A sector 35 cam1/ccd1 reference image with n stars, and their TIC entries."""
    from tess_stars2px import tess_stars2px_reverse_function_entry

    rng = np.random.default_rng(3)
    cols = rng.uniform(60.0, 2080.0, n)
    rows = rng.uniform(15.0, 2035.0, n)
    tmags = rng.uniform(7.6, 11.9, n)
    tmags[0] = 8.0                          # a bright high proper-motion star
    ras, decs = np.empty(n), np.empty(n)
    scinfo = None
    for i in range(n):
        if scinfo is None:
            ras[i], decs[i], scinfo = tess_stars2px_reverse_function_entry(35, 1, 1, cols[i], rows[i])
        else:
            ras[i], decs[i], scinfo = tess_stars2px_reverse_function_entry(35, 1, 1, cols[i], rows[i],
                                                                           scinfo)
    pmra, pmdec = np.zeros(n), np.zeros(n)
    pmra[0], pmdec[0] = 90.0, -80.0

    # a calibrated image: low background, so faint stars pass step 1's contrast test
    image = rng.normal(50.0, 3.0, (2078, 2136)).astype(np.float32)
    yy, xx = np.mgrid[-5:6, -5:6]
    for col, row, tmag in zip(cols, rows, tmags):
        c, r = int(round(col)) - 1, int(round(row)) - 1
        dc, dr = col - 1 - c, row - 1 - r
        image[r - 5:r + 6, c - 5:c + 6] += (2e5 * 10 ** (-0.4 * (tmag - 7.5))
                                            * np.exp(-((xx - dc) ** 2 + (yy - dr) ** 2) / 1.0))
    name = tmp_path / "tess2021041025908-00149615-1-crm-ffi_ccd1.cal.fits"
    fits.writeto(name, image, fits.Header({"MIDTJD": 2260.25, "TJD_ZERO": 2457000.0}))
    stars = TICCatalog(np.arange(1000, 1000 + n, dtype=np.int64), ras, decs, tmags,
                       np.full(n, np.nan), np.full(n, np.nan), pmra, pmdec)
    return name, stars


def test_step1_uses_provider_and_records_epoch(tmp_path):
    ref, stars = make_reference(tmp_path)
    tic = FakeTIC(stars)
    out = tmp_path / "reftica_s35_1-1.h5"

    step1.get_refimg_ctrlpts(35, 1, 1, str(ref), str(out), catalog=tic)

    [pointing] = tic.pointings
    assert (pointing.sector, pointing.camera, pointing.ccd) == (35, 1, 1)
    assert len(pointing.cones) == 25
    with h5py.File(out, "r") as f:
        assert f.attrs["pm_epoch_jd"] == 2459260.25
        assert f.attrs["tic_source"] == "fake"
        assert f.attrs["ref_FIN"] == "00149615"
        tics = f["tics"][:]
        assert len(tics) > 300
        assert len(set(f["blkidxs"][:])) == 25
        assert 1000 in tics
        k = list(tics).index(1000)
        ra, dec = f["ras"][k], f["decs"][k]
    want_ra, want_dec = step1.apply_proper_motion(stars.ra[:1], stars.dec[:1], stars.pmra[:1],
                                                  stars.pmdec[:1], Time(2459260.25, format="jd",
                                                                        scale="tdb"))
    assert (ra, dec) == (want_ra[0], want_dec[0])
    # 21 years at ~120 mas/yr
    assert SkyCoord(ra, dec, unit="deg").separation(
        SkyCoord(stars.ra[0], stars.dec[0], unit="deg")).arcsec == pytest.approx(2.53, abs=0.05)


def test_wcs_step1_cli_exit_2_when_tic_unreachable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(psycopg, "connect", lambda **kw: (_ for _ in ()).throw(
        psycopg.OperationalError("no such service")))
    rc = wcs_step1.main(["-s", "35", "-ca", "1", "-cd", "1", "-ri", str(tmp_path / "ref.fits"),
                         "-o", str(tmp_path / "out.h5"), "--tic-service", "nope",
                         "-l", str(tmp_path / "step1.log")])
    assert rc == 2
    assert "service 'nope'" in capsys.readouterr().err
