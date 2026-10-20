"""Barycentric time corrections from TESS's position, tabulated in tess_ephem.txt."""

import os
from importlib.resources import files

EPHEMERIS_ENV = 'TICA_EPHEMERIS'


def packaged_ephemeris():
    """The tess_ephem.txt installed with this package."""
    return str(files('btjd').joinpath('tess_ephem.txt'))


def ephemeris_path():
    """The tess_ephem.txt the WCS step reads and tica-dump-ephemeris extends.

    $TICA_EPHEMERIS if set, otherwise the copy installed with this package.
    """
    return os.environ.get(EPHEMERIS_ENV) or packaged_ephemeris()
