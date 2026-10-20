"""Installation smoke tests.

These run without the DVC-managed calibration models or regression data, so
they can be used to check a fresh environment (e.g. a newly built Docker image).
The full end-to-end check is still reg_test/run_reg_test.py.
"""
import importlib
import os
import shutil
import subprocess
import sysconfig
from importlib.metadata import version as dist_version

import numpy as np
import pytest

SCRIPTS = [
    "tica-cal-ccd2ccd",
    "tica-cal-ffi2ccds",
    "tica-cal-ffi2ffi",
    "tica-ccd-report",
    "tica-ffi2ccds",
    "tica-ccds2ffi",
    "tica-trim-ccds2ffi",
    "tica-production-table",
    "tica-darktime",
    "tica-wcs-step1",
    "tica-wcs-step2",
    "tica-dump-ephemeris",
    "tica-calibrate-spoc",
    "tica-wcs-spoc",
]


@pytest.mark.parametrize("module", [
    "tica",
    "tica.tica",
    "btjd.btjd_correction",
    "wcs_build.step1_get_refimg_ctrlpts",
    "wcs_build.step2_mkwcs",
])
def test_import(module):
    importlib.import_module(module)


def test_version_matches_metadata():
    import tica
    import tica.tica
    assert tica.version == dist_version("tica")
    assert tica.tica.version == tica.version


def test_ephemeris_is_packaged():
    from wcs_build.step2_mkwcs import ephemeris_data
    assert ephemeris_data.ndim == 2 and ephemeris_data.shape[1] >= 7


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_help(script):
    # Scripts land next to the interpreter even when the environment isn't activated
    search_path = os.pathsep.join([sysconfig.get_path("scripts"), os.environ.get("PATH", "")])
    path = shutil.which(script, path=search_path)
    assert path is not None, f"{script} is not on PATH"
    result = subprocess.run([path, "--help"], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=120)
    assert "Traceback" not in result.stderr, result.stderr
    assert "usage" in (result.stdout + result.stderr).lower()


def test_fit_wcs_recovers_tess_point_model():
    """Fit a WCS to stars placed with the tess-point model, as step2 does on real data.

    Guards the gwcs.wcstools.wcs_from_points call and the layout of the
    returned forward transform that fit_wcs relies on.
    """
    from astropy.wcs import WCS
    from tess_stars2px import tess_stars2px_reverse_function_entry
    from wcs_build.step2_mkwcs import fit_wcs

    sector, camera, ccd = 35, 1, 1
    rng = np.random.default_rng(42)
    n = 600
    cols = rng.uniform(60.0, 2080.0, n)
    rows = rng.uniform(10.0, 2040.0, n)
    ras = np.empty(n)
    decs = np.empty(n)
    for i in range(n):
        ras[i], decs[i], _ = tess_stars2px_reverse_function_entry(
            sector, camera, ccd, cols[i], rows[i])
    tmags = rng.uniform(7.0, 11.0, n)
    # 5x5 grid of control-point blocks, as built by step1
    blkidxs = (np.clip(rows // 410, 0, 4) * 5 + np.clip((cols - 45) // 410, 0, 4)).astype(int)

    hdr, allstd, *_rest, gdResids, exResids = fit_wcs(
        ras, decs, cols, rows, tmags, sector, camera, ccd,
        blkidxs=blkidxs, NCOL=5, fitDegree=5)

    assert hdr["AP_ORDER"] == 5
    # 4-sigma clipping on a near-perfect fit rejects a handful of points
    assert gdResids.mean() > 0.95
    # tess-point is itself a smooth polynomial model, so the fit should be near
    # exact (~0.035 arcsec rms with gwcs 0.16 and 1.0 alike)
    assert allstd < 0.1  # arcsec
    assert np.all(exResids < 0.1)

    # The SIP header written for the FFIs must reproduce the input positions
    w = WCS(hdr)
    fit_ras, fit_decs = w.all_pix2world(cols, rows, 1)
    sep = np.hypot((fit_ras - ras) * np.cos(np.radians(decs)), fit_decs - decs) * 3600.0
    assert np.max(sep) < 1.0  # arcsec
