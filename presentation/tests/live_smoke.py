"""Explicit opt-in read-only historical test. Uses existing authorized SSH, no credentials copied."""
import json,subprocess,sys,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.service import Service,Geography,base
class SSHQueries:
    def query(self,query,deadline):
        program='import urllib.request,urllib.parse\nq='+repr(query)+'\ndata=urllib.parse.urlencode({"query":q,"timeout":"7s"}).encode()\nwith urllib.request.urlopen("http://127.0.0.1:9428/select/logsql/query",data,timeout=8) as r: print(r.read(8388609).decode())\n'
        r=subprocess.run(['ssh','-F','/home/klab/.ssh/config','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','klab@192.168.5.230','python3 -'],input=program,capture_output=True,text=True,timeout=max(1,min(12,deadline-time.monotonic())))
        if r.returncode or len(r.stdout)>8388608:raise RuntimeError('Read-only query failed')
        return [json.loads(s) for s in r.stdout.splitlines() if s.strip()]
end=datetime(2026,10,5,1,30,tzinfo=timezone.utc);start=end-timedelta(minutes=15)
client=SSHQueries();result=Service(client,Geography()).overview(end,900)
raw=client.query(base('opnsense-flow',start,end,'schema:=2 remote_ip:=192.168.5.1')+' | limit 20001 | fields event_id, bytes',time.monotonic()+15)
assert len(raw)<=20000,'Reference bound exceeded'
unique={}
for r in raw:unique[r['event_id']]=max(unique.get(r['event_id'],0),int(r['bytes']))
assert result['metrics']['router_bytes']==sum(unique.values()),'Router aggregate differs from independent event-id deduplication'
dns=client.query(base('pihole-dns',start,end)+' | limit 10001 | fields event_id, outcome',time.monotonic()+15)
assert len(dns)<=10000
unique_dns={r['event_id']:r['outcome'] for r in dns}
assert result['metrics']['dns_queries']==len(unique_dns)
assert result['metrics']['dns_blocked']==sum(v=='blocked' for v in unique_dns.values())
assert result['metrics']['capture_bytes'] is not None,'Capture result unexpectedly unavailable'
assert result['metrics']['devices'] is not None,'Inventory unexpectedly unavailable'
summary={'window':result['window'],'independent_flow_rows':len(raw),'unique_flow_events':len(unique),'router_ip_bytes':result['metrics']['router_bytes'],'dns_queries':result['metrics']['dns_queries'],'dns_blocked':result['metrics']['dns_blocked'],'capture_frame_bytes':result['metrics']['capture_bytes'],'sources':result['sources'],'issues':result['issues'],'verified':'Adapter totals agree with independent raw-event calculations; no mutations performed.'}
print(json.dumps(summary,indent=2))
