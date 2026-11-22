#!/usr/bin/python3
import gzip, html, urllib.parse, re, base64, hashlib, hmac, http.client, ipaddress, json, os, pathlib, shutil, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=pathlib.Path(os.environ.get('PS2_DOWNLOAD_STATE',str(pathlib.Path.home()/'.local/share/maizonas/downloads')))
DOWNLOADS=pathlib.Path(os.environ.get('PS2_DOWNLOAD_DIR',str(pathlib.Path.home()/'Downloads/MaizoNAS')))
DVD=pathlib.Path(os.environ.get('PS2_OPL_ROOT',str(pathlib.Path.home()/'PS2')))/'DVD'
MOVIES=pathlib.Path(os.environ.get('PS2_MOVIES_DIR',str(pathlib.Path.home()/'Filmes')))
APP=pathlib.Path(__file__).resolve().parent
CONFIG=json.loads((ROOT/'config.json').read_text())
LOCK=threading.Lock()

def rpc(method, params=None):
    params=list(params or [])
    if method=='system.multicall':
        for call in params[0]:
            args=call.setdefault('params',[])
            if args and isinstance(args[0],str) and args[0].startswith('token:'): args.pop(0)
            args.insert(0,'token:'+CONFIG['secret'])
    elif method.startswith('aria2.'):
        if params and isinstance(params[0],str) and params[0].startswith('token:'): params.pop(0)
        params.insert(0,'token:'+CONFIG['secret'])
    conn=http.client.HTTPConnection('127.0.0.1',int(os.environ.get('PS2_ARIA_RPC_PORT','6800')),timeout=30)
    try:
        conn.request('POST','/jsonrpc',json.dumps({'jsonrpc':'2.0','id':'ps2','method':method,'params':params}),{'Content-Type':'application/json'})
        return json.loads(conn.getresponse().read())
    finally: conn.close()

from manager import Manager
MANAGER=Manager(ROOT,DOWNLOADS,rpc)
from collection import Collection,Conflict,VIDEO_TYPES
COLLECTION=Collection(DVD.parent,MOVIES,pathlib.Path(os.environ.get('MAIZONAS_COLLECTION_STATE',str(ROOT.parent/'ps2-collection'))))

def record(gid,state,detail,files=None,category=None):
    with LOCK:
        p=ROOT/'imports.json'
        try: data=json.loads(p.read_text())
        except (FileNotFoundError,ValueError): data={}
        data[gid]={'state':state,'detail':detail,'files':files or [],'time':time.strftime('%Y-%m-%d %H:%M:%S')}
        if category:data[gid]['category']=category
        tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)); tmp.replace(p)

def inside(path,root):
    try: path.resolve().relative_to(root.resolve()); return True
    except ValueError: return False

def valid_image(path):
    with path.open('rb') as f:
        if path.suffix.lower()=='.zso': return f.read(4)==b'ZISO'
        f.seek(32768)
        block=f.read(2048)
        return b'CD001' in block or b'BEA01' in block

OPL_ROOT=DVD.parent
PASSWORD_FILE=ROOT/'archive-passwords.txt'
CONTENT_TYPES={
    'ART': {'.png','.jpg','.jpeg','.bmp','.ico'},
    'CFG': {'.cfg'}, 'CHT': {'.cht','.pnach','.txt'},
    'VMC': {'.bin','.vmc'},
    'THM': {'.cfg','.png','.jpg','.jpeg','.bmp','.ttf','.tar','.thm'},
    'APPS': {'.elf','.cfg','.png','.jpg','.ico','.icn'},
    'POPS': {'.vcd','.elf','.bin','.cfg','.txt'},
    'LNG': {'.lng','.ttf'},
    'CD': {'.iso','.zso'}, 'DVD': {'.iso','.zso'},
}

def passwords():
    try: lines=PASSWORD_FILE.read_text().splitlines()
    except FileNotFoundError: lines=[]
    return list(dict.fromkeys(['']+[v for v in lines if v]))

