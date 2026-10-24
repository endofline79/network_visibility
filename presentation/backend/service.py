"""Bounded, source-separated read models. No collectors/checkpoints or write API."""
import collections,concurrent.futures,copy,ipaddress,json,os,threading,time,math
from .locations import aggregate,valid_coordinate
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .client import QueryClient,QueryError
from .filterlog import parse_filterlog,public_endpoint
from .models import Overview
UTC=timezone.utc
CAPTURE_INTERVAL=60
CAPTURE_SETTLING=30
CAPTURE_FIRST_COMPLETE=datetime(2026,10,5,1,27,20,tzinfo=UTC)
NETWORKS=tuple(ipaddress.ip_network(n) for n in ('192.168.5.0/24','10.10.10.0/24','10.10.20.0/24'))
COVERAGE=[
 'Router traffic: deduplicated NetFlow schema 2, IP-layer bytes, flow-end time bins. Recent totals are provisional; post-NAT uploads cannot be assigned reliably to clients.',
 'Kitchen capture: source port 1 → destination port 4, last verified 2026-10-05. Traffic staying inside an AP or on other paths may be absent. This app does not recheck switch configuration.',
 'Capture uses Ethernet frame bytes. Router and capture totals overlap and must not be added. A busy full-duplex source can oversubscribe its 2.5-Gbps mirror destination.',
 'Kitchen totals cover completed 60-second intervals by emission time; the current interval and up to 30 seconds of delivery settling are excluded. Startup emissions before 2026-10-05T01:27:20Z are excluded. Missing window boundaries withhold totals.',
 'Kernel capture drops are unmeasured. An hourly capture restart causes an approximately ten-second gap. Zero application drop counters do not prove complete capture.',
 'Raw capture labels still say flex-port7-pilot and mirror_enabled: unverified; the dated deployment record describes port 4. Pilot pre-mirror data is excluded from Kitchen totals.',
 'DNS includes only requests handled by Pi-hole and normally trails by one to two minutes. Firewall counts include only logged decisions.',
 'Inventory is a sampled observation. A missing device is not necessarily offline. The busiest Kitchen identity is shown only for recent, unambiguous snapshot correlations.',
 'Geography is approximate and uses local DB-IP data. Globe arcs represent relationships, not physical routes. Country percentages include unknown locations.',
 'Collector internals such as NetFlow decoder-error counters and a router collector heartbeat are not exposed by the current query API. Empty flow windows cannot prove zero traffic or healthy collection. Source freshness indicates recent observations, not full collector health.'
]
def stamp(d):return d.astimezone(UTC).isoformat().replace('+00:00','Z')
def date(s):return datetime.fromisoformat(str(s).replace('Z','+00:00')).astimezone(UTC)
def number(v):
    # VictoriaLogs returns scalar fields as strings. Refuse negative/nonintegral counters.
    if isinstance(v,bool):raise ValueError('Invalid counter')
    try:n=int(v)
    except OverflowError:raise ValueError('Invalid counter') from None
    if n<0 or n>2**63-1 or (isinstance(v,float) and not v.is_integer()):raise ValueError('Invalid counter')
    return n
def scalar(rows,key):return number(rows[0].get(key,0)) if rows else 0
def base(source,start,end,extra=''):
    return f'_time:[{stamp(start)},{stamp(end)}) app_name:={source}'+(' '+extra if extra else '')
def source(kind,title,observed,end,note,threshold=180,quiet=False):
    state='quiet' if not observed and quiet else 'unavailable' if not observed else 'stale' if (end-date(observed)).total_seconds()>threshold else 'fresh'
    return {'id':kind,'title':title,'observed_at':observed,'state':state,'note':note}
