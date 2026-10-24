import copy,json,sys,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app
from backend.demo import demo
from backend.models import Overview
from backend.service import Service,capture_rows,capture_intervals,number,stamp
UTC=timezone.utc;END=datetime(2026,10,5,1,30,tzinfo=UTC)
SNAP={'observed_at':stamp(END-timedelta(seconds=30)),'partial':False,'devices':[{'id':'ap1','mac':'28:70:4e:5b:0e:ab','name':'Kitchen'}],'clients':[{'id':'client1','name':'Test device','ip':'192.168.5.145','type':'WIRELESS','uplink_id':'ap1'}]}
def cap(kind='connections',eid='boot:1',at=None,**extra):
 if kind=='health':extra={'packets_total':21,'frame_bytes_total':2200,'interval_packets':21,'interval_frame_bytes':2200,'flow_capacity_overflow_packets':0,'invalid_lines':0,'queue_drops':0,'delivery_errors':0,**extra}
 return {'_time':stamp(at or END-timedelta(seconds=40)),'_msg':json.dumps({'schema':1,'kind':kind,'event_id':eid,'interval_seconds':60,**extra})}
FLOW={'src':'192.168.5.145','dst':'192.168.5.238','protocol':'17','src_port':'54984','dst_port':'53','vlan':'','packets':21,'frame_bytes':2200}
def zero_health(at,eid):return cap('health',eid,at=at,packets_total=0,frame_bytes_total=0,interval_packets=0,interval_frame_bytes=0)
# Anonymized structural fixtures match inspected real source schemas.
class MemoryQueries:
 def __init__(self):self.queries=[];self.fail=set();self.partial=False;self.malformed=False
 def query(self,q,deadline):
  self.queries.append(q)
  if any(src in q for src in self.fail):raise RuntimeError('private upstream failure must not leak')
  if 'unifi-snapshot' in q:
   snap=copy.deepcopy(SNAP);snap['partial']=self.partial;return [{'snapshot_json':json.dumps(snap),'_time':snap['observed_at']}]
  if 'opnsense-flow' in q:
   if 'fields _time' in q:return [{'_time':stamp(END-timedelta(seconds=20))}]
   if 'stats by (_time)' in q:return [{'_time':stamp(END-timedelta(minutes=5)),'bytes':'1000'}]
   if 'stats by (src_addr,dst_addr)' in q:return [{'src_addr':'192.168.5.1','dst_addr':'8.8.8.8','bytes':'600'},{'src_addr':'192.168.5.1','dst_addr':'1.1.1.1','bytes':'400'}]
   return [{'bytes':'1000','records':'2'}]
  if 'pihole-dns' in q:
   if 'fields _time' in q:return [{'_time':stamp(END-timedelta(seconds=90))}]
   return [{'outcome':'blocked','queries':'2'},{'outcome':'cached','queries':'3'}]
  if 'pihole-snapshot' in q:return [{'_time':stamp(END-timedelta(seconds=30)),'snapshot_json':'{}'}]
  if 'tshark-summary' in q:
   r=cap(eid='boot:3',flows=[FLOW]);rows=[zero_health(END-timedelta(seconds=160),'boot:1'),zero_health(END-timedelta(seconds=100),'boot:2'),r,r,cap('health','boot:4',packets_total=21,kernel_capture_drops='not_measured')]
   return rows+[{'_time':stamp(END),'_msg':'broken'}] if self.malformed else rows
  if 'filterlog' in q:return []
  raise AssertionError(q)
class Geo:
 def lookup(self,ip):return {'code':'US','name':'United States','latitude':39.8,'longitude':-98.6} if ip=='8.8.8.8' else None
 def status(self):return {'available':True,'provider':'Test database','age_days':0}
class RouterObservations(MemoryQueries):
 def __init__(self,last_seen=None,has_window_records=False):
  super().__init__();self.last_seen=last_seen;self.has_window_records=has_window_records
 def query(self,q,deadline):
  if 'opnsense-flow' not in q:return super().query(q,deadline)
  self.queries.append(q)
  if 'fields _time' in q:
   fallback=stamp(END-timedelta(days=30)) in q
   if self.last_seen and fallback==(self.last_seen<=END-timedelta(minutes=30)):return [{'_time':stamp(self.last_seen)}]
   return []
  if self.has_window_records:
   # Use the normal received-record fixture, independently of current freshness.
   return super().query(q,deadline)
  return [{'bytes':'0','records':'0'}] if 'count() records' in q else []