def destination(path,base,category='auto'):
    relative=path.relative_to(base)
    if any(part.startswith('.') or part in ('..','') for part in relative.parts): return None
    if path.suffix.lower() in VIDEO_TYPES or category=='movies' and path.suffix.lower()=='.iso':
        target=MOVIES/path.name
        if not inside(target,MOVIES) or target.is_symlink() or MOVIES.is_symlink():raise ValueError('Destino de filme inseguro')
        return target
    if category=='movies':return None
    folder=None
    for index,part in enumerate(relative.parts[:-1]):
        if part.upper() in CONTENT_TYPES:
            folder=part.upper(); tail=relative.parts[index+1:]; break
    if folder is None:
        if path.suffix.lower() not in ('.iso','.zso'): return None
        folder='DVD'; tail=(path.name,)
    if path.suffix.lower() not in CONTENT_TYPES[folder]: return None
    if folder in ('CD','DVD'): tail=(path.name,)
    target=OPL_ROOT/folder/Path(*tail)
    if not inside(target,OPL_ROOT) or target.is_symlink(): raise ValueError('Destino inseguro')
    # Refuse symlinked directories, even when the link points inside OPL_ROOT.
    for parent in (target.parent,*target.parent.parents):
        if parent==OPL_ROOT: break
        if parent.is_symlink(): raise ValueError('Pasta de destino contem link')
    return target