class Geography:
    def __init__(self,path=None):
        self.reader=None;self.age=None;self.build_utc=None
        try:
            import maxminddb
            self.reader=maxminddb.open_database(path or os.getenv('GEOIP_DATABASE','/geoip/dbip-city-lite.mmdb'))
            self.age=max(0,int((time.time()-self.reader.metadata().build_epoch)/86400));self.build_utc=stamp(datetime.fromtimestamp(self.reader.metadata().build_epoch,UTC))
        except Exception:pass
    def lookup(self,ip):
        if not self.reader:return None
        try:
            row=self.reader.get(ip) or {};country=row.get('country',{});loc=row.get('location',{})
            code=country.get('iso_code');lat=loc.get('latitude');lon=loc.get('longitude')
            if not code:return None
            if not valid_coordinate(lat,90) or not valid_coordinate(lon,180):lat=lon=None
            region=(row.get('subdivisions') or [{}])[0];city=row.get('city') or {};radius=loc.get('accuracy_radius')
            radius=radius if isinstance(radius,(int,float)) and not isinstance(radius,bool) and math.isfinite(radius) and radius>0 else None
            return {'code':str(code),'name':str(country.get('names',{}).get('en',code))[:100],'latitude':lat,'longitude':lon,'region':str(region.get('names',{}).get('en') or '')[:120] or None,'city':str(city.get('names',{}).get('en') or '')[:120] or None,'accuracy_radius_km':radius}
        except Exception:return None
    def status(self):return {'available':self.reader is not None,'provider':'DB-IP Lite','age_days':self.age,'build_utc':self.build_utc,'grid_degrees':.5,'max_mapped_areas':96,'uncertainty_note':'Approximate IP areas, not verified server locations. Provider accuracy may be unavailable; the grouping grid is not an accuracy boundary.'}

def capture_rows(rows,start,end):
    if len(rows)>10000:raise QueryError('Capture range too large; choose a shorter window')
    seen=set();flows=[];health=[];invalid=0
    for row in rows:
        try:
            t=date(row['_time']);m=json.loads(row['_msg']);eid=m['event_id']
            if not isinstance(eid,str) or m.get('schema')!=1:raise ValueError()
            if eid in seen:continue
            seen.add(eid)
            if m.get('kind') not in ('health','connections'):continue
            # Only completed post-activation intervals, never the pre-mirror broadcast pilot.
            if t<CAPTURE_FIRST_COMPLETE or not(start<=t<end):continue
            boot,sequence=eid.rsplit(':',1);sequence=number(sequence)
            if not boot or not sequence:raise ValueError()
            if m['kind']=='health':
                counters={k:number(m[k]) for k in ('packets_total','frame_bytes_total','interval_packets','interval_frame_bytes','flow_capacity_overflow_packets','invalid_lines','queue_drops','delivery_errors')}
                if counters['interval_packets']>counters['packets_total'] or counters['interval_frame_bytes']>counters['frame_bytes_total']:raise ValueError()
                health.append((t,{**m,**counters,'_boot':boot,'_sequence':sequence}));continue
            if len(m['flows'])>20 or m.get('interval_seconds')!=60:raise ValueError()
            for f in m['flows']:
                n=number(f['frame_bytes']);p=number(f['packets'])
                if not all(isinstance(f.get(k),str) for k in ['src','dst','protocol','src_port','dst_port','vlan']):raise ValueError()
                flows.append((t,{**f,'frame_bytes':n,'packets':p,'_boot':boot,'_sequence':sequence}))
        except (KeyError,ValueError,TypeError,json.JSONDecodeError):invalid+=1
    return flows,sorted(health,key=lambda x:x[0],reverse=True),invalid

