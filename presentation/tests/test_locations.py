import json,math,unittest
from datetime import datetime,timedelta,timezone
from backend.locations import aggregate,MAX_AREAS
from backend.service import Geography,stamp
from backend.live_globe import LiveGlobe
from backend.models import Overview,GlobeSnapshot
from backend.demo import demo
from test_live_globe import Queries,row,END

def loc(region='California',city='Mountain View',lat=37.4225,lon=-122.085,code='US',**kw):return {'code':code,'name':'United States' if code=='US' else code,'region':region,'city':city,'latitude':lat,'longitude':lon,**kw}
class Areas(unittest.TestCase):
 def test_US_domestic_spread_country_count_and_no_country_point(self):
  countries,areas=aggregate({'west':(loc(),None),'east':(loc('Virginia','Ashburn',39.0438,-77.4874),None)})
  self.assertEqual(len(countries),1);self.assertEqual(countries[0]['count'],2);self.assertIsNone(countries[0]['latitude']);self.assertEqual(len(areas),2);self.assertGreater(abs(areas[0]['longitude']-areas[1]['longitude']),40)
 def test_quantized_center_and_same_cell_merge(self):
  countries,a=aggregate({'one':(loc(),None),'two':(loc(city='Cupertino',lat=37.3322,lon=-122.011),None)})
  self.assertEqual(len(a),1);self.assertEqual(a[0]['count'],2);self.assertEqual(a[0]['latitude'],37.25);self.assertEqual(a[0]['longitude'],-122.25);self.assertEqual(set(a[0]['cities']),{'Cupertino','Mountain View'})
 def test_identity_independent_of_endpoint_order_count_and_time(self):
  one={'one':(loc(),stamp(END)),'two':(loc(),stamp(END-timedelta(seconds=1)))}
  c,a=aggregate(one,True);c,b=aggregate(dict(reversed(list(one.items()))),True);self.assertEqual(a,b)
  c,b=aggregate({'different':(loc(),stamp(END+timedelta(seconds=1)))},True);self.assertEqual(a[0]['id'],b[0]['id']);self.assertNotEqual(a[0]['activity_id'],b[0]['activity_id'])
 def test_country_and_unknown_positions_never_fabricated(self):
  c,a=aggregate({'one':({'code':'US','name':'United States','latitude':37.751,'longitude':-97.822},None),'two':(None,None)})
  self.assertEqual(sum(x['count'] for x in a),2);self.assertEqual({x['precision'] for x in a},{'country','unknown'});self.assertTrue(all(x['latitude'] is None and x['longitude'] is None for x in a))
 def test_invalid_coordinates_and_bool_are_unplaced(self):
  for lat,lon in [(float('nan'),0),(1,float('inf')),(91,1),(1,181),(True,1),(1,False)]:
   c,a=aggregate({'one':(loc(lat=lat,lon=lon),None)});self.assertEqual(a[0]['precision'],'country');self.assertIsNone(a[0]['latitude'])
 def test_poles_and_date_line_stay_within_grid(self):
  c,a=aggregate({'one':(loc(lat=90,lon=180),None),'two':(loc(lat=-90,lon=-180),None)})
  self.assertEqual(len(a),2);self.assertTrue(all(-90<x['latitude']<90 and -180<x['longitude']<180 for x in a))
 def test_geographical_bound_preserves_every_endpoint(self):
  data={str(i):(loc(lat=-50+i*.5,lon=-120),None) for i in range(130)}
  c,a=aggregate(data);mapped=[x for x in a if x['precision']=='area'];overflow=[x for x in a if x['precision']=='overflow']
  self.assertEqual(len(mapped),MAX_AREAS);self.assertEqual(sum(x['count'] for x in a),130);self.assertEqual(c[0]['count'],130);self.assertEqual(overflow[0]['count'],34);self.assertIsNone(overflow[0]['longitude'])
  c,b=aggregate(dict(reversed(list(data.items()))));self.assertEqual(a,b)
 def test_bound_not_ranked_by_changing_counts(self):
  data={str(i):(loc(lat=-50+i*.5,lon=-120),None) for i in range(130)}
  _,a=aggregate(data);data.update({f'copy{i}':(loc(lat=-50,lon=-120),None) for i in range(100)})
  _,b=aggregate(data);self.assertEqual({x['id'] for x in a if x['precision']=='area'},{x['id'] for x in b if x['precision']=='area'})
 def test_count_and_time_buckets_conserve_duplicates_and_old_observations(self):
  t=stamp(END);old=stamp(END-timedelta(seconds=200));c,a=aggregate({'one':(loc(),t),'two':(loc(),old),'three':(loc(),old)},True)
  self.assertEqual(sum(b['count'] for b in a[0]['age_buckets']),3);self.assertEqual(a[0]['last_seen'],t);self.assertEqual(c[0]['last_seen'],t)
 def test_overflow_preserves_buckets_for_expiry(self):
  c,a=aggregate({str(i):(loc(lat=-50+i*.5),stamp(END-timedelta(seconds=i))) for i in range(130)},True)
  self.assertEqual(sum(b['count'] for x in a for b in x['age_buckets']),130)
 def test_no_endpoint_keys_in_payload(self):
  c,a=aggregate({'8.8.8.8':(loc(),None)});self.assertNotIn('8.8.8.8',json.dumps({'countries':c,'locations':a}))
 def test_radius_metadata_not_invented_or_assumed(self):
  _,a=aggregate({'one':(loc(accuracy_radius_km=20),None),'two':(loc(),None)});self.assertEqual(a[0]['radius_known_count'],1);self.assertIsNone(a[0]['accuracy_radius_km'])
  _,a=aggregate({'one':(loc(accuracy_radius_km=20),None)});self.assertEqual(a[0]['accuracy_radius_km'],20)
  for value in [-1,True,float('inf'),'50']:
   _,a=aggregate({'one':(loc(accuracy_radius_km=value),None)});self.assertIsNone(a[0]['accuracy_radius_km'])
 def test_city_labels_are_bounded_and_counts_unchanged(self):
  _,a=aggregate({str(i):(loc(city='City'+str(i)),None) for i in range(20)});self.assertEqual(len(a[0]['cities']),3);self.assertEqual(a[0]['other_city_labels'],17);self.assertEqual(a[0]['count'],20)
 def test_geo_lookup_retains_existing_city_region_without_claiming_radius(self):
  class Reader:
   def get(self,ip):return {'country':{'iso_code':'US','names':{'en':'United States'}},'city':{'names':{'en':'Mountain View'}},'subdivisions':[{'names':{'en':'California'}}],'location':{'latitude':37.42,'longitude':-122.08}}
  g=Geography.__new__(Geography);g.reader=Reader();a=g.lookup('8.8.8.8');self.assertEqual(a['city'],'Mountain View');self.assertEqual(a['region'],'California');self.assertIsNone(a['accuracy_radius_km'])
 def test_live_cache_ordering_counts_and_public_filter(self):
  class Geo:
   def lookup(self,ip):return loc() if ip=='8.8.8.8' else loc('Virginia','Ashburn',39.04,-77.48)
   def status(self):return {'available':True,'provider':'fixture','age_days':40}
  q=Queries([row(),row(),row('1.1.1.1'),row('10.0.0.1')]);l=LiveGlobe(q,Geo());v=l.snapshot(END);GlobeSnapshot.model_validate(v);self.assertEqual(v['endpoints'],2);self.assertEqual(sum(x['count'] for x in v['locations']),2);self.assertEqual(len(v['locations']),2)
  self.assertEqual(v,l.snapshot(END));q.rows=list(reversed(q.rows));l.expires=0;self.assertEqual(v['locations'],l.snapshot(END)['locations'])
 def test_live_partial_empty_failure_and_stale_remain_truthful(self):
  class Geo:
   def lookup(self,ip):return loc()
   def status(self):return {'available':True,'provider':'fixture','age_days':40}
  q=Queries([row(seconds=120)]);l=LiveGlobe(q,Geo());v=l.snapshot(END);self.assertEqual(v['state'],'stale');self.assertEqual(sum(x['count'] for x in v['locations']),1)
  for records,state in [([],'unavailable'),([row()]*2001,'partial')]:
   q.rows=records;l.expires=0;v=l.snapshot(END);self.assertEqual(v['state'],state);self.assertEqual(v['locations'],[]);self.assertIsNone(v['endpoints'])
  q.error=True;l.expires=0;v=l.snapshot(END);self.assertEqual(v['locations'],[]);self.assertNotIn('secret',json.dumps(v))
 def test_demo_summary_and_near_live_schema_and_totals(self):
  for state in ['normal','stale','unavailable']:
   v=demo(END,3600,state);Overview.model_validate(v);self.assertEqual(sum(c['count'] for c in v['countries']),sum(a['count'] for a in v['locations']));self.assertTrue(all(c['latitude'] is None for c in v['countries']))
