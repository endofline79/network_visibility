"""Clearly labeled illustrative data; never used as a live-mode fallback."""
from datetime import datetime,timedelta,timezone
from .locations import aggregate

def demo(end, seconds, scenario='normal'):
    stamp=lambda d:d.isoformat().replace('+00:00','Z')
    places=[('US','United States',39.8,-98.6,84),('GB','United Kingdom',51.5,-.1,36),('CA','Canada',45.4,-75.7,20),('DE','Germany',50.1,8.7,16),('AU','Australia',-33.9,151.2,12),('JP','Japan',35.7,139.7,12),('SG','Singapore',1.35,103.8,8),('BR','Brazil',-23.55,-46.63,8),('??','Unknown location',None,None,4)]
    titles={'inventory':'UniFi devices','router':'Router traffic','dns':'Pi-hole DNS','capture':'Kitchen capture','firewall':'Firewall decisions'}
    result={'mode':'demo','as_of':stamp(datetime.now(timezone.utc)), 'window':{'start':stamp(end-timedelta(seconds=seconds)),'end':stamp(end),'seconds':seconds,'label':{900:'Last 15 minutes',3600:'Last hour',86400:'Last 24 hours'}[seconds]},
      'sources':[{'id':k,'title':v,'state':'fresh','observed_at':stamp(end-timedelta(seconds=70 if k=='dns' else 24)),'note':'Illustrative observations for this design preview.'} for k,v in titles.items()],
      'metrics':{'devices':18,'infrastructure':3,'router_bytes':2640000000,'capture_bytes':486000000,'dns_queries':2846,'dns_blocked':192,'firewall_blocks':84,'destinations':200,'busiest':{'name':'Living room TV','ip':'192.0.2.10','bytes':192000000,'identity_note':'Illustrative device identity; not a real household measurement.'},'attention':0},
      'countries':[{'code':c,'name':n,'latitude':lat,'longitude':lon,'count':num,'percent':num/2} for c,n,lat,lon,num in places],
      'devices':[{'id':f'demo-{i}','name':name,'ip':f'192.0.2.{10+i}','type':'Wireless' if i%2==0 else 'Wired','attachment':'Kitchen' if i%2==0 else 'Home switch','observed_at':stamp(end-timedelta(seconds=24))} for i,name in enumerate(['Living room TV','Home server','Phone','Workstation','Kitchen speaker','Pi-hole'])],
      'recent':[{'id':f'demo-{i}','time':stamp(end-timedelta(minutes=i+1)),'text':text,'source':source} for i,(text,source) in enumerate([('Kitchen device exchanged DNS traffic with Pi-hole.','Kitchen capture'),('A device was observed through Kitchen.','UniFi'),('Pi-hole filtered a DNS request.','DNS'),('A public endpoint appeared in routed observations.','Router')])],
      'trend':[{'time':stamp(end-timedelta(minutes=60-i*5)),'bytes':v*1000000} for i,v in enumerate([90,120,112,180,155,110,220,300,270,210,290,240])],
      'coverage':['Demo data is illustrative. All values on this screen are fictional.','Router IP bytes and Kitchen Ethernet frame bytes overlap; never add them together.','Kitchen mirror: source port 1 → destination port 4, verified October 5, 2026. Only traffic crossing that AP connection is covered.','Capture kernel drops are unmeasured. The hourly restart causes an approximately ten-second gap.','Raw collector labels still say flex-port7-pilot and mirror_enabled: unverified. They are not live switch configuration checks.','IP geolocation is approximate. Arcs show relationships, not packet routes.'], 'issues':[], 'geo':{'available':True,'provider':'DB-IP Lite (demo locations)','age_days':4}}
    areas=[('US','United States','California','Mountain View',37.4225,-122.085,34),('US','United States','Virginia','Ashburn',39.0438,-77.4874,30),('US','United States','New York','New York',40.7128,-74.006,20)]
    labels={'GB':('England','London'),'CA':('Ontario','Ottawa'),'DE':('Hesse','Frankfurt'),'AU':('New South Wales','Sydney'),'JP':('Tokyo','Tokyo'),'SG':('Singapore','Singapore'),'BR':('São Paulo','São Paulo'),'??':(None,None)}
    areas += [(c,n,*labels[c],lat,lon,num) for c,n,lat,lon,num in places if c!='US']
    result['countries'],result['locations']=aggregate({f'demo:{c}:{city}:{i}':({'code':c,'name':n,'region':region if lat is not None else None,'city':city if lat is not None else None,'latitude':lat,'longitude':lon},None) for c,n,region,city,lat,lon,num in areas for i in range(num)})
    result['location_state']='available'
    if scenario=='stale':
      for s in result['sources']:s.update(state='stale',observed_at=stamp(end-timedelta(minutes=12)),note='Updates are delayed. The last observation remains visible.')
      result['metrics']['attention']=5;result['issues']=['The preview simulates delayed source updates.']
    if scenario=='unavailable':
      result['location_state']='unavailable'
      for s in result['sources']:s.update(state='unavailable',observed_at=None,note='No observations are available.')
      result['metrics']={k:None for k in result['metrics']};result['metrics']['attention']=5
      for k in ['countries','locations','devices','recent','trend']:result[k]=[]
      result['geo']['available']=False
    return result
