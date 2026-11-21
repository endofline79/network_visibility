"""Loopback-first presentation. No collectors or controller calls.

Phase 0 adds a host-name cache and planner settings for a later ask path.
This process does not call an LLM.
"""
import copy
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .demo import demo
from .models import Overview,GlobeSnapshot,Alerts,OpsHome,DestinationsView
from .auth import Viewer,Login,same_origin
from .hosts import HostCache
from .planner import status as planner_status
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

log=logging.getLogger('visibility.app')
NETWORK_CACHE_TTL=15.0
NETWORK_CACHE_MAX=32
_network_cache_lock=threading.Lock()
_network_cache={}

def _network_cached(key,builder):
    now=time.monotonic()
    with _network_cache_lock:
        entry=_network_cache.get(key)
        if entry and now-entry[0]<NETWORK_CACHE_TTL:
            return copy.deepcopy(entry[1])
    payload=builder()
    with _network_cache_lock:
        _network_cache[key]=(time.monotonic(),copy.deepcopy(payload))
        while len(_network_cache)>NETWORK_CACHE_MAX:
            _network_cache.pop(next(iter(_network_cache)))
    return payload

@asynccontextmanager
async def _lifespan(_app):
    try:yield
    finally:host_cache._stop.set()

MODE=os.getenv('PRESENTATION_MODE','demo')
if MODE not in ('demo','live'):raise RuntimeError('PRESENTATION_MODE must be demo or live')
AUTH=os.getenv('PRESENTATION_AUTH','preview')
if AUTH not in ('preview','required'):raise RuntimeError('Invalid authentication mode')
if MODE=='live' and AUTH!='required':raise RuntimeError('Live mode requires viewer authentication')
viewer=Viewer(os.getenv('VIEWER_CONFIG_FILE','/run/visibility/viewer.json')) if AUTH=='required' else None
STATIC=Path(os.getenv('STATIC_DIR',Path(__file__).resolve().parents[1]/'frontend/dist'))
app=FastAPI(title='Visibility presentation',docs_url=None,redoc_url=None,openapi_url=None,lifespan=_lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver','192.168.5.230','ai-02'])
@app.middleware('http')
async def guard(request,call_next):
    session_path=request.url.path in ('/api/session/login','/api/session/logout')
    if request.method not in ('GET','HEAD') and not (session_path and request.method=='POST'):
        return JSONResponse({'detail':'This presentation API is read-only'},status_code=405)
    if viewer and request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/session/login') and request.session.get('viewer')!=viewer.username:
        return JSONResponse({'detail':'Sign in to view your network'},status_code=401,headers={'Cache-Control':'no-store'})
    response=await call_next(request)
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
    if request.url.scheme=='https':
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response
if viewer:
    app.add_middleware(SessionMiddleware,secret_key=viewer.secret,session_cookie='visibility_viewer',max_age=28800,same_site='strict',https_only=True)
@app.post('/api/session/login')
def login(body:Login,request:Request):
    if not viewer:raise HTTPException(404,'Viewer sign-in is not configured in this demo')
    same_origin(request)
    if not viewer.verify(request.client.host if request.client else 'unknown',body.username,body.password):raise HTTPException(401,'Sign-in failed')
    request.session.clear();request.session['viewer']=viewer.username
    return {'authenticated':True}
@app.post('/api/session/logout')
def logout(request:Request):
    if not viewer:raise HTTPException(404,'Viewer sign-in is not configured in this demo')
    same_origin(request);request.session.clear()
    return {'authenticated':False}
VERSION='0.5.1'
def _anchor(end):
    anchor=end or datetime.now(timezone.utc).replace(second=0,microsecond=0)
    if anchor.tzinfo is None:raise HTTPException(422,'A timezone is required')
    anchor=anchor.astimezone(timezone.utc)
    if (anchor-datetime.now(timezone.utc)).total_seconds()>60:raise HTTPException(422,'Future windows are unavailable')
    if (datetime.now(timezone.utc)-anchor).total_seconds()>30*86400:raise HTTPException(422,'Window exceeds retention')
    return anchor
_RANGE_SECONDS={'1h':3600,'24h':86400,'7d':604800}
@app.get('/api/network/overview')
def network_overview(range:Literal['1h','24h','7d']='24h',end:datetime|None=None):
    anchor=_anchor(end);seconds=_RANGE_SECONDS[range]
    if MODE=='demo':
        from .network_demo import demo_overview
        return demo_overview(anchor,seconds)
    from .network import Directory,live_overview
    from .service import service
    try:return _network_cached(('overview',range,anchor.isoformat()),lambda:live_overview(service.client,anchor,seconds,Directory.from_sources(host_cache)))
    except Exception as exc:
        log.warning('network overview failed: %s',type(exc).__name__)
        raise HTTPException(503,'Network overview cannot be validated right now') from None
@app.get('/api/network/host/{host_id}')
def network_host(host_id:str,range:Literal['1h','24h','7d']='24h',end:datetime|None=None):
    if not host_id or len(host_id)>80 or not all(ch.isalnum() or ch in '-_.' for ch in host_id):
        raise HTTPException(404,'Host was not found')
    anchor=_anchor(end);seconds=_RANGE_SECONDS[range];host_id=host_id.lower()
    if MODE=='demo':
        from .network_demo import demo_host
        payload=demo_host(anchor,seconds,host_id)
        if payload is None:raise HTTPException(404,'Host was not found')
        return payload
    from .network import Directory,live_host
    from .service import service
    record=Directory.from_sources(host_cache).resolve(host_id)
    if record is None:raise HTTPException(404,'Host was not found')
    try:return _network_cached(('host',range,anchor.isoformat(),record['id']),lambda:live_host(service.client,anchor,seconds,record))
    except Exception as exc:
        log.warning('network host failed: %s',type(exc).__name__)
        raise HTTPException(503,'Host view cannot be validated right now') from None
@app.get('/api/network/firewall')
def network_firewall(range:Literal['1h','24h','7d']='24h',end:datetime|None=None):
    anchor=_anchor(end);seconds=_RANGE_SECONDS[range]
    if MODE=='demo':
        from .network_demo import demo_firewall
        return demo_firewall(anchor,seconds)
    from .network import Directory,live_firewall
    from .service import service
    try:return _network_cached(('firewall',range,anchor.isoformat()),lambda:live_firewall(service.client,anchor,seconds,Directory.from_sources(host_cache)))
    except Exception as exc:
        log.warning('network firewall failed: %s',type(exc).__name__)
        raise HTTPException(503,'Firewall view cannot be validated right now') from None
@app.get('/api/network/dns')
def network_dns(range:Literal['1h','24h','7d']='24h',host:str|None=None,end:datetime|None=None):
    anchor=_anchor(end);seconds=_RANGE_SECONDS[range]
    host_id=None
    if host is not None and host!='':
        if len(host)>80 or not all(ch.isalnum() or ch in '-_.' for ch in host):
            raise HTTPException(404,'Host was not found')
        host_id=host.lower()
    if MODE=='demo':
        from .network_demo import demo_dns
        payload=demo_dns(anchor,seconds,host_id=host_id)
        if payload is None:raise HTTPException(404,'Host was not found')
        return payload
    from .network import Directory,live_dns
    from .service import service
    directory=Directory.from_sources(host_cache)
    record=None
    if host_id is not None:
        record=directory.resolve(host_id)
        if record is None:raise HTTPException(404,'Host was not found')
    try:return _network_cached(('dns',range,anchor.isoformat(),record['id'] if record else ''),lambda:live_dns(service.client,anchor,seconds,directory,record=record))
    except Exception as exc:
        log.warning('network dns failed: %s',type(exc).__name__)
        raise HTTPException(503,'DNS view cannot be validated right now') from None
@app.get('/api/health')
def health():return {'status':'ok','mode':MODE,'version':VERSION}
@app.get('/api/overview',response_model=Overview)
def overview(window:Literal['15m','1h','24h']='1h',scenario:Literal['normal','stale','unavailable','error']='normal',end:datetime|None=None):
    anchor=_anchor(end)
    seconds={'15m':900,'1h':3600,'24h':86400}[window]
    if MODE=='demo':
        if scenario=='error':raise HTTPException(503,'Demo unavailable state')
        return demo(anchor,seconds,scenario)
    if scenario!='normal':raise HTTPException(422,'Demo scenarios are unavailable in live mode')
    from .service import service
    try:return service.overview(anchor,seconds)
    except Exception as exc:
        log.warning('overview failed: %s',type(exc).__name__)
        raise HTTPException(503,'Telemetry cannot be validated right now') from None
@app.get('/api/ops',response_model=OpsHome)
def ops_home(window:Literal['15m','1h']='1h',scenario:Literal['normal','stale','unavailable','error']='normal',end:datetime|None=None):
    anchor=_anchor(end)
    seconds={'15m':900,'1h':3600}[window]
    from . import ops as ops_view
    if MODE=='demo':
        if scenario=='error':raise HTTPException(503,'Demo unavailable state')
        return ops_view.demo_ops(anchor,seconds,scenario)
    if scenario!='normal':raise HTTPException(422,'Demo scenarios are unavailable in live mode')
    try:
        from .service import service
        return ops_view.live_ops(service.client,anchor,seconds)
    except Exception as exc:
        log.warning('ops home failed: %s',type(exc).__name__)
        raise HTTPException(503,'Operations view cannot be validated right now') from None
@app.get('/api/destinations',response_model=DestinationsView)
def destinations(window:Literal['1h','24h','7d']='24h',host:str='all',scenario:Literal['normal','stale','unavailable','error']='normal',end:datetime|None=None):
    anchor=_anchor(end)
    seconds={'1h':3600,'24h':86400,'7d':7*86400}[window]
    from .inventory import InventoryError,load_inventory
    from . import destinations as destinations_view
    try:inventory=load_inventory()
    except InventoryError:raise HTTPException(503,'IoT host inventory cannot be read') from None
    if host!='all' and inventory.by_id(host) is None:raise HTTPException(404,'Host is not on the IoT allowlist')
    if MODE=='demo':
        if scenario=='error':raise HTTPException(503,'Demo unavailable state')
        return destinations_view.demo_destinations(inventory,anchor,seconds,host,scenario)
    if scenario!='normal':raise HTTPException(422,'Demo scenarios are unavailable in live mode')
    try:
        from .service import service
        return destinations_view.live_destinations(service.client,inventory,anchor,seconds,host)
    except Exception as exc:
        log.warning('destinations failed: %s',type(exc).__name__)
        raise HTTPException(503,'DNS destinations cannot be validated right now') from None
@app.get('/api/alerts',response_model=Alerts)
def alerts():
    from . import alerts as alert_view
    if MODE=='demo':return alert_view.demo_alerts()
    try:
        from .service import service
        return alert_view.live_alerts(service.client)
    except Exception as exc:
        log.warning('alerts failed: %s',type(exc).__name__)
        raise HTTPException(503,'Alerts cannot be validated right now') from None
@app.get('/api/globe',response_model=GlobeSnapshot)
def live_globe(scenario:Literal['normal','stale','unavailable','error']='normal'):
    if MODE=='demo':
        if scenario=='error':raise HTTPException(503,'Demo unavailable state')
        anchor=datetime.now(timezone.utc)
        view=demo(anchor,900,scenario)
        observed=anchor if scenario=='normal' else anchor-timedelta(minutes=8)
        return {'mode':'demo','as_of':anchor.isoformat(),
                'window':{'start':(anchor-timedelta(seconds=300)).isoformat(),'end':anchor.isoformat(),'seconds':300,'label':'Last 5 minutes'},
                'refresh_seconds':10,'state':('fresh' if scenario=='normal' else 'stale' if scenario=='stale' else 'unavailable'),
                'observed_at':observed.isoformat() if scenario!='unavailable' else None,
                'endpoints':view['metrics']['destinations'] if scenario!='unavailable' else None,
                'countries':[{**c,'last_seen':observed.isoformat(),'activity_id':'demo:'+c['code']} for c in view['countries']] if scenario!='unavailable' else [],
                'locations':[{**a,'last_seen':observed.isoformat(),'activity_id':'demo:'+a['id'],'age_buckets':[{'last_seen':observed.isoformat(),'count':a['count']}]} for a in view['locations']] if scenario!='unavailable' else [],
                'geo':view['geo'],'note':'Simulated near-live activity. Live mode uses router NetFlow public endpoints; exports may arrive minutes late. Approximate IP areas, not verified server locations or packet routes.'}
    if scenario!='normal':raise HTTPException(422,'Demo scenarios are unavailable in live mode')
    return globe_service.snapshot()
if MODE=='live':
    from .service import service
    from .live_globe import LiveGlobe
    globe_service=LiveGlobe(service.client,service.geo)
    from .client import QueryClient
    _planner_queries=QueryClient()
    _planner_queries.token_path=Path(os.getenv('PLANNER_TOKEN_FILE','/run/visibility/planner-token'))
    host_cache=HostCache(clients=[_planner_queries,service.client])
    if os.getenv('HOST_CACHE_AUTOSTART','1')!='0':host_cache.start()
else:
    host_cache=HostCache()
@app.get('/api/hosts')
def hosts():return host_cache.snapshot()
@app.get('/api/planner')
def planner():return planner_status()
if STATIC.exists():
    app.mount('/assets',StaticFiles(directory=STATIC/'assets'),name='assets')
    @app.get('/')
    def index():return FileResponse(STATIC/'index.html')
    @app.get('/legacy')
    def legacy_page():
        page=STATIC/'legacy.html'
        if not page.exists():raise HTTPException(404,'The previous console is not built')
        return FileResponse(page)
