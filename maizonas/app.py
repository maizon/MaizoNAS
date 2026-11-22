"""Single authenticated HTTP origin for collection, downloader, converter and settings."""
import importlib.util,io,json,os,pathlib,signal,socket,threading,time,urllib.parse,subprocess,sys
from . import config as cfg
APP=pathlib.Path(__file__).parent
SETTINGS=cfg.load()
p=SETTINGS['paths']
os.environ.update(PS2_DOWNLOAD_STATE=p['state'],PS2_DOWNLOAD_DIR=p['downloads'],PS2_OPL_ROOT=p['games'],PS2_MOVIES_DIR=p['movies'],PS2_ARIA_RPC_PORT=str(SETTINGS['rpc_port']),MAIZONAS_COLLECTION_STATE=p['collection_state'],FILMES_DIR=p['movies'],FILMES_STATE=p['converter_state'],FILMES_AUTH_CONFIG=str(pathlib.Path(p['state'])/'config.json'),FILMES_ENGINE=SETTINGS['converter']['engine'])
sys.path.insert(0,str(APP/'legacy'))
import service as legacy
spec=importlib.util.spec_from_file_location('maizonas_video',APP/'converter/server.py');video=importlib.util.module_from_spec(spec);spec.loader.exec_module(video)

def admin(method,body=None):
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
  s.settimeout(90 if method in ('settings.save','samba.restart','samba.test','network.confirm') else 15);s.connect(os.environ.get('MAIZONAS_SOCKET','/run/maizonas/admin.sock'));s.sendall(json.dumps({'method':method,'body':body or {}}).encode()+b'\n');data=b''
  while not data.endswith(b'\n'):
   chunk=s.recv(65536)
   if not chunk:break
   data+=chunk
   if len(data)>2*1024*1024:raise ValueError('Resposta administrativa muito grande.')
  reply=json.loads(data)
  if 'error' in reply:raise ValueError(reply['error'])
  return reply['result']

