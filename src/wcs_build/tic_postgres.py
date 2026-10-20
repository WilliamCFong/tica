"""The TIC from a PostgreSQL copy with the q3c extension (the MIT production servers).

Connection details come from a libpq service file, not from TICA: the
service (default 'tic', or $TICA_TIC_SERVICE) is looked up in
$PGSERVICEFILE or ~/.pg_service.conf, and the password in ~/.pgpass
(which must be chmod 600). For example:

  # ~/.pg_service.conf
  [tic]
  host=tic-db.example.edu
  port=5432
  dbname=tic
  user=tica

  # ~/.pgpass
  tic-db.example.edu:5432:tic:tica:<password>

The table needs the columns id, ra, dec, tmag, kmag, gaiamag, pmra, pmdec
and disposition. See wcs_build.tic_catalog for the selection returned.
"""

import os

from wcs_build.tic_catalog import PM_LIMIT, ConeSearchProvider, TICCatalog, TICError

DEFAULT_SERVICE = 'tic'
DEFAULT_TABLE = 'ticentries'

QUERY = ("select id, ra, dec, tmag, kmag, gaiamag, pmra, pmdec from {table}"
         " where q3c_radial_query(ra, dec, %s, %s, %s)"
         " and tmag between %s and %s"
         " and pmra between %s and %s and pmdec between %s and %s"
         " and disposition is null"
         " order by id")


def default_service():
    return os.environ.get('TICA_TIC_SERVICE') or DEFAULT_SERVICE


class PostgresTIC(ConeSearchProvider):
    """Cone searches on one connection, opened here and closed by close()."""

    def __init__(self, service=None, table=DEFAULT_TABLE):
        import psycopg
        from psycopg import sql

        self.service = service or default_service()
        self.table = table
        self.source = 'postgres:service={} table={}'.format(self.service, table)
        self._query = sql.SQL(QUERY).format(table=sql.Identifier(table))
        try:
            # autocommit: read-only queries, so don't hold a transaction open between them
            self._con = psycopg.connect(service=self.service, autocommit=True)
        except psycopg.OperationalError as e:
            raise TICError(
                "cannot connect to the TIC with PostgreSQL service {!r}: {}. Check the [{}] entry "
                "in $PGSERVICEFILE or ~/.pg_service.conf and the password in ~/.pgpass.".format(
                    self.service, str(e).strip(), self.service)) from e

    def cone_search(self, cone, tmag_min, tmag_max):
        import psycopg

        params = (cone.ra, cone.dec, cone.radius, tmag_min, tmag_max,
                  -PM_LIMIT, PM_LIMIT, -PM_LIMIT, PM_LIMIT)
        try:
            with self._con.cursor() as cur:
                cur.execute(self._query, params)
                return TICCatalog.from_rows(cur.fetchall())
        except psycopg.Error as e:
            raise TICError("TIC query on {} failed: {}".format(self.source, str(e).strip())) from e

    def close(self):
        self._con.close()
