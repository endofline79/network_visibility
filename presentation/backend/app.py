"""Loopback-first presentation. No collectors, ingestion, controller calls or AI runtime."""
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .demo import demo
from .models import Overview,GlobeSnapshot,Alerts
from .auth import Viewer,Login,same_origin
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

MODE=os.getenv('PRESENTATION_MODE','demo')
if MODE not in ('demo','live'):raise RuntimeError('PRESENTATION_MODE must be demo or live')
AUTH=os.getenv('PRESENTATION_AUTH','preview')
if AUTH not in ('preview','required'):raise RuntimeError('Invalid authentication mode')
if MODE=='live' and AUTH!='required':raise RuntimeError('Live mode requires viewer authentication')
viewer=Viewer(os.getenv('VIEWER_CONFIG_FILE','/run/visibility/viewer.json')) if AUTH=='required' else None
STATIC=Path(os.getenv('STATIC_DIR',Path(__file__).resolve().parents[1]/'frontend/dist'))
app=FastAPI(title='Visibility presentation',docs_url=None,redoc_url=None,openapi_url=None)
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
@app.get('/api/health')
def health():return {'status':'ok','mode':MODE,'version':'0.2.0'}
@app.get('/api/overview',response_model=Overview)
def overview(window:Literal['15m','1h','24h']='1h',scenario:Literal['normal','stale','unavailable','error']='normal',end:datetime|None=None):
    anchor=end or datetime.now(timezone.utc).replace(second=0,microsecond=0)
    if anchor.tzinfo is None:raise HTTPException(422,'A timezone is required')
    anchor=anchor.astimezone(timezone.utc)
    if (anchor-datetime.now(timezone.utc)).total_seconds()>60:raise HTTPException(422,'Future windows are unavailable')
    if (datetime.now(timezone.utc)-anchor).total_seconds()>30*86400:raise HTTPException(422,'Window exceeds retention')
    seconds={'15m':900,'1h':3600,'24h':86400}[window]
    if MODE=='demo':
        if scenario=='error':raise HTTPException(503,'Demo unavailable state')
        return demo(anchor,seconds,scenario)
    if scenario!='normal':raise HTTPException(422,'Demo scenarios are unavailable in live mode')
    from .service import service
    try:return service.overview(anchor,seconds)
    except Exception:raise HTTPException(503,'Telemetry cannot be validated right now') from None
@app.get('/api/alerts',response_model=Alerts)
def alerts():
    from . import alerts as alert_view
    if MODE=='demo':return alert_view.demo_alerts()
    try:
        from .service import service
        return alert_view.live_alerts(service.client)
    except Exception:raise HTTPException(503,'Alerts cannot be validated right now') from None
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
if STATIC.exists():
    app.mount('/assets',StaticFiles(directory=STATIC/'assets'),name='assets')
    @app.get('/')
    def index():return FileResponse(STATIC/'index.html')
