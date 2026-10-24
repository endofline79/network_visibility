"""Shared, bounded recent public-endpoint observations from router NetFlow.

This is a snapshot of flow-end observations, not a packet stream. Overlapping
queries recover late exports inside the five-minute window. Endpoint last-seen
identities do not advance for retries, duplicate receipts, or older late exports.
No collector changes, client attribution, ingest timestamp, or arbitrary query.
"""
import collections
import copy
import hashlib
import ipaddress
import threading
import time
from datetime import datetime, timedelta, timezone
from .filterlog import public_endpoint
from .locations import aggregate
from .service import NETWORKS, base, date, stamp

WINDOW_SECONDS = 300
REFRESH_SECONDS = 10
PAIR_LIMIT = 2000
GEO_LIMIT = 4096

class LiveGlobe:
    def __init__(self, client, geo):
        self.client, self.geo = client, geo
        self.lock = threading.Lock()
        self.cached = None
        self.expires = 0
        self.geo_cache = collections.OrderedDict()
        self.last_observed = None

    def snapshot(self, now=None):
        # A single cache entry, including failures: requests cannot select a
        # time/cursor/window and create unbounded cache keys or retry storms.
        with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return copy.deepcopy(self.cached)
            end = now or datetime.now(timezone.utc)
            start = end - timedelta(seconds=WINDOW_SECONDS)
            out = {'mode': 'live', 'as_of': stamp(end),
                   'window': {'start': stamp(start), 'end': stamp(end),
                              'seconds': WINDOW_SECONDS, 'label': 'Last 5 minutes'},
                   'refresh_seconds': REFRESH_SECONDS, 'state': 'unavailable',
                   'observed_at': self.last_observed, 'endpoints': None,
                   'countries': [], 'locations': [], 'geo': self.geo.status(),
                   'note': 'Router NetFlow public endpoints, by flow-end time. Exports can arrive minutes late; older exports outside this window are absent. Fresh observations do not prove collector health. Arcs show approximate relationships, not packets or routes.'}
            try:
                query = base('opnsense-flow', start, end, 'schema:=2 remote_ip:=192.168.5.1')
                # max is idempotent across at-least-once receipts. No byte/flow
                # totals are claimed here; duplicate rows cannot animate twice.
                rows = self.client.query(query + ' | stats by (src_addr,dst_addr) max(_time) last_seen | limit 2001', time.monotonic() + 5)
                if len(rows) > PAIR_LIMIT:
                    out['state'] = 'partial'
                    out['note'] = 'Recent endpoint pairs exceed the 2,000-pair bound. Globe locations and counts are withheld; historical summaries remain separate.'
                else:
                    ips = {}; latest = None
                    for row in rows:
                        when = date(row['last_seen'])
                        if not start <= when < end:
                            raise ValueError('Invalid flow timestamp')
                        latest = max(latest, when) if latest else when
                        for field in ('src_addr', 'dst_addr'):
                            ip = str(ipaddress.ip_address(row[field]))
                            if public_endpoint(ip, NETWORKS):
                                ips[ip] = max(ips.get(ip, when), when)
                    if latest:
                        self.last_observed = stamp(latest)
                        out['observed_at'] = self.last_observed
                        out['state'] = 'fresh' if (end-latest).total_seconds() <= 90 else 'stale'
                        out['endpoints'] = len(ips)
                        endpoints={}
                        for ip,when in ips.items():
                            if ip not in self.geo_cache:
                                self.geo_cache[ip]=self.geo.lookup(ip)
                                if len(self.geo_cache)>GEO_LIMIT:self.geo_cache.popitem(last=False)
                            self.geo_cache.move_to_end(ip)
                            endpoints[ip]=(self.geo_cache[ip],stamp(when))
                        out['countries'],out['locations']=aggregate(endpoints,near_live=True)
                    else:
                        out['note'] = 'No router flow records observed in the last five minutes. Traffic and collection coverage are unknown. The previous observation timestamp, when known, is preserved.'
            except Exception:
                out['state'] = 'unavailable'
                out['note'] = 'Recent router observations could not be validated within the query budget. Traffic and collection coverage are unknown.'
            self.cached = out
            self.expires = time.monotonic() + REFRESH_SECONDS
            return copy.deepcopy(out)
