"""The TIC from the MAST catalog API (Mast.Catalogs.Filtered.Tic.Position.Rows).

Needs no credentials, but is much slower than a local database: one
request per cone, and MAST may answer "EXECUTING" until the query
finishes. See wcs_build.tic_catalog for the selection returned; the
disposition and NULL proper-motion rules are applied here, since the MAST
filters cannot express them.
"""

import json
import logging
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

from wcs_build.tic_catalog import PM_LIMIT, ConeSearchProvider, TICCatalog, TICError

MAST_URL = 'https://mast.stsci.edu/api/v0/invoke'
COLUMNS = ('ID', 'ra', 'dec', 'Tmag', 'Kmag', 'GAIAmag', 'pmRA', 'pmDEC')

logger = logging.getLogger(__name__)


def mast_query(request, timeout):
    """POST a MAST API request; return the decoded JSON response."""
    version = ".".join(map(str, sys.version_info[:3]))
    headers = {"Content-type": "application/x-www-form-urlencoded",
               "Accept": "text/plain",
               "User-agent": "python-requests/" + version}
    data = ("request=" + quote(json.dumps(request))).encode()
    with urlopen(Request(MAST_URL, data=data, headers=headers), timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def cone_request(cone, tmag_min, tmag_max):
    return {'service': 'Mast.Catalogs.Filtered.Tic.Position.Rows',
            'params': {'columns': ','.join(COLUMNS + ('disposition',)),
                       'filters': [
                           {'paramName': 'Tmag', 'values': [{'min': tmag_min, 'max': tmag_max}]},
                           {'paramName': 'pmRA', 'values': [{'min': -PM_LIMIT, 'max': PM_LIMIT}]},
                           {'paramName': 'pmDEC', 'values': [{'min': -PM_LIMIT, 'max': PM_LIMIT}]}],
                       'ra': '{:10.5f}'.format(cone.ra),
                       'dec': '{:10.5f}'.format(cone.dec),
                       'radius': '{:10.7f}'.format(cone.radius)},
            'format': 'json', 'removenullcolumns': False}


def select_rows(data):
    """Rows of the contract's selection from MAST's 'data' list, sorted by TIC ID."""
    rows = [tuple(x[c] for c in COLUMNS) for x in data
            if x['disposition'] is None and x['pmRA'] is not None and x['pmDEC'] is not None]
    return sorted(rows, key=lambda row: row[0])


class MastTIC(ConeSearchProvider):

    source = 'mast'

    def __init__(self, timeout=120, attempts=10, wait=5.0, sleep=time.sleep):
        self.timeout = timeout
        self.attempts = attempts
        self.wait = wait
        self._sleep = sleep

    def cone_search(self, cone, tmag_min, tmag_max):
        request = cone_request(cone, tmag_min, tmag_max)
        problem = None
        for attempt in range(self.attempts):
            if attempt:
                self._sleep(self.wait)
            try:
                response = mast_query(request, self.timeout)
            except (OSError, ValueError) as e:
                problem = e
                logger.warning('MAST cone search failed ({}); retrying'.format(e))
                continue
            status = response.get('status')
            if status == 'EXECUTING':
                problem = 'query still executing'
                continue
            if status == 'ERROR' or 'data' not in response:
                problem = response.get('msg') or 'status {}'.format(status)
                logger.warning('MAST cone search failed ({}); retrying'.format(problem))
                continue
            return TICCatalog.from_rows(select_rows(response['data']))
        raise TICError('MAST cone search at ra={:.5f} dec={:.5f} failed after {} attempts: {}'.format(
            cone.ra, cone.dec, self.attempts, problem))
