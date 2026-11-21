"""Fixed-origin HTTPS query transport. No redirects, arbitrary endpoints or mutations."""
import http.client,json,logging,os,ssl,threading,time,urllib.parse
from pathlib import Path
log=logging.getLogger('visibility.client')
class QueryError(Exception):pass
class QueryClient:
    def __init__(self):
        self.host=os.getenv('TELEMETRY_API_HOST','192.168.5.230')
        self.port=int(os.getenv('TELEMETRY_API_PORT','9429'))
        self.ca=Path(os.getenv('TELEMETRY_CA_FILE','/run/visibility/telemetry-ca.crt'))
        self.token_path=Path(os.getenv('TELEMETRY_TOKEN_FILE','/run/visibility/query-token'))
        self.slots=threading.BoundedSemaphore(4)
        self._tls_lock=threading.Lock()
        self._tls_key=None
        self._tls_context=None
    def _ssl_context(self):
        try:
            st=self.ca.stat()
            key=(str(self.ca),st.st_mtime_ns,st.st_size,st.st_ino)
        except OSError:
            return ssl.create_default_context(cafile=str(self.ca))
        with self._tls_lock:
            if self._tls_context is None or self._tls_key!=key:
                self._tls_context=ssl.create_default_context(cafile=str(self.ca))
                self._tls_key=key
            return self._tls_context
    def query(self,query,deadline):
        remaining=deadline-time.monotonic()
        if remaining<=0 or not self.slots.acquire(timeout=max(0,remaining)):
            log.warning('telemetry query rejected: budget or concurrency slots exhausted')
            raise QueryError('Query budget exhausted')
        c=None
        try:
            token=self.token_path.read_text().strip()
            if not token or len(token)>8192 or any(x.isspace() for x in token):raise QueryError('Credential unavailable')
            context=self._ssl_context()
            remaining=deadline-time.monotonic()
            if remaining<=0:raise QueryError('Query budget exhausted')
            c=http.client.HTTPSConnection(self.host,self.port,context=context,timeout=min(8,remaining))
            body=urllib.parse.urlencode({'query':query,'timeout':str(min(7,max(.1,remaining)))+'s'}).encode()
            c.request('POST','/select/logsql/query',body,{'Authorization':'Bearer '+token,'Content-Type':'application/x-www-form-urlencoded'})
            response=c.getresponse()
            if response.status!=200:
                log.warning('telemetry query returned HTTP %s',response.status)
                raise QueryError('Query unavailable')
            chunks=[];total=0
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise QueryError('Query budget exhausted')
                if c.sock:c.sock.settimeout(min(8,remaining))
                chunk=response.read1(65536)
                if not chunk:break
                total+=len(chunk)
                if total>8*1024*1024:raise QueryError('Response limit exceeded')
                chunks.append(chunk)
            rows=[json.loads(line) for line in b''.join(chunks).splitlines() if line.strip()]
            if len(rows)>10001:raise QueryError('Row limit exceeded')
            return rows
        except QueryError as exc:
            log.warning('telemetry query failed: %s',exc)
            raise QueryError('Telemetry query unavailable or exceeds its budget') from None
        except Exception as exc:
            log.warning('telemetry query failed: %s',type(exc).__name__)
            raise QueryError('Telemetry query unavailable or exceeds its budget') from None
        finally:
            if c:c.close()
            self.slots.release()
