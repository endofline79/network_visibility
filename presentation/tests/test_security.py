import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from backend.auth import Viewer
from backend.client import QueryClient,QueryError
CONFIG={'username':'viewer-test','salt':'01'*16,'password_hash':hashlib.pbkdf2_hmac('sha256',b'test-only-password',bytes.fromhex('01'*16),600000).hex(),'session_secret':'test-fixture-secret-never-use-in-production-00000000'}
class Security(unittest.TestCase):
 def test_password_and_throttle(self):
  with patch.object(Path,'read_text',return_value=json.dumps(CONFIG)):v=Viewer('not-a-real-account')
  self.assertTrue(v.verify('test','viewer-test','test-only-password'))
  for _ in range(5):self.assertFalse(v.verify('test','viewer-test','incorrect'))
  with self.assertRaises(HTTPException) as cm:v.verify('test','viewer-test','test-only-password')
  self.assertEqual(cm.exception.status_code,429)
 def test_live_mode_refuses_unauthenticated_startup(self):
  env={**os.environ,'PRESENTATION_MODE':'live','PRESENTATION_AUTH':'preview'}
  p=subprocess.run([sys.executable,'-c','import backend.app'],env=env,capture_output=True,text=True,timeout=10)
  self.assertNotEqual(p.returncode,0);self.assertIn('Live mode requires viewer authentication',p.stderr)
 def test_session_secure_cookie_and_no_unauthorized_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'viewer-test.json';path.write_text(json.dumps(CONFIG))
   env={**os.environ,'PRESENTATION_MODE':'live','PRESENTATION_AUTH':'required','VIEWER_CONFIG_FILE':str(path)}
   program='''from fastapi.testclient import TestClient
from backend.app import app
c=TestClient(app,base_url='https://testserver')
assert c.get('/api/overview').status_code==401
assert c.get('/api/globe').status_code==401
assert c.get('/api/alerts').status_code==401
assert c.post('/api/alerts',json={}).status_code==405
assert c.post('/api/session/login',json={'username':'viewer-test','password':'test-only-password'}).status_code==403
r=c.post('/api/session/login',headers={'Origin':'https://testserver'},json={'username':'viewer-test','password':'test-only-password'})
assert r.status_code==200
cookie=r.headers['set-cookie'].lower()
assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
assert 'test-only-password' not in cookie
from unittest.mock import patch
from backend.models import GlobeSnapshot
from backend.app import globe_service
with patch.object(globe_service,'snapshot',return_value={'mode':'live','as_of':'2026-10-06T01:00:00Z','window':{'start':'2026-10-06T00:55:00Z','end':'2026-10-06T01:00:00Z','seconds':300,'label':'Last 5 minutes'},'refresh_seconds':10,'state':'unavailable','observed_at':None,'endpoints':None,'countries':[],'geo':{'available':False,'provider':'test','age_days':None},'note':'fixture'}) as read:
 assert c.get('/api/globe').status_code==200
 assert read.call_count==1
 assert c.get('/api/globe?scenario=stale').status_code==422
 assert c.post('/api/globe',json={}).status_code==405
from backend import alerts as alerts_mod
fixture={'mode':'live','as_of':'2026-10-24T16:00:00Z','checker':'ok','illustrative':False,'open':[],'resolved':[]}
with patch.object(alerts_mod,'live_alerts',return_value=fixture) as read_alerts:
 assert c.get('/api/alerts').status_code==200
 assert read_alerts.call_count==1
 assert c.post('/api/alerts',json={}).status_code==405
assert c.post('/api/session/logout',headers={'Origin':'https://testserver'},json={}).status_code==200
assert c.get('/api/overview').status_code==401
assert c.get('/api/globe').status_code==401
assert c.get('/api/alerts').status_code==401
print('authenticated-session-contract-ok')
'''
   r=subprocess.run([sys.executable,'-c',program],env=env,text=True,capture_output=True,timeout=15)
   self.assertEqual(r.returncode,0,r.stderr);self.assertIn('authenticated-session-contract-ok',r.stdout)
 def test_query_transport_fixed_path_no_redirect_and_no_secret_error(self):
  class Response:status=302
  class Connection:
   def __init__(self,*args,**kwargs):self.sock=None
   def request(self,*args):Connection.sent=args
   def getresponse(self):return Response()
   def close(self):pass
  with patch.object(Path,'read_text',return_value='CANARY-DO-NOT-EXPOSE'),patch('backend.client.ssl.create_default_context') as tls,patch('backend.client.http.client.HTTPSConnection',Connection):
   import time
   c=QueryClient()
   with self.assertRaises(QueryError) as cm:c.query('test',time.monotonic()+5)
   self.assertNotIn('CANARY',str(cm.exception));self.assertEqual(Connection.sent[0:2],('POST','/select/logsql/query'));self.assertEqual(tls.call_count,1)
if __name__=='__main__':unittest.main()