def capture_intervals(flows,health,start,end,as_of=None):
    """Reconcile flush batches by boot/sequence; enqueue timestamps may differ.

    Interval counters are additive. Error counters are cumulative within a boot,
    so any reported loss remains a coverage concern even after a clean restart.
    """
    errors=('flow_capacity_overflow_packets','invalid_lines','queue_drops','delivery_errors')
    by_boot=collections.defaultdict(list)
    for t,h in health:by_boot[h['_boot']].append((t,h))
    batches=collections.defaultdict(list)
    for t,f in flows:batches[f['_boot']].append(f)
    incomplete=False;loss=any(h[k]>0 for t,h in health for k in errors)
    assigned=0
    for boot,records in by_boot.items():
        previous=None;ordered=sorted(batches[boot],key=lambda f:f['_sequence']);offset=0
        for t,h in sorted(records,key=lambda row:row[1]['_sequence']):
            begin=offset
            while offset<len(ordered) and ordered[offset]['_sequence']<h['_sequence']:offset+=1
            batch=ordered[begin:offset];assigned+=len(batch)
            if sum(f['frame_bytes'] for f in batch)!=h['interval_frame_bytes'] or sum(f['packets'] for f in batch)!=h['interval_packets']:incomplete=True
            if previous:
                if any(h[k]<previous[k] for k in ('packets_total','frame_bytes_total',*errors)):raise ValueError('Capture counters decreased within a boot')
                if h['packets_total']-previous['packets_total']!=h['interval_packets'] or h['frame_bytes_total']-previous['frame_bytes_total']!=h['interval_frame_bytes']:incomplete=True
            previous=h
    if assigned!=len(flows):incomplete=True
    # Emission timestamps differ from arrival times. Only the trailing boundary
    # receives a delivery-settling allowance; this cannot excuse a missing start.
    times=sorted(t for t,h in health)
    effective_start=max(start,CAPTURE_FIRST_COMPLETE)
    # Settling applies only to a current window, never permanently to history.
    elapsed=max(0,((as_of or datetime.now(UTC))-end).total_seconds())
    settling=max(0,CAPTURE_SETTLING-elapsed)
    if times:
        if (times[0]-effective_start).total_seconds()>=CAPTURE_INTERVAL:incomplete=True
        if (end-times[-1]).total_seconds()>CAPTURE_INTERVAL+settling:incomplete=True
        if any((b-a).total_seconds()>CAPTURE_INTERVAL+1 for a,b in zip(times,times[1:])):incomplete=True
    return sum(h['interval_frame_bytes'] for t,h in health),incomplete,loss