def import_file(path,base,category='auto'):
    target=destination(path,base,category)
    if target is None: return None
    if path.is_symlink(): raise ValueError('Arquivo de origem contem link')
    if path.suffix.lower() in ('.iso','.zso') and not valid_image(path):
        raise ValueError('Imagem ISO/ZSO invalida: '+path.name)
    if path.suffix.lower() in ('.mp4','.avi'):
        with path.open('rb') as f:header=f.read(16)
        valid=header[4:8]==b'ftyp' if path.suffix.lower()=='.mp4' else header[:4]==b'RIFF' and header[8:12]==b'AVI '
        if not valid:raise ValueError('Arquivo de vídeo inválido: '+path.name)
    if path.suffix.lower() in VIDEO_TYPES-{'.mp4','.avi'}:
        probe=subprocess.run(['ffprobe','-v','error','-select_streams','v','-show_entries','stream=codec_type','-of','json','--',str(path)],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30)
        try: valid=probe.returncode==0 and any(stream.get('codec_type')=='video' for stream in json.loads(probe.stdout).get('streams',[]))
        except (ValueError,TypeError): valid=False
        if not valid:raise ValueError('Arquivo de vídeo inválido: '+path.name)
    name='Filmes/'+target.name if inside(target,MOVIES) else str(target.relative_to(OPL_ROOT))
    if target.exists(): return (name,False)
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o775)
    fd,tmp=tempfile.mkstemp(prefix='.import-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as out, path.open('rb') as src:
            shutil.copyfileobj(src,out,1024*1024); out.flush(); os.fsync(out.fileno())
        os.chmod(tmp,0o664)
        try: os.link(tmp,target)
        except FileExistsError: return (name,False)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return (name,True)

def extract(archive,stage):
    errors=[]
    for index,password in enumerate(passwords()):
        listing=subprocess.run(['7z','l','-slt','-ba','-p'+password,'--',str(archive)],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120)
        if listing.returncode:
            errors.append('listagem'); continue
        encrypted='Encrypted = +' in listing.stdout
        for line in listing.stdout.splitlines():
            key,separator,value=line.partition(' = ')
            explicit_link=key in ('Symbolic Link','Hard Link') and bool(value.strip())
            unix_link=key=='Attributes' and any(token.startswith('l') for token in value.split())
            if explicit_link or unix_link:
                raise ValueError('Arquivo compactado contem links; extracao recusada')
            if line.startswith('Path = '):
                value=line[7:].replace('\\','/')
                if value.startswith('/') or '..' in pathlib.PurePosixPath(value).parts or ':' in value:
                    raise ValueError('Caminho inseguro no arquivo compactado')
        # Each password attempt gets its own directory; partial failed files never get imported.
        attempt=stage/('attempt-'+str(index)); attempt.mkdir()
        result=subprocess.run(['7z','x','-y','-p'+password,'-o'+str(attempt),'--',str(archive)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if result.returncode:
            shutil.rmtree(attempt);errors.append('extracao')
            if encrypted: continue
            raise ValueError('Arquivo danificado ou partes ausentes: '+archive.name)
        for item in attempt.rglob('*'):
            if item.is_symlink() or not inside(item,attempt): raise ValueError('Link inseguro na extracao')
        return sorted(item for item in attempt.rglob('*') if item.is_file())
    raise ValueError('Nao foi possivel extrair '+archive.name+'. Nenhuma senha da lista funcionou, ou o arquivo esta incompleto/danificado. Atualize a lista de senhas e tente novamente.')

def process(gid):
    tasks=ROOT/'tasks';tasks.mkdir(exist_ok=True)
    saved=tasks/(gid+'.json')
    reply=rpc('aria2.getFiles',[gid])
    if 'error' in reply:
        if not saved.exists(): raise ValueError(reply['error']['message'])
        files=[Path(p) for p in json.loads(saved.read_text())]
    else:
        files=[Path(f['path']) for f in reply['result'] if f.get('selected')=='true']
    if not files or any(not inside(p,DOWNLOADS) or p.is_symlink() for p in files):
        raise ValueError('Download fora da pasta PS2-Automatico ou sem arquivos selecionados')
    saved.write_text(json.dumps([str(p) for p in files]))
    category=MANAGER.category_for(gid)
    record(gid,'extraindo','Preparando arquivos e testando a lista de senhas, se necessario',category=category)
    copied=[];skipped=[]
    def publish(path,base):
        result=import_file(path,base,category)
        if result:
            (copied if result[1] else skipped).append(result[0])
    with tempfile.TemporaryDirectory(prefix=gid+'-',dir=ROOT/'work') as stage_name:
        for index,p in enumerate(files):
            if not p.is_file(): continue
            suffix=p.suffix.lower()
            archive=suffix in ('.zip','.7z','.rar') or p.name.lower().endswith(('.7z.001','.zip.001'))
            if not archive:
                publish(p,DOWNLOADS);continue
            part=re.search(r'\.part(\d+)\.rar$',p.name,re.I)
            if part and int(part.group(1))!=1: continue
            stage=Path(stage_name)/str(index);stage.mkdir()
            for item in extract(p,stage):
                publish(item,stage)
    if not copied and not skipped: raise ValueError('Nenhum arquivo compatível encontrado. Filmes: arquivos de vídeo (MP4, AVI, MKV, MPG, MOV, WebM e outros) ou ISO marcada como filme. Jogos: formatos do OPL. CSO e BIN/CUE precisam de tratamento separado.')
    detail='Importacao concluida. '+str(len(copied))+' arquivo(s) importado(s); '+str(len(skipped))+' existente(s) preservado(s). Originais mantidos em Downloads/PS2-Automatico.'
    imported=copied+skipped
    kind='movies' if imported and all(n.startswith('Filmes/') for n in imported) else 'mixed' if any(n.startswith('Filmes/') for n in imported) else 'games'
    record(gid,'pronto',detail,copied,kind)
    COLLECTION.last_scan=0


def worker(stop):
    while not stop.wait(2):
        for item in sorted((ROOT/'queue').glob('*.json')):
            gid=item.stem
            try:
                process(gid)
            except Exception as e: record(gid,'erro',str(e))
            finally: item.unlink(missing_ok=True)

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        if not self.authorized():return
        parsed=urllib.parse.urlsplit(self.path)
        if parsed.path!='/api/collection/file':return self.send_error(404)
        try:COLLECTION.send_file(self,urllib.parse.parse_qs(parsed.query).get('id',[''])[0],head=True)
        except ValueError as e:self.send_error(404,str(e))
    def authorized(self):
        addr=ipaddress.ip_address(self.client_address[0])
        allowed=addr.is_loopback or any(addr in ipaddress.ip_network(network) for network in ('192.168.0.0/24','100.64.0.0/10'))
        expected='Basic '+base64.b64encode(('ps2:'+CONFIG['password']).encode()).decode()
        if not allowed:
            self.send_error(403); return False
        if not hmac.compare_digest(self.headers.get('Authorization',''),expected):
            self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="Downloads PS2"'); self.end_headers(); return False
        return True
    def send_data(self,data,kind='application/json',code=200):
        compressed='gzip' in self.headers.get('Accept-Encoding','') and len(data)>1024 and (kind.startswith('text/') or kind in ('application/json','image/svg+xml'))
        if compressed: data=gzip.compress(data,compresslevel=4)
        self.send_response(code)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('Vary','Accept-Encoding')
        if compressed: self.send_header('Content-Encoding','gzip')
        self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError): pass
    def password_page(self,message=''):
        try: saved=PASSWORD_FILE.read_text()
        except FileNotFoundError: saved=''
        try: imports=json.loads((ROOT/'imports.json').read_text())
        except (FileNotFoundError,ValueError): imports={}
        failed=''.join('<li>'+html.escape(v.get('detail',''))+' <form method="post" action="/retry"><input type="hidden" name="gid" value="'+html.escape(gid)+'"><button>Tentar novamente</button></form></li>' for gid,v in imports.items() if v.get('state')=='erro' and re.fullmatch('[0-9a-f]{16}',gid))
        body='<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Senhas dos arquivos</title><style>body{font:17px sans-serif;max-width:680px;margin:24px auto;padding:0 16px;background:#101827;color:#eee}a{color:#8bc9ff}textarea{box-sizing:border-box;width:100%;height:240px;font:16px monospace;padding:12px}button{font-size:17px;padding:12px;margin:12px 0}li{margin-bottom:20px}</style><a href="/downloads">← Downloads</a><h1>Senhas dos arquivos</h1><p>Uma senha por linha. Cada arquivo é tentado sem senha e depois com as senhas desta lista. Se nenhuma funcionar, o original é mantido.</p>'
        body+='<p>'+html.escape(message)+'</p><form method="post" action="/passwords"><textarea name="passwords" autocomplete="off" spellcheck="false">'+html.escape(saved)+'</textarea><button>Salvar senhas</button></form><h2>Importacoes com erro</h2><ul>'+failed+'</ul></html>'
        self.send_data(body.encode(),'text/html; charset=utf-8')
    def do_GET(self):
        if not self.authorized(): return
        path=self.path.split('?',1)[0]
        if path in ('/collection','/collection/'):
            return self.send_data((APP/'web/collection.html').read_bytes(),'text/html; charset=utf-8')
        if path in ('/collection.js','/collection.css'):
            name=path[1:];return self.send_data((APP/'web'/name).read_bytes(),'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8')
        if path.startswith('/api/collection'):
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                if path=='/api/collection':return self.send_data(json.dumps(COLLECTION.list(query.get('refresh')==['1']),ensure_ascii=False).encode())
                if path=='/api/collection/cover':
                    body,kind=COLLECTION.cover(query.get('id',[''])[0]);return self.send_data(body,kind)
                if path=='/api/collection/file':return COLLECTION.send_file(self,query.get('id',[''])[0])
            except ValueError as e:return self.send_data(json.dumps({'error':str(e)}).encode(),code=404)
            return self.send_error(404)
        if path=='/':
            body=(APP/'web/lite.html').read_bytes()
            return self.send_data(body,'text/html; charset=utf-8')
        if path in ('/ui/','/ui/index.html'):
            body=(APP/'web/index.html').read_text()
            link='<a href="/passwords" style="position:fixed;bottom:6px;right:10px;z-index:9999;background:#163452;color:white;padding:8px 12px;border-radius:8px">Senhas dos arquivos</a>'
            return self.send_data(body.replace('</body>',link+'</body>').encode(),'text/html; charset=utf-8')
        if path=='/api/state': return self.send_data(json.dumps(MANAGER.state(),ensure_ascii=False).encode())
        if path=='/passwords': return self.password_page()
        if path=='/imports':
            try: body=(ROOT/'imports.json').read_bytes()
            except FileNotFoundError: body=b'{}'
            return self.send_data(body,'application/json; charset=utf-8')
        self.send_error(404)
    def do_POST(self):
        if not self.authorized(): return
        if self.path.startswith('/api/collection/'):
            origin=self.headers.get('Origin')
            if origin and urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host'):return self.send_error(403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=12*1024*1024:return self.send_error(413)
                data=json.loads(self.rfile.read(length));item=data.get('id','')
                if self.path=='/api/collection/preview':result=COLLECTION.preview(item,data.get('title'),data.get('category'))
                elif self.path=='/api/collection/update':result=COLLECTION.update(item,data.get('title'),data.get('rename',True),data.get('category'))
                elif self.path=='/api/collection/cover':result=COLLECTION.upload_cover(item,data.get('data'),data.get('applyOpl',False))
                elif self.path=='/api/collection/scan':result=COLLECTION.list(True)
                else:return self.send_error(404)
                return self.send_data(json.dumps(result,ensure_ascii=False).encode())
            except Conflict as e:return self.send_data(json.dumps({'error':str(e)},ensure_ascii=False).encode(),code=409)
            except (ValueError,TypeError,KeyError) as e:return self.send_data(json.dumps({'error':str(e)},ensure_ascii=False).encode(),code=400)
            except OSError as e:return self.send_data(json.dumps({'error':'Não foi possível acessar o arquivo: '+str(e)},ensure_ascii=False).encode(),code=409)
        if self.path in ('/passwords','/retry'):
            # Accept forms only from this origin; require the same browser authorization.
            origin=self.headers.get('Origin')
            if origin and urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host'): return self.send_error(403)
            try: length=int(self.headers.get('Content-Length','0'))
            except ValueError: return self.send_error(400)
            if not 0<length<=131072: return self.send_error(413)
            form=urllib.parse.parse_qs(self.rfile.read(length).decode(),keep_blank_values=True)
            if self.path=='/passwords':
                value=form.get('passwords',[''])[0].replace('\r\n','\n').replace('\r','\n')
                temp=PASSWORD_FILE.with_suffix('.tmp')
                with open(temp,'w',opener=lambda p,f:os.open(p,f,0o600)) as out: out.write(value)
                temp.chmod(0o600);temp.replace(PASSWORD_FILE)
                return self.password_page('Lista salva. Ela sera usada nas proximas extracoes. Para arquivos que falharam, toque em Tentar novamente.')
            gid=form.get('gid',[''])[0]
            if not re.fullmatch('[0-9a-f]{16}',gid): return self.send_error(400)
            record(gid,'aguardando','Nova tentativa solicitada')
            (ROOT/'queue'/(gid+'.json')).write_text(json.dumps({'gid':gid}))
            return self.password_page('Nova tentativa adicionada a fila.')
        if self.path!='/jsonrpc': return self.send_error(404)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16*1024*1024: return self.send_error(413)
            data=json.loads(self.rfile.read(length))
            method=data['method'];params=data.get('params',[])
            if method.startswith('manager.'):
                origin=self.headers.get('Origin')
                if origin and urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host'): return self.send_error(403)
                actions={
                    'manager.replaceLink':MANAGER.replace,
                    'manager.retry':MANAGER.retry,
                    'manager.add':MANAGER.add,
                    'manager.addTorrent':MANAGER.add_torrent,
                    'manager.cancel':MANAGER.cancel,
                    'manager.settings':MANAGER.settings,
                }
                try:
                    if method=='manager.category':
                        gid,category=params[0],params[1]
                        statuses=json.loads((ROOT/'imports.json').read_text()) if (ROOT/'imports.json').exists() else {}
                        if statuses.get(gid,{}).get('state')=='extraindo':raise ValueError('A importação está em andamento; aguarde para mudar o destino.')
                        result=MANAGER.category(gid,category)
                        if MANAGER.task(gid).get('status')=='complete':
                            record(gid,'aguardando','Importação para o novo destino solicitada',category=category)
                            (ROOT/'queue'/(gid+'.json')).write_text(json.dumps({'gid':gid}))
                            result['message']+=' Importação adicionada à fila; cópias anteriores serão preservadas.'
                    elif method=='manager.retryImport':
                        gid=params[0]
                        if not re.fullmatch('[0-9a-f]{16}',gid):raise ValueError('Tarefa invalida')
                        imports_path=ROOT/'imports.json'
                        statuses=json.loads(imports_path.read_text()) if imports_path.exists() else {}
                        if statuses.get(gid,{}).get('state')=='extraindo':raise ValueError('A extracao ja esta em andamento')
                        MANAGER.task(gid)
                        record(gid,'aguardando','Nova tentativa de importacao solicitada')
                        (ROOT/'queue'/(gid+'.json')).write_text(json.dumps({'gid':gid}))
                        result={'message':'Extracao adicionada a fila.'}
                    elif method=='manager.source':
                        task=MANAGER.task(params[0]);result={'sourcePage':task.get('sourcePage',''),'sourceUrl':task.get('sourceUrl','') or next((u['uri'] for f in task.get('files',[]) for u in f.get('uris',[])), '')}
                    elif method in ('manager.pauseAll','manager.resumeAll'):
                        MANAGER.call('aria2.pauseAll' if method.endswith('pauseAll') else 'aria2.unpauseAll')
                        result={'message':'Fila pausada.' if method.endswith('pauseAll') else 'Fila retomada.'}
                    elif method in actions:result=actions[method](*params)
                    else:raise ValueError('Acao desconhecida')
                    try:MANAGER.update()
                    except Exception:pass
                    reply={'jsonrpc':'2.0','result':result,'id':data.get('id')}
                except (ValueError,TypeError,IndexError) as error:
                    reply={'jsonrpc':'2.0','error':{'code':-32602,'message':str(error)},'id':data.get('id')}
            else:
                reply=rpc(method,params);reply['id']=data.get('id')
            self.send_data(json.dumps(reply).encode())
        except Exception as e: self.send_data(json.dumps({'error':str(e)}).encode(),code=502)
    def log_message(self,fmt,*args): pass

def main():
    if '--daemon' in sys.argv:
        if os.fork(): return
        os.setsid()
        if os.fork(): os._exit(0)
        inp=os.open('/dev/null',os.O_RDONLY); out=os.open(ROOT/'service.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        os.dup2(inp,0); os.dup2(out,1); os.dup2(out,2)
    (ROOT/'service.pid').write_text(str(os.getpid()))
    stop=threading.Event()
    child=subprocess.Popen(['aria2c','--conf-path='+str(ROOT/'aria2.conf')])
    ThreadingHTTPServer.request_queue_size=64
    server=ThreadingHTTPServer(('0.0.0.0',8088),Handler)
    threading.Thread(target=worker,args=(stop,),daemon=True).start()
    threading.Thread(target=MANAGER.watch,args=(stop,),daemon=True).start()
    def shutdown(signum,frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,shutdown)
    try:
        server.timeout=2
        while child.poll() is None: server.handle_request()
    except KeyboardInterrupt: pass
    finally:
        stop.set(); server.server_close()
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=20)
            except subprocess.TimeoutExpired: child.kill()
        (ROOT/'service.pid').unlink(missing_ok=True)
if __name__=='__main__': main()
