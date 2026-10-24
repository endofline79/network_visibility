"""Optional viewer authentication; credentials are provisioned separately after approval."""
import hashlib,hmac,json,os,threading,time
from pathlib import Path
from pydantic import BaseModel,ConfigDict,Field
from fastapi import HTTPException,Request
class Login(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(max_length=80)
    password:str=Field(max_length=512)
class Viewer:
    def __init__(self,path):
        d=json.loads(Path(path).read_text())
        self.username=d['username'];self.salt=bytes.fromhex(d['salt']);self.digest=bytes.fromhex(d['password_hash']);self.secret=d['session_secret']
        if not isinstance(self.username,str) or not self.username or len(self.salt)<16 or len(self.digest)!=32 or len(self.secret)<43:raise ValueError('Invalid viewer configuration')
        self.attempts={};self.lock=threading.Lock()
    def verify(self,ip,username,password):
        now=time.monotonic()
        with self.lock:
            self.attempts={k:v for k,v in self.attempts.items() if now-v[0]<60}
            first,n=self.attempts.get(ip,(now,0))
            if n>=5 or len(self.attempts)>=1024:raise HTTPException(429,'Too many login attempts. Try again in a minute.')
            self.attempts[ip]=(first,n+1)
        calculated=hashlib.pbkdf2_hmac('sha256',password.encode(),self.salt,600000)
        ok=hmac.compare_digest(calculated,self.digest) & hmac.compare_digest(username.encode(),self.username.encode())
        if ok:
            with self.lock:self.attempts.pop(ip,None)
        return ok

def same_origin(request):
    expected=str(request.base_url).rstrip('/')
    if request.headers.get('origin')!=expected or request.headers.get('content-type','').split(';')[0]!='application/json':
        raise HTTPException(403,'A same-origin JSON request is required')
