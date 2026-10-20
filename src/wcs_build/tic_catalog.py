"""The TIC query contract for WCS step 1.

Step 1 asks a provider for the TESS Input Catalog stars around one CCD:
a CCDPointing gives the sector, camera and CCD, and the cones (one per
analysis block) that cover the CCD. The provider returns one TICCatalog
per cone, in the same order. Step 1 then predicts pixel positions with
tess-point and keeps, for each block, the stars that land in it, so a
star may appear in several cones' catalogs.

Every provider must return the same selection, which is what TICA has
always used in production:

- Positions are the TIC's, at epoch J2000 (TIC v8). Step 1 propagates
  them to the reference image's epoch with the proper motions.
- Proper motions are in mas/yr; pmra includes the cos(dec) factor.
- Only stars with tmag_min <= Tmag <= tmag_max (inclusive).
- Only stars whose disposition is NULL. This drops every flagged entry,
  including DUPLICATE, SPLIT and ARTIFACT.
- Only stars with -100 <= pmRA <= 100 and -100 <= pmDEC <= 100 mas/yr.
  Stars with a NULL proper motion fail this test and are excluded.
- Kmag and GAIAmag may be NULL; they are returned as NaN. Step 1 does not
  use them.
- Each catalog is sorted by TIC ID. A cone with no stars gives an empty
  catalog, not an error.

Providers raise TICError when the catalog cannot be reached or queried.
"""

import abc
from dataclasses import dataclass

import numpy as np

FIELDS = ('tic', 'ra', 'dec', 'tmag', 'kmag', 'gaiamag', 'pmra', 'pmdec')

# proper-motion limit of the selection, mas/yr
PM_LIMIT = 100.0


class TICError(RuntimeError):
    """The TIC could not be reached or queried."""


@dataclass(frozen=True)
class Cone:
    """A cone on the sky; all values in degrees."""
    ra: float
    dec: float
    radius: float


@dataclass(frozen=True)
class CCDPointing:
    """The cones that cover one CCD in one sector."""
    sector: int
    camera: int
    ccd: int
    cones: tuple


@dataclass
class TICCatalog:
    """Catalog fields for a set of stars, one array per field (see FIELDS)."""
    tic: np.ndarray
    ra: np.ndarray
    dec: np.ndarray
    tmag: np.ndarray
    kmag: np.ndarray
    gaiamag: np.ndarray
    pmra: np.ndarray
    pmdec: np.ndarray

    def __len__(self):
        return len(self.tic)

    @classmethod
    def empty(cls):
        return cls.from_rows([])

    @classmethod
    def from_rows(cls, rows):
        """Build from rows of (tic, ra, dec, tmag, kmag, gaiamag, pmra, pmdec); None becomes NaN."""
        rows = list(rows)
        tic = np.array([row[0] for row in rows], dtype=np.int64)
        columns = [np.array([np.nan if row[k] is None else float(row[k]) for row in rows],
                            dtype=np.float64)
                   for k in range(1, len(FIELDS))]
        return cls(tic, *columns)


class TICProvider(abc.ABC):
    """Gives the TIC stars around a CCD pointing; see the module docstring for the contract."""

    #: short description of the catalog source, recorded in step 1's output
    source = ''

    @abc.abstractmethod
    def query(self, pointing, tmag_min, tmag_max):
        """Return a list with one TICCatalog for each cone in pointing.cones."""

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class ConeSearchProvider(TICProvider):
    """A provider that queries one cone at a time."""

    @abc.abstractmethod
    def cone_search(self, cone, tmag_min, tmag_max):
        """Return the TICCatalog for one cone."""

    def query(self, pointing, tmag_min, tmag_max):
        return [self.cone_search(cone, tmag_min, tmag_max) for cone in pointing.cones]


PROVIDERS = ('postgres', 'mast')


def get_provider(name, **options):
    """A provider by name: 'postgres' (PostgresTIC) or 'mast' (MastTIC)."""
    if name == 'postgres':
        from wcs_build.tic_postgres import PostgresTIC
        return PostgresTIC(**options)
    if name == 'mast':
        from wcs_build.tic_mast import MastTIC
        return MastTIC(**options)
    raise ValueError("unknown TIC provider {!r}; choose from {}".format(name, ', '.join(PROVIDERS)))
