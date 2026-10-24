import copy
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from backend.live_globe import LiveGlobe, GEO_LIMIT
from backend.models import GlobeSnapshot
from fastapi.testclient import TestClient
from backend.app import app
from backend.service import stamp

END=datetime(2026,10,6,1,tzinfo=timezone.utc)
def row(ip='8.8.8.8',seconds=5,src='192.168.5.230'):
    return {'src_addr':src,'dst_addr':ip,'last_seen':stamp(END-timedelta(seconds=seconds))}
class Queries:
    def __init__(self,rows):self.rows=rows;self.calls=[];self.error=False
    def query(self,q,deadline):
        self.calls.append(q)
        if self.error:raise RuntimeError('secret upstream detail')
        return copy.deepcopy(self.rows)
class Geography:
    def __init__(self):self.calls=[]
    def lookup(self,ip):
        self.calls.append(ip)
        return {'code':'US','name':'United States','latitude':39.,'longitude':-98.} if ip=='8.8.8.8' else None
    def status(self):return {'available':True,'provider':'test','age_days':0}
class LiveTests(unittest.TestCase):
    def build(self,rows):
        self.q=Queries(rows);self.geo=Geography();self.live=LiveGlobe(self.q,self.geo)
        return self.live.snapshot(END)
    def refresh(self,seconds=10):
        self.live.expires=0;return self.live.snapshot(END+timedelta(seconds=seconds))
    def test_source_gate_bounded_timestamp_and_schema(self):
        v=self.build([row()]);GlobeSnapshot.model_validate(v)
        self.assertEqual(v['state'],'fresh');self.assertEqual(v['endpoints'],1)
        q=self.q.calls[0]
        for value in ['app_name:=opnsense-flow','remote_ip:=192.168.5.1','schema:=2','max(_time) last_seen','limit 2001',stamp(END-timedelta(seconds=300)),stamp(END)]:self.assertIn(value,q)
        self.assertNotIn('tshark',q);self.assertNotIn('bytes',v)
    def test_duplicate_pairs_and_public_filter_and_unknown_denominator(self):
        v=self.build([row(),row(),row('1.1.1.1'),row('239.1.1.1'),row('10.0.0.1'),row('::ffff:10.0.0.1'),row('2001:db8::1')])
        self.assertEqual(v['endpoints'],2)
        self.assertEqual(sum(c['count'] for c in v['countries']),2)
        self.assertEqual(next(c for c in v['countries'] if c['code']=='??')['percent'],50)
    def test_no_replay_from_duplicate_receipts_or_older_late_exports(self):
        first=self.build([row()]);self.q.rows=[row(),row(seconds=40),row()]
        second=self.refresh();self.assertEqual(first['countries'],second['countries'])
        self.assertEqual(len(self.geo.calls),1)
        self.q.rows=[row(seconds=-3)];third=self.refresh(20)
        self.assertNotEqual(first['countries'][0]['activity_id'],third['countries'][0]['activity_id'])
    def test_fractional_country_timestamp_is_ordered_as_time(self):
        class SameCountry(Geography):
            def lookup(self,ip):return {'code':'US','name':'United States','latitude':39.,'longitude':-98.}
        whole=END-timedelta(seconds=5)
        fraction=whole+timedelta(microseconds=900000)
        expected_id=None
        for reverse_ips in (False,True):
            ips=('8.8.8.8','1.1.1.1') if reverse_ips else ('1.1.1.1','8.8.8.8')
            records=[{**row(ips[0]),'last_seen':whole.astimezone(timezone(timedelta(hours=1))).isoformat()},
                     {**row(ips[1]),'last_seen':fraction.astimezone(timezone(timedelta(hours=-5))).isoformat()}]
            live=LiveGlobe(Queries(records),SameCountry())
            v=live.snapshot(END)
            self.assertEqual(v['observed_at'],stamp(fraction))
            self.assertEqual(v['countries'][0]['last_seen'],stamp(fraction))
            if expected_id is not None:self.assertEqual(v['countries'][0]['activity_id'],expected_id)
            expected_id=v['countries'][0]['activity_id']
            # Both row orders, both endpoint sort orders, timezone normalization,
            # and whole/fractional representations have the same newest time.
            live.client.rows=list(reversed(records));live.expires=0
            self.assertEqual(live.snapshot(END)['countries'],v['countries'])
    def test_new_endpoint_from_late_export_inside_window_is_included(self):
        self.build([row()]);self.q.rows=[row(),row('1.1.1.1',seconds=250)]
        v=self.refresh();self.assertEqual(v['endpoints'],2)
        self.assertIn('minutes late',v['note'])
    def test_empty_and_failure_retain_prior_timestamp_never_zero(self):
        first=self.build([row()]);self.q.rows=[]
        empty=self.refresh();self.assertEqual(empty['observed_at'],first['observed_at']);self.assertEqual(empty['state'],'unavailable');self.assertIsNone(empty['endpoints']);self.assertEqual(empty['countries'],[])
        self.q.error=True;failed=self.refresh(20);self.assertEqual(failed['state'],'unavailable');self.assertNotIn('secret',str(failed));self.assertIsNone(failed['endpoints'])
    def test_no_prior_history_is_explicit_unknown(self):
        v=self.build([]);self.assertIsNone(v['observed_at']);self.assertIsNone(v['endpoints']);self.assertEqual(v['state'],'unavailable')
    def test_old_record_is_stale_and_age_not_receipt_time(self):
        v=self.build([row(seconds=120)]);self.assertEqual(v['state'],'stale');self.assertEqual(v['observed_at'],stamp(END-timedelta(seconds=120)))
    def test_pair_bound_withholds_locations_and_counts(self):
        v=self.build([row()]*2001);self.assertEqual(v['state'],'partial');self.assertEqual(v['countries'],[]);self.assertIsNone(v['endpoints']);self.assertEqual(self.geo.calls,[])
    def test_invalid_time_or_addresses_withhold(self):
        for bad in [row(seconds=-1),row(seconds=301),{**row(),'dst_addr':'bad'},{**row(),'last_seen':'bad'}]:
            v=self.build([bad]);self.assertEqual(v['state'],'unavailable');self.assertEqual(v['countries'],[])
    def test_global_cache_defensive_copy_and_failure_backoff(self):
        v=self.build([row()]);v['countries'].clear();cached=self.live.snapshot(END+timedelta(seconds=1));self.assertEqual(len(cached['countries']),1);self.assertEqual(len(self.q.calls),1)
        self.q.error=True;self.refresh();self.live.snapshot();self.live.snapshot();self.assertEqual(len(self.q.calls),2)
    def test_concurrent_viewers_share_one_query(self):
        q=Queries([row()]);original=q.query
        def delayed(*a):time.sleep(.025);return original(*a)
        q.query=delayed;l=LiveGlobe(q,Geography())
        with ThreadPoolExecutor(max_workers=8) as pool:values=list(pool.map(lambda _:l.snapshot(END),range(8)))
        self.assertEqual(len(q.calls),1);self.assertTrue(all(v==values[0] for v in values))
    def test_geo_cache_is_bounded(self):
        self.build([row()]);self.live.geo_cache.update({f'cached:{i}':None for i in range(GEO_LIMIT-1)})
        self.q.rows=[row('1.1.1.1')];self.refresh();self.assertEqual(len(self.live.geo_cache),GEO_LIMIT)

class GlobeHTTP(unittest.TestCase):
    def test_demo_states_and_security_headers(self):
        client=TestClient(app)
        for state in ('normal','stale','unavailable'):
            r=client.get('/api/globe',params={'scenario':state})
            self.assertEqual(r.status_code,200);GlobeSnapshot.model_validate(r.json())
            self.assertEqual(r.json()['mode'],'demo')
            self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertEqual(client.get('/api/globe?scenario=error').status_code,503)
        self.assertEqual(client.get('/api/globe?scenario=invalid').status_code,422)
        self.assertEqual(client.post('/api/globe').status_code,405)