class Handler(legacy.Handler,video.Handler):
 def authorized(self):
  import ipaddress
  try:
   addr=ipaddress.ip_address(self.client_address[0]);allowed=addr.is_loopback or addr.is_private or addr in ipaddress.ip_network('100.64.0.0/10')
   if not allowed:return self.send_error(403) or False
  except ValueError:return False
  if cfg.authorized(self.headers.get('Authorization',''),cfg.load()):return True
  self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="MaizoNAS", charset="UTF-8"');self.send_header('Content-Length','0');self.end_headers();return False
 def send_data(self,data,kind='application/json',code=200):
  if kind.startswith('text/html') and b'/shell.js' not in data:
   assets=b'<link rel="stylesheet" href="/shell.css"><script src="/shell.js" defer></script>'
   data=data.replace(b'</html>',assets+b'</html>') if b'</html>' in data else data+assets
  return legacy.Handler.send_data(self,data,kind,code)
 def guard(self):return self.authorized()
 def reply(self,value,status=200):return self.send_data(json.dumps(value,ensure_ascii=False).encode(),'application/json; charset=utf-8',code=status)
 def do_GET(self):
  if not self.authorized():return
  path=urllib.parse.urlsplit(self.path).path
  if path=='/api/admin/status':
   try:return self.reply(admin('status'))
   except (OSError,ValueError) as error:return self.reply({'error':'O serviço administrativo está indisponível: '+str(error)},503)
  if path=='/api/admin/logs':
   try:return self.reply(admin('logs'))
   except (OSError,ValueError) as error:return self.reply({'error':str(error)},503)
  if path in ('/settings','/settings/'):
   return self.send_data((APP/'web/settings.html').read_bytes(),'text/html; charset=utf-8')
  static={'/settings.js':('settings.js','text/javascript'),'/shell.js':('shell.js','text/javascript'),'/shell.css':('shell.css','text/css'),'/settings.css':('settings.css','text/css')}
  if path in static:
   file,kind=static[path];return self.send_data((APP/'web'/file).read_bytes(),kind+'; charset=utf-8')
  if path=='/convert':return self.send_data((APP/'converter/web/index.html').read_bytes(),'text/html; charset=utf-8')
  if path.startswith('/converter/'):
   self.path='/'+path.split('/converter/',1)[1];return video.Handler.do_GET(self)
  if path.startswith('/api/converter/'):
   self.path=self.path.replace('/api/converter/','/api/',1);return video.Handler.do_GET(self)
  if path in ('/','/collection','/collection/'):
   self.path='/collection';return legacy.Handler.do_GET(self)
  if path in ('/downloads','/downloads/'):
   self.path='/';return legacy.Handler.do_GET(self)
  if path.startswith('/ui'):
   self.send_response(302);self.send_header('Location','/downloads');self.send_header('Content-Length','0');self.end_headers();return
  return legacy.Handler.do_GET(self)
 def do_POST(self):
  if not self.authorized():return
  origin=self.headers.get('Origin')
  if origin and urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host'):return self.reply({'error':'Origem inválida.'},403)
  if self.path.startswith('/api/admin/'):
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=65536 or self.headers.get_content_type()!='application/json':raise ValueError('Requisição inválida.')
    body=json.loads(self.rfile.read(length));methods={'/api/admin/network/plan':'network.plan','/api/admin/network/apply':'network.apply','/api/admin/network/confirm':'network.confirm','/api/admin/settings':'settings.save','/api/admin/samba/restart':'samba.restart','/api/admin/samba/test':'samba.test','/api/admin/dependencies':'dependencies.repair'}
    if self.path not in methods:raise ValueError('Operação desconhecida.')
    return self.reply(admin(methods[self.path],body))
   except (ValueError,OSError) as error:return self.reply({'error':str(error)},400)
  if self.path.startswith('/api/converter/'):
   self.path=self.path.replace('/api/converter/','/api/',1);return video.Handler.do_POST(self)
  if self.path=='/jsonrpc':
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=16*1024*1024:raise ValueError('Requisição inválida.')
    raw=self.rfile.read(length);request=json.loads(raw)
    if not isinstance(request,dict) or not str(request.get('method','')).startswith('manager.'):raise ValueError('Use os métodos do gerenciador. RPC arbitrário não é permitido.')
    self.rfile=io.BytesIO(raw)
   except (ValueError,TypeError) as error:return self.reply({'error':str(error)},400)
  return legacy.Handler.do_POST(self)

class Redirect(legacy.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  host=self.headers.get('Host','localhost').rsplit(':',1)[0];self.send_response(302);self.send_header('Location','http://'+host+':'+str(SETTINGS['web_port'])+'/convert');self.send_header('Content-Length','0');self.end_headers()

def main():
 video.initialize();stop=threading.Event()
 child=subprocess.Popen(['aria2c','--conf-path='+str(legacy.ROOT/'aria2.conf')],stdin=subprocess.DEVNULL)
 server=legacy.ThreadingHTTPServer(('0.0.0.0',SETTINGS['web_port']),Handler);server.request_queue_size=64
 for target,args in [(legacy.worker,(stop,)),(legacy.MANAGER.watch,(stop,)),(video.worker,())]:threading.Thread(target=target,args=args,daemon=True).start()
 redirect=None
 if SETTINGS.get('legacy_converter_redirect') and SETTINGS['web_port']!=8090:
  try:redirect=legacy.ThreadingHTTPServer(('0.0.0.0',8090),Redirect);threading.Thread(target=redirect.serve_forever,daemon=True).start()
  except OSError:pass
 def shutdown(*args):stop.set();video.STOP.set();threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
 try:server.serve_forever(poll_interval=.5)
 finally:
  stop.set();video.STOP.set();server.server_close()
  if redirect:redirect.shutdown();redirect.server_close()
  try:legacy.rpc('aria2.saveSession')
  except Exception:pass
  child.terminate()
  try:child.wait(timeout=15)
  except subprocess.TimeoutExpired:child.kill();child.wait()

if __name__=='__main__':main()