class Contracts(unittest.TestCase):
 def test_capture_dedup_and_premirror_exclusion(self):
  r=cap(flows=[FLOW]);old=cap(eid='old',at=datetime(2026,10,5,1,26,44,tzinfo=UTC),flows=[FLOW]);f,h,bad=capture_rows([r,r,old],END-timedelta(hours=1),END)
  self.assertEqual(sum(x['frame_bytes'] for t,x in f),2200);self.assertEqual(bad,0)
 def test_source_separation_and_unknown_geography_denominator(self):
  c=MemoryQueries();v=Service(c,Geo()).overview(END,3600)
  for key,num in [('router_bytes',1000),('capture_bytes',2200),('dns_queries',5),('dns_blocked',2),('destinations',2)]:self.assertEqual(v['metrics'][key],num)
  self.assertEqual(v['metrics']['busiest']['name'],'Test device');self.assertEqual(sum(x['percent'] for x in v['countries']),100)
  self.assertEqual(next(x for x in v['countries'] if x['code']=='??')['percent'],50)
  self.assertTrue(all('2026-10-05T01:30:00Z)' in q for q in c.queries))
  self.assertTrue(any('schema:=2' in q and 'max(bytes)' in q for q in c.queries))
 def test_cache_and_deterministic_window(self):
  c=MemoryQueries();s=Service(c,Geo());a=s.overview(END,3600);n=len(c.queries);b=s.overview(END,3600)
  self.assertEqual(a,b);self.assertEqual(len(c.queries),n);b['metrics']['router_bytes']=0;self.assertEqual(s.overview(END,3600)['metrics']['router_bytes'],1000)
 def test_public_destinations_exclude_ipv4_and_ipv6_special_ranges(self):
  excluded=['239.255.255.250','224.0.0.1','255.255.255.255','0.0.0.0','127.0.0.1','10.0.0.1','172.16.0.1','192.168.5.145','169.254.1.1','100.64.0.1','192.0.2.1','198.18.0.1','198.51.100.1','203.0.113.1','240.0.0.1','ff02::1','ff0e::1','::','::1','fe80::1','fc00::1','2001:db8::1','::ffff:10.0.0.1']
  class SpecialEndpoints(MemoryQueries):
   def query(self,q,deadline):
    if 'opnsense-flow' in q and 'stats by (src_addr,dst_addr)' in q:return [{'src_addr':'192.168.5.1','dst_addr':ip,'bytes':'1'} for ip in excluded+['8.8.8.8','1.1.1.1','2001:4860:4860::8888']]
    return super().query(q,deadline)
  v=Service(SpecialEndpoints(),Geo()).overview(END,900)
  self.assertEqual(v['metrics']['destinations'],3)
  self.assertEqual(sum(c['count'] for c in v['countries']),3)
  self.assertEqual(next(c for c in v['countries'] if c['code']=='??')['percent'],66.67)
 def test_partial_and_malformed_withhold_metrics(self):
  c=MemoryQueries();c.partial=True;c.malformed=True;v=Service(c,Geo()).overview(END,3600)
  self.assertIsNone(v['metrics']['devices']);self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['busiest']);self.assertEqual(v['metrics']['attention'],2)
 def test_outage_is_not_zero_or_demo(self):
  c=MemoryQueries();c.fail={'opnsense-flow'};v=Service(c,Geo()).overview(END,3600)
  self.assertIsNone(v['metrics']['router_bytes']);self.assertIsNone(v['metrics']['destinations']);self.assertEqual(v['mode'],'live');self.assertNotIn('private upstream failure',json.dumps(v))
 def test_stopped_exporter_beyond_recent_lookback(self):
  last=END-timedelta(minutes=45);c=RouterObservations(last);v=Service(c,Geo()).overview(END,900)
  router=next(s for s in v['sources'] if s['id']=='router')
  self.assertEqual(router['state'],'stale');self.assertEqual(router['observed_at'],stamp(last))
  self.assertIsNone(v['metrics']['router_bytes']);self.assertIsNone(v['metrics']['destinations'])
  self.assertEqual(v['metrics']['attention'],1);self.assertEqual(v['countries'],[])
  queries=[q for q in c.queries if 'opnsense-flow' in q]
  self.assertTrue(all('remote_ip:=192.168.5.1' in q for q in queries))
  self.assertTrue(any(stamp(END-timedelta(days=30)) in q for q in queries))
 def test_empty_selected_window_retains_recent_prior_observation(self):
  last=END-timedelta(minutes=20);c=RouterObservations(last);v=Service(c,Geo()).overview(END,900)
  router=next(s for s in v['sources'] if s['id']=='router')
  self.assertEqual(router['observed_at'],stamp(last));self.assertEqual(router['state'],'stale')
  self.assertIsNone(v['metrics']['router_bytes']);self.assertIsNone(v['metrics']['destinations'])
  self.assertIn('coverage are unknown',router['note'])
  self.assertFalse(any(stamp(END-timedelta(days=30)) in q for q in c.queries))
 def test_empty_router_with_no_history_is_unknown_not_quiet(self):
  v=Service(RouterObservations(),Geo()).overview(END,900)
  router=next(s for s in v['sources'] if s['id']=='router')
  self.assertEqual(router['state'],'unavailable');self.assertIsNone(router['observed_at'])
  self.assertIsNone(v['metrics']['router_bytes']);self.assertIsNone(v['metrics']['destinations']);self.assertEqual(v['metrics']['attention'],1)
 def test_recent_observation_cannot_certify_empty_window(self):
  v=Service(RouterObservations(END-timedelta(minutes=5)),Geo()).overview(END,900)
  self.assertEqual(next(s for s in v['sources'] if s['id']=='router')['state'],'unavailable')
  self.assertIsNone(v['metrics']['router_bytes']);self.assertEqual(v['metrics']['attention'],1)
 def test_historical_received_totals_survive_stopped_exporter(self):
  last=END-timedelta(minutes=45);v=Service(RouterObservations(last,True),Geo()).overview(END,3600)
  self.assertEqual(v['metrics']['router_bytes'],1000);self.assertEqual(v['metrics']['destinations'],2)
  router=next(s for s in v['sources'] if s['id']=='router')
  self.assertEqual(router['observed_at'],stamp(last));self.assertEqual(router['state'],'stale');self.assertEqual(v['metrics']['attention'],1)
 def test_independently_observed_capture_health_supports_quiet_zero(self):
  class QuietCapture(MemoryQueries):
   def query(self,q,deadline):
    if 'tshark-summary' in q:return [zero_health(END-timedelta(seconds=age),'boot:'+str(i)) for i,age in enumerate([160,100,40],1)]
    return super().query(q,deadline)
  v=Service(QuietCapture(),Geo()).overview(END,900)
  self.assertEqual(v['metrics']['capture_bytes'],0);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'fresh')
  self.assertIsNone(v['metrics']['busiest']);self.assertEqual(v['metrics']['attention'],0)
 def test_all_sources_outage_withholds_measurements(self):
  c=MemoryQueries();c.fail={'unifi-snapshot','opnsense-flow','pihole-dns','tshark-summary','filterlog'}
  v=Service(c,Geo()).overview(END,900)
  self.assertEqual(v['metrics']['attention'],5);self.assertTrue(all(s['state']=='unavailable' for s in v['sources']))
  self.assertTrue(all(value is None for key,value in v['metrics'].items() if key!='attention'))
 def test_successful_empty_sources_are_not_healthy_aggregate(self):
  class EmptyQueries:
   def query(self,q,deadline):return []
  v=Service(EmptyQueries(),Geo()).overview(END,900)
  self.assertEqual(v['metrics']['attention'],4);self.assertIsNone(v['metrics']['router_bytes']);self.assertIsNone(v['metrics']['destinations'])
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['dns_queries']);self.assertIsNone(v['metrics']['devices'])
 def capture_result(self,rows,end=END):
  class CaptureQueries(MemoryQueries):
   def query(self,q,deadline):
    if 'tshark-summary' in q:return rows
    return super().query(q,deadline)
  return Service(CaptureQueries(),Geo()).overview(end,900)
 def test_invalid_health_cannot_leave_published_capture_total(self):
  for counter in ('packets_total','frame_bytes_total','interval_packets','interval_frame_bytes','flow_capacity_overflow_packets','invalid_lines','queue_drops','delivery_errors'):
   with self.subTest(counter=counter):
    v=self.capture_result([cap(flows=[FLOW]),cap('health','boot:2',**{counter:-1})])
    self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['busiest'])
    self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'partial');self.assertEqual(v['metrics']['attention'],1)
 def test_earlier_boot_losses_survive_clean_restart(self):
  t=END-timedelta(seconds=100)
  rows=[zero_health(END-timedelta(seconds=160),'prefix:1'),cap(eid='oldboot:1',at=t,flows=[FLOW]),cap('health','oldboot:2',at=t,queue_drops=9),cap(eid='newboot:1',flows=[FLOW]),cap('health','newboot:2')]
  v=self.capture_result(rows)
  self.assertEqual(v['metrics']['capture_bytes'],4400);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'partial')
  self.assertEqual(v['metrics']['attention'],1);self.assertTrue(any('earlier boots' in s for s in v['issues']));self.assertIsNone(v['metrics']['busiest'])
 def test_batches_reconcile_by_sequence_despite_timestamp_jitter(self):
  t=END-timedelta(seconds=40)
  rows=[zero_health(END-timedelta(seconds=160),'prefix:1'),zero_health(END-timedelta(seconds=100),'prefix:2'),cap(eid='boot:1',at=t,flows=[FLOW]),cap(eid='boot:2',at=t+timedelta(milliseconds=1),flows=[FLOW]),cap('health','boot:3',at=t+timedelta(milliseconds=2),packets_total=42,frame_bytes_total=4400,interval_packets=42,interval_frame_bytes=4400)]
  v=self.capture_result(rows+[rows[0],rows[-1]])
  self.assertEqual(v['metrics']['capture_bytes'],4400);self.assertEqual(v['metrics']['attention'],0)
 def test_missing_connection_batch_withholds_interval_total(self):
  rows=[cap(flows=[FLOW]),cap('health','boot:3',packets_total=42,frame_bytes_total=4400,interval_packets=42,interval_frame_bytes=4400)]
  v=self.capture_result(rows)
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['busiest']);self.assertEqual(v['metrics']['attention'],1)
 def test_missing_health_emission_detected_by_cumulative_counters(self):
  t=END-timedelta(seconds=100)
  rows=[cap(eid='boot:1',at=t,flows=[FLOW]),cap('health','boot:2',at=t),cap(eid='boot:5',flows=[FLOW]),cap('health','boot:6',packets_total=63,frame_bytes_total=6600)]
  v=self.capture_result(rows)
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertEqual(v['metrics']['attention'],1)
 def test_cumulative_error_counts_are_not_added_as_interval_counts(self):
  t=END-timedelta(seconds=100)
  rows=[zero_health(END-timedelta(seconds=160),'prefix:1'),cap(eid='boot:1',at=t,flows=[FLOW]),cap('health','boot:2',at=t,queue_drops=9),cap(eid='boot:3',flows=[FLOW]),cap('health','boot:4',packets_total=42,frame_bytes_total=4400,queue_drops=9)]
  v=self.capture_result(rows)
  self.assertEqual(v['metrics']['capture_bytes'],4400);self.assertEqual(v['metrics']['attention'],1)
  self.assertEqual(sum('cumulative application' in s for s in v['issues']),1)
 def test_counter_reset_without_boot_change_withholds_total(self):
  t=END-timedelta(seconds=100)
  rows=[cap(eid='boot:1',at=t,flows=[FLOW]),cap('health','boot:2',at=t,queue_drops=9),cap(eid='boot:3',flows=[FLOW]),cap('health','boot:4')]
  v=self.capture_result(rows)
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['busiest']);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'unavailable')
 def test_connection_batch_without_health_cannot_certify_total(self):
  v=self.capture_result([cap(flows=[FLOW])])
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertEqual(v['metrics']['attention'],1)
 def test_capture_complete_window_has_zero_without_false_alert(self):
  end=datetime(2026,10,5,2,15,tzinfo=UTC);start=end-timedelta(minutes=15)
  rows=[zero_health(start+timedelta(seconds=20+i*60),'full:'+str(i+1)) for i in range(15)]
  v=self.capture_result(rows,end)
  self.assertEqual(v['metrics']['capture_bytes'],0);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'fresh')
 def test_capture_missing_first_interval_is_partial(self):
  end=datetime(2026,10,5,2,15,tzinfo=UTC);start=end-timedelta(minutes=15)
  for offset in [0,20]:
   with self.subTest(phase=offset):
    rows=[zero_health(start+timedelta(seconds=offset+i*60),'full:'+str(i+1)) for i in range(1,15)]
    v=self.capture_result(rows,end)
    self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['busiest']);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'partial');self.assertGreater(v['metrics']['attention'],0)
 def test_capture_missing_last_interval_is_partial(self):
  end=datetime(2026,10,5,2,15,tzinfo=UTC);start=end-timedelta(minutes=15)
  rows=[zero_health(start+timedelta(seconds=20+i*60),'full:'+str(i+1)) for i in range(14)]
  v=self.capture_result(rows,end)
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'partial')
 def test_capture_single_recent_heartbeat_cannot_certify_full_window(self):
  end=datetime(2026,10,5,2,15,tzinfo=UTC)
  for age in [40,150]:
   for zero in [True,False]:
    with self.subTest(age=age,zero=zero):
     t=end-timedelta(seconds=age)
     rows=[zero_health(t,'sparse:2')] if zero else [cap(eid='sparse:1',at=t,flows=[FLOW]),cap('health','sparse:2',at=t)]
     v=self.capture_result(rows,end)
     self.assertIsNone(v['metrics']['capture_bytes']);self.assertIsNone(v['metrics']['busiest']);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'partial');self.assertGreater(v['metrics']['attention'],0)
 def test_capture_activation_clips_effective_start(self):
  rows=[zero_health(datetime(2026,10,5,1,26,44,tzinfo=UTC),'pilot:1')]+[zero_health(datetime(2026,10,5,1,27+i,44,tzinfo=UTC),'activated:'+str(i+1)) for i in range(3)]
  v=self.capture_result(rows)
  self.assertEqual(v['metrics']['capture_bytes'],0);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'fresh')
  end=datetime(2026,10,5,1,27,0,tzinfo=UTC);v=self.capture_result(rows,end)
  self.assertIsNone(v['metrics']['capture_bytes']);self.assertEqual(next(s for s in v['sources'] if s['id']=='capture')['state'],'unavailable')
 def test_capture_late_arrival_has_bounded_current_window_tolerance(self):
  end=datetime(2026,10,5,2,15,tzinfo=UTC);start=end-timedelta(minutes=15)
  rows=[zero_health(start+timedelta(seconds=40+i*60),'settling:'+str(i+1)) for i in range(14)]
  flows,health,invalid=capture_rows(rows,start,end)
  self.assertEqual(capture_intervals(flows,health,start,end,end),(0,False,False))
  self.assertEqual(capture_intervals(flows,health,start,end,end+timedelta(seconds=10)),(0,False,False))
  self.assertEqual(capture_intervals(flows,health,start,end,end+timedelta(seconds=11)),(0,True,False))
  self.assertEqual(capture_intervals(flows,health,start,end,end+timedelta(minutes=5)),(0,True,False))
  self.assertIsNone(self.capture_result(rows,end)['metrics']['capture_bytes'])
 def test_counter_validation_and_bounds(self):
  for v in [-1,'NaN',True,1.5,2**64,float('inf')]:
   with self.assertRaises((ValueError,TypeError)):number(v)
  with self.assertRaises(Exception):capture_rows([{}]*10001,END-timedelta(hours=1),END)
 def test_historical_identity_not_invented(self):
  c=MemoryQueries();old=copy.deepcopy(SNAP);old['observed_at']=stamp(END-timedelta(minutes=10))
  with patch.dict(SNAP,old):v=Service(c,Geo()).overview(END,3600)
  self.assertIsNone(v['metrics']['busiest'])
 def test_demo_contracts(self):
  for s in ['normal','stale','unavailable']:Overview.model_validate(demo(END,3600,s))
class HTTPContract(unittest.TestCase):
 def setUp(self):self.client=TestClient(app)
 def test_read_only_and_no_generic_proxy(self):
  self.assertEqual(self.client.post('/api/overview',json={}).status_code,405);self.assertEqual(self.client.get('/api/query?query=*').status_code,404)
  self.assertEqual(self.client.get('/api/overview?window=90d').status_code,422);self.assertEqual(self.client.get('/api/overview?end=2026-10-05T01:30:00').status_code,422)
 def test_demo_is_explicit_error_not_fallback(self):
  r=self.client.get('/api/overview');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['mode'],'demo')
  self.assertEqual(self.client.get('/api/overview?scenario=error').status_code,503)
  self.assertIsNone(self.client.get('/api/overview?scenario=unavailable').json()['metrics']['router_bytes'])
 def test_security_headers(self):
  r=self.client.get('/api/overview');self.assertEqual(r.headers['cache-control'],'no-store');self.assertIn("connect-src 'self'",r.headers['content-security-policy'])
 def test_no_old_collectors(self):
  for name in ['backend.jev','backend.unifi','backend.pihole']:self.assertNotIn(name,sys.modules)
if __name__=='__main__':unittest.main()