class Service:
    def __init__(self,client=None,geo=None):
        self.client=client or QueryClient();self.geo=geo or Geography();self.cache={};self.lock=threading.Lock()
    def overview(self,end,seconds):
        key=(stamp(end),seconds)
        with self.lock:
            item=self.cache.get(key)
            if item and time.monotonic()-item[0]<30:return copy.deepcopy(item[1])
            out=self.build(end,seconds)
            self.cache[key]=(time.monotonic(),out)
            if len(self.cache)>16:self.cache.pop(next(iter(self.cache)))
            return copy.deepcopy(out)
    def build(self,end,seconds):
        start=end-timedelta(seconds=seconds);deadline=time.monotonic()+15
        result={'mode':'live','as_of':stamp(datetime.now(UTC)), 'window':{'start':stamp(start),'end':stamp(end),'seconds':seconds,'label':{900:'Last 15 minutes',3600:'Last hour',86400:'Last 24 hours'}[seconds]},
          'sources':[],'metrics':dict.fromkeys(['devices','infrastructure','router_bytes','capture_bytes','dns_queries','dns_blocked','firewall_blocks','destinations','busiest']),
          'countries':[],'locations':[],'location_state':'unavailable','devices':[],'recent':[],'trend':[],'coverage':COVERAGE,'issues':[], 'geo':self.geo.status()}
        q=lambda query:self.client.query(query,deadline)
        def inventory():
            rows=q(base('unifi-snapshot',end-timedelta(hours=1),end,'entity_kind:=snapshot')+' | sort by (_time) desc | limit 1')
            if not rows:return {'rows':[],'snapshot':None}
            return {'rows':rows,'snapshot':json.loads(rows[0]['snapshot_json'])}
        def router():
            b=base('opnsense-flow',start,end,'schema:=2 remote_ip:=192.168.5.1')
            unique=b+' | stats by (event_id,src_addr,dst_addr,flow_end_ns) max(bytes) bytes'
            totals=q(unique+' | stats sum(bytes) bytes, count() records')
            endpoints=q(unique+' | stats by (src_addr,dst_addr) sum(bytes) bytes | limit 5001')
            # No interpolation across bins: each exported chunk belongs at flow end.
            rawtrend=q(b+' | stats by (event_id,_time:5m) max(bytes) bytes | stats by (_time) sum(bytes) bytes | sort by (_time)')
            latest=q(base('opnsense-flow',end-timedelta(minutes=30),end,'schema:=2 remote_ip:=192.168.5.1')+' | sort by (_time) desc | limit 1 | fields _time')
            if not latest:
                # Retain a stopped exporter's last observation beyond the freshness lookback.
                # This is still bounded by retention and the shared request deadline.
                latest=q(base('opnsense-flow',end-timedelta(days=30),end-timedelta(minutes=30),'schema:=2 remote_ip:=192.168.5.1')+' | sort by (_time) desc | limit 1 | fields _time')
            return {'bytes':scalar(totals,'bytes'),'records':scalar(totals,'records'),'endpoints':endpoints,'trend':rawtrend,'latest':latest}
        def dns():
            rows=q(base('pihole-dns',start,end)+' | stats by (event_id,outcome) count() receipts | stats by (outcome) count() queries')
            latest=q(base('pihole-dns',end-timedelta(minutes=30),end)+' | sort by (_time) desc | limit 1 | fields _time')
            snapshot=q(base('pihole-snapshot',end-timedelta(hours=1),end,'entity_kind:=snapshot')+' | sort by (_time) desc | limit 1 | fields _time, snapshot_json')
            return {'rows':rows,'latest':latest,'snapshot':snapshot}
        def capture():return q(base('tshark-summary',max(start,datetime(2026,10,5,1,26,19,tzinfo=UTC)),end)+' | sort by (_time) desc | limit 10001 | fields _time, _msg')
        def firewall():return q(base('filterlog',start,end)+' | sort by (_time) desc | limit 1001 | fields _time, _msg, remote_ip, app_name')
        jobs={'inventory':inventory,'router':router,'dns':dns,'capture':capture,'firewall':firewall};values={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(fn):k for k,fn in jobs.items()}
            for future in concurrent.futures.as_completed(futures):
                k=futures[future]
                try:values[k]=future.result()
                except Exception:values[k]=None
        titles={'inventory':'UniFi devices','router':'Router traffic','dns':'Pi-hole DNS','capture':'Kitchen capture','firewall':'Firewall decisions'}
        for k in jobs:
            if values[k] is None:
                result['sources'].append(source(k,titles[k],None,end,'The source query is unavailable or exceeded its limit. Try a shorter window.'))
        inv=values['inventory'];snapshot=inv.get('snapshot') if inv else None
        if inv is not None:
            observed=snapshot.get('observed_at') if snapshot else None
            s=source('inventory',titles['inventory'],observed,end,'Sampled inventory; absence is not proof of an offline device.',150)
            if snapshot:
                if snapshot.get('partial'):
                    s['state']='partial';result['issues'].append('The latest UniFi snapshot is partial. Device totals are withheld.')
                else:
                    result['metrics']['devices']=len(snapshot['clients']);result['metrics']['infrastructure']=len(snapshot['devices'])
                names={d['id']:d.get('name','') for d in snapshot['devices']}
                result['devices']=[{'id':str(d['id']),'name':str(d.get('name') or d.get('ip') or 'Unnamed device'),'ip':str(d.get('ip') or ''),'type':str(d.get('type') or 'Unknown'),'attachment':names.get(d.get('uplink_id'),'Unknown attachment'),'observed_at':observed} for d in snapshot['clients'][:2000]]
            result['sources'].append(s)
        flow=values['router']
        if flow is not None:
            latest=flow['latest'][0]['_time'] if flow['latest'] else None
            s=source('router',titles['router'],latest,end,'Flow exports may arrive several minutes late. Freshness describes received records, not collector health.',600)
            if not flow['records']:
                # A successful empty query is absence of evidence, not a measured zero.
                # Keep the prior observation, but never let recent records alone certify
                # collection coverage for an empty selected window.
                if s['state']=='fresh':s['state']='unavailable'
                s['note']='No router flow records were observed in this window. Traffic and collection coverage are unknown; the current query API has no router heartbeat.'
            else:result['metrics']['router_bytes']=flow['bytes']
            result['sources'].append(s)
            result['trend']=[{'time':r['_time'],'bytes':number(r['bytes'])} for r in flow['trend']]
            if len(flow['endpoints'])>5000:
                result['location_state']='withheld';result['issues'].append('Endpoint breakdown exceeded 5,000 pairs; destinations and geography are withheld. Router total remains complete for received records.')
            elif flow['records']:
                ips=set()
                for row in flow['endpoints']:
                    for key in ['src_addr','dst_addr']:
                        try:
                            ip=ipaddress.ip_address(row[key])
                            if public_endpoint(str(ip),NETWORKS):ips.add(str(ip))
                        except (ValueError,KeyError):pass
                result['metrics']['destinations']=len(ips)
                result['countries'],result['locations']=aggregate({ip:(self.geo.lookup(ip),None) for ip in ips})
                result['location_state']='available'
        dnsdata=values['dns']
        if dnsdata is not None:
            latest=dnsdata['latest'][0]['_time'] if dnsdata['latest'] else None
            snap=dnsdata['snapshot'][0]['_time'] if dnsdata['snapshot'] else None
            s=source('dns',titles['dns'],latest or snap,end,'Pi-hole events settle for 60 seconds and are polled every minute.',240,quiet=bool(snap))
            result['sources'].append(s)
            # Successful empty query can mean zero events; a missing snapshot cannot certify coverage.
            if latest or snap:
                result['metrics']['dns_queries']=sum(number(r['queries']) for r in dnsdata['rows'])
                result['metrics']['dns_blocked']=sum(number(r['queries']) for r in dnsdata['rows'] if r.get('outcome')=='blocked')
        cap=values['capture']
        if cap is not None:
            try:
                flows,health,invalid=capture_rows(cap,start,end)
                total,incomplete,loss=capture_intervals(flows,health,start,end,date(result['as_of']))
                observed=stamp(health[0][0]) if health else None
                s=source('capture',titles['capture'],observed,end,'Kitchen-only completed 60-second intervals by emission time. Current interval and up to 30 seconds of delivery settling excluded. Kernel drops unknown; hourly restart gap.',CAPTURE_INTERVAL+CAPTURE_SETTLING)
                if invalid:
                    s['state']='partial';result['issues'].append('Malformed capture records were encountered; Kitchen totals are withheld.')
                elif incomplete:
                    s['state']='partial';result['issues'].append('Kitchen capture intervals or connection batches are incomplete; Kitchen totals and device ranking are withheld.')
                elif health:result['metrics']['capture_bytes']=total
                if loss:
                    s['state']='partial';result['issues'].append('Kitchen capture reported cumulative application errors or dropped summaries in this window, including earlier boots. The exact loss time is unknown.')
                result['sources'].append(s)
                # Name only an unambiguous recent IP observed on Kitchen; never map old flows with today's DHCP identity.
                if snapshot and not snapshot.get('partial') and (end-date(snapshot['observed_at'])).total_seconds()<=150 and not invalid and not incomplete and not loss:
                    kitchen_ids={d['id'] for d in snapshot['devices'] if str(d.get('mac','')).lower()=='28:70:4e:5b:0e:ab'}
                    clients=collections.defaultdict(list)
                    for c in snapshot['clients']:
                        if c.get('ip') and c.get('uplink_id') in kitchen_ids:clients[c['ip']].append(c)
                    totals=collections.Counter()
                    for t,f in flows:
                        if abs((t-date(snapshot['observed_at'])).total_seconds())>120:continue
                        for ip in {f['src'],f['dst']}:
                            if len(clients.get(ip,[]))==1:totals[ip]+=f['frame_bytes']
                    if totals:
                        ip,n=totals.most_common(1)[0];c=clients[ip][0]
                        result['metrics']['busiest']={'name':str(c.get('name') or ip),'ip':ip,'bytes':n,'identity_note':'Recent two-minute capture sample correlated to a nearby UniFi snapshot; identity is inferred, not a full-window ranking.'}
            except (QueryError,ValueError,TypeError,KeyError):
                result['metrics']['capture_bytes']=None;result['metrics']['busiest']=None
                result['sources'].append(source('capture',titles['capture'],None,end,'Capture data exceeded a bound or could not be validated. Select a shorter time window.'))
        fw=values['firewall']
        if fw is not None:
            observed=fw[0]['_time'] if fw else None
            result['sources'].append(source('firewall',titles['firewall'],observed,end,'Only logged firewall decisions. Quiet periods do not imply collection failure.',300,quiet=True))
            events=[parse_filterlog(r,NETWORKS) for r in fw[:1000]]
            if len(fw)<=1000 and not any(e.get('parse_error') for e in events):result['metrics']['firewall_blocks']=sum(e.get('action')=='block' for e in events)
        result['metrics']['attention']=sum(s['state'] in ('stale','unavailable','partial') for s in result['sources'])
        # Recent feed uses facts from archived source state, never inferred application actions.
        for s in result['sources']:
            if s['observed_at']:result['recent'].append({'id':s['id']+s['observed_at'],'time':s['observed_at'],'text':f"{s['title']} supplied an observation.",'source':s['title']})
        result['recent'].sort(key=lambda r:r['time'],reverse=True)
        return Overview.model_validate(result).model_dump()
service=Service()
