"""Approximate public-IP areas, not host positions or confidence boundaries.

Half-degree grouping deliberately coarsens the provider's coordinates. Only
locations with a city or region label are plotted. Every endpoint contributes
exactly once: mapped area, country-only, unknown, or explicit bounded overflow.
"""
import collections,hashlib,json,math
from datetime import datetime,timezone
GRID_DEGREES=.5
MAX_AREAS=96

def valid_coordinate(value,limit):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and -limit<=value<=limit

def timestamp(value):
    if not value:return None
    return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc)

def identity(key):return hashlib.sha256(json.dumps(key,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()[:24]

def aggregate(endpoints,near_live=False):
    # Input already excludes private/reserved addresses. Keys are never returned.
    areas={};countries={}
    for loc,seen in endpoints.values():
        loc=loc or {};code=loc.get('code') or '??';country=loc.get('name') or 'Unknown location'
        region=loc.get('region') or None;city=loc.get('city') or None
        lat,lon=loc.get('latitude'),loc.get('longitude')
        precision='area' if code!='??' and (region or city) and valid_coordinate(lat,90) and valid_coordinate(lon,180) else 'unknown' if code=='??' else 'country'
        if precision=='area':
            y=min(359,math.floor((lat+90)/GRID_DEGREES));x=min(719,math.floor((lon+180)/GRID_DEGREES))
            key=(code,region,x,y);lat=-90+(y+.5)*GRID_DEGREES;lon=-180+(x+.5)*GRID_DEGREES
        else:key=(code,precision);lat=lon=None
        code_id=identity(key)
        if code_id not in areas:
            areas[code_id]={'id':code_id,'country_code':code,'country_name':country,'region':region if precision=='area' else None,'precision':precision,'latitude':lat,'longitude':lon,'count':0,'_cities':collections.Counter(),'_times':collections.Counter(),'_radii':[]}
        a=areas[code_id];a['count']+=1
        if city and precision=='area':a['_cities'][str(city)]+=1
        if near_live and seen:a['_times'][timestamp(seen).isoformat().replace('+00:00','Z')]+=1
        radius=loc.get('accuracy_radius_km')
        if isinstance(radius,(int,float)) and not isinstance(radius,bool) and math.isfinite(radius) and radius>0:a['_radii'].append(radius)
        if code not in countries:countries[code]={'code':code,'name':country,'count':0,'percent':0,'latitude':None,'longitude':None,'_times':[]}
        c=countries[code];c['count']+=1
        if near_live and seen:c['_times'].append(timestamp(seen))
    # Hash order is independent of count or timestamp so refreshes cannot select
    # a different representative simply because traffic volume changes.
    mapped=sorted((a for a in areas.values() if a['precision']=='area'),key=lambda a:a['id']);kept=mapped[:MAX_AREAS]
    unplaced=[a for a in areas.values() if a['precision']!='area'];overflow={}
    for a in mapped[MAX_AREAS:]:
        code=a['country_code']
        if code not in overflow:
            overflow[code]={**a,'id':identity((code,'overflow')),'precision':'overflow','latitude':None,'longitude':None,'region':None,'count':0,'_cities':collections.Counter(),'_times':collections.Counter(),'_radii':[]}
        o=overflow[code];o['count']+=a['count'];o['_times'].update(a['_times']);o['_radii'].extend(a['_radii'])
    result=[]
    for a in [*kept,*unplaced,*overflow.values()]:
        cities=a.pop('_cities');times=a.pop('_times');radii=a.pop('_radii')
        a['cities']=[name for name,count in sorted(cities.items(),key=lambda x:(-x[1],x[0]))[:3]]
        a['other_city_labels']=max(0,len(cities)-3)
        a['name']=(a['region'] or (a['cities'][0] if a['cities'] else a['country_name'])) if a['precision']=='area' else {'unknown':'Unknown IP location','country':a['country_name']+' · country only','overflow':a['country_name']+' · additional areas'}[a['precision']]
        a['last_seen']=max(times,key=timestamp) if times else None
        a['activity_id']=identity((a['id'],a['last_seen'])) if a['last_seen'] else None
        a['age_buckets']=[{'last_seen':t,'count':n} for t,n in sorted(times.items(),key=lambda x:timestamp(x[0]))]
        # A single radius cannot describe a mix of estimates and missing metadata.
        a['accuracy_radius_km']=max(radii) if len(radii)==a['count'] and radii else None
        a['radius_known_count']=len(radii)
        result.append(a)
    total=len(endpoints)
    for c in countries.values():
        times=c.pop('_times');c['percent']=round(c['count']/total*100,2) if total else 0
        if near_live:c['last_seen']=max(times).isoformat().replace('+00:00','Z') if times else None;c['activity_id']=identity((c['code'],c['last_seen']))
    result.sort(key=lambda a:(a['precision']!='area',-a['count'],a['id']))
    return sorted(countries.values(),key=lambda c:(-c['count'],c['code'])),result
