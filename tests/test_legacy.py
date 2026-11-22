"""Isolated end-to-end tests: real aria2, completion hook, import worker and HTTP API.

All downloaded media, catalogue data and rename/cover tests live inside TemporaryDirectory.
"""
import base64,functools,hashlib,io,json,os,socket,struct,subprocess,sys,tempfile,threading,time,unittest,urllib.error,urllib.parse,urllib.request,zipfile
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'maizonas/legacy'
def free_port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='collection-test-');cls.root=Path(cls.tmp.name);root=cls.root;cls.state=root/'downloads-state';cls.downloads=root/'downloads';cls.opl=root/'OPL';cls.movies=root/'Filmes'
  for p in [cls.state,cls.state/'queue',cls.state/'tasks',cls.state/'work',cls.downloads,cls.opl/'DVD',cls.opl/'CD',cls.opl/'ART',cls.opl/'CFG',root/'fixtures']:p.mkdir(parents=True,exist_ok=True)
  cls.port=free_port();cls.secret='isolated-test-secret';cls.password='isolated-test-password';(cls.state/'config.json').write_text(json.dumps({'secret':cls.secret,'password':cls.password}));(cls.state/'aria2.conf').write_text('')
  os.environ.update({'PS2_DOWNLOAD_STATE':str(cls.state),'PS2_DOWNLOAD_DIR':str(cls.downloads),'PS2_OPL_ROOT':str(cls.opl),'PS2_MOVIES_DIR':str(cls.movies),'PS2_ARIA_RPC_PORT':str(cls.port)})
  sys.path.insert(0,str(APP));import service;cls.service=service
  cls.aria_log=(root/'aria.log').open('wb');cls.aria=subprocess.Popen(['aria2c','--enable-rpc=true','--rpc-listen-all=false','--rpc-listen-port='+str(cls.port),'--rpc-secret='+cls.secret,'--dir='+str(cls.downloads),'--allow-overwrite=false','--auto-file-renaming=false','--file-allocation=none','--seed-time=0','--save-session='+str(root/'session.txt'),'--on-download-complete='+str(APP/'completed.py')],stdout=cls.aria_log,stderr=subprocess.STDOUT)
  for _ in range(100):
   try:service.rpc('aria2.getVersion');break
   except OSError:time.sleep(.05)
  else:raise RuntimeError('Test aria2 did not start')
  class Quiet(SimpleHTTPRequestHandler):
   def log_message(self,*args):pass
  cls.source=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root/'fixtures')));threading.Thread(target=cls.source.serve_forever,daemon=True).start();cls.base=f'http://127.0.0.1:{cls.source.server_port}/'
  cls.http=ThreadingHTTPServer(('127.0.0.1',0),service.Handler);threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.url=f'http://127.0.0.1:{cls.http.server_port}'
  cls.stop=threading.Event();cls.workers=[threading.Thread(target=service.worker,args=(cls.stop,),daemon=True),threading.Thread(target=service.MANAGER.watch,args=(cls.stop,),daemon=True)]
  for t in cls.workers:t.start()
  cls.auth='Basic '+base64.b64encode(('ps2:'+cls.password).encode()).decode()
 @classmethod
 def tearDownClass(cls):
  cls.stop.set()
  for t in cls.workers:t.join(timeout=5)
  cls.http.shutdown();cls.http.server_close();cls.source.shutdown();cls.source.server_close();cls.aria.terminate();cls.aria.wait(timeout=15);cls.aria_log.close();cls.tmp.cleanup()
 def request(self,path,data=None,headers=None,method=None,auth=True):
  h={'Authorization':self.auth} if auth else {}
  h.update(headers or {})
  if data is not None:h['Content-Type']='application/json';data=json.dumps(data).encode()
  return urllib.request.urlopen(urllib.request.Request(self.url+path,data=data,headers=h,method=method),timeout=15)
 def api(self,path,data=None):
  with self.request(path,data) as r:return json.load(r)
 def rpc(self,name,params):
  d=self.api('/jsonrpc',{'jsonrpc':'2.0','id':1,'method':name,'params':params});self.assertNotIn('error',d,d);return d['result']
 def fixture(self,name,kind):
  p=self.root/'fixtures'/name
  if kind=='iso':
   b=bytearray(96*1024);b[32768:32775]=b'\x01CD001\x01';p.write_bytes(b)
  elif kind=='mp4':p.write_bytes(b'\0\0\0\x18ftypmp42'+b'\0'*5000)
  elif kind=='avi':p.write_bytes(b'RIFF'+struct.pack('<I',5000)+b'AVI '+b'\0'*5000)
  return p
 def add_wait(self,name,category='auto'):
  result=self.rpc('manager.add',[[self.base+urllib.parse.quote(name)],'',category]);gid=result['gids'][0]
  for _ in range(160):
   statuses=json.loads((self.state/'imports.json').read_text()) if (self.state/'imports.json').exists() else {};s=statuses.get(gid,{})
   if s.get('state')=='erro':self.fail(s['detail'])
   if s.get('state')=='pronto':return gid,s
   time.sleep(.1)
  self.fail('Timed out waiting for download/import: '+name)
 def test_01_authentication(self):
  for path in ['/collection','/api/collection']:
   with self.assertRaises(urllib.error.HTTPError) as c:self.request(path,auth=False)
   self.assertEqual(c.exception.code,401)
  with self.request('/collection') as r:self.assertIn(b'/collection.js',r.read())
 def test_02_film_iso_goes_only_to_filmes(self):
  self.fixture('Filme de teste.iso','iso');gid,s=self.add_wait('Filme de teste.iso','movies');self.assertTrue((self.movies/'Filme de teste.iso').is_file());self.assertFalse((self.opl/'DVD/Filme de teste.iso').exists());self.assertEqual(s['category'],'movies');self.assertEqual(self.service.MANAGER.task(gid)['category'],'movies')
 def test_03_mp4_avi_automatic_and_game_iso(self):
  for name,kind in [('Video.mp4','mp4'),('Video antigo.avi','avi')]:
   self.fixture(name,kind);self.add_wait(name);self.assertTrue((self.movies/name).is_file());self.assertFalse((self.opl/'DVD'/name).exists())
  name='SLUS_123.45.Jogo de teste.iso';self.fixture(name,'iso');self.add_wait(name);self.assertTrue((self.opl/'DVD'/name).is_file());self.assertFalse((self.movies/name).exists())
 def test_04_movie_archive(self):
  iso=self.fixture('Empacotado.iso','iso');avi=self.fixture('Empacotado.avi','avi')
  with zipfile.ZipFile(self.root/'fixtures/Pacote.zip','w') as z:z.write(iso,'pasta/Empacotado.iso');z.write(avi,'pasta/Empacotado.avi')
  self.add_wait('Pacote.zip','movies');self.assertTrue((self.movies/'Empacotado.iso').exists());self.assertTrue((self.movies/'Empacotado.avi').exists())
 def test_05_collection_rename_cover_and_collision(self):
  listing=self.api('/api/collection?refresh=1');game=next(i for i in listing['items'] if i['serial']=='SLUS_123.45');ident=game['id'];original=self.opl/'DVD'/game['filename'];sha=hashlib.sha256(original.read_bytes()).hexdigest();cache=self.opl/'DVD/games.bin';cache.write_bytes(b'original cache')
  proposed=self.api('/api/collection/preview',{'id':ident,'title':'Nome correto'});self.assertEqual(proposed['filename'],'SLUS_123.45.Nome correto.iso')
  answer=self.api('/api/collection/update',{'id':ident,'title':'Nome correto','rename':True});new=self.opl/'DVD'/answer['item']['filename'];self.assertFalse(original.exists());self.assertEqual(hashlib.sha256(new.read_bytes()).hexdigest(),sha);self.assertFalse(cache.exists());self.assertTrue(any('games.bin' in p.name for p in (self.service.COLLECTION.state/'backups').iterdir()))
  image=Image.new('RGB',(180,270),'green');buf=io.BytesIO();image.save(buf,'PNG');payload=base64.b64encode(buf.getvalue()).decode();answer=self.api('/api/collection/cover',{'id':ident,'data':payload,'applyOpl':True});self.assertTrue(answer['item']['hasCover']);self.assertTrue((self.opl/'ART/SLUS_123.45_COV.png').exists())
  with self.request(answer['item']['cover']) as r:self.assertEqual(r.headers['Content-Type'],'image/webp');self.assertGreater(len(r.read()),30)
  self.api('/api/collection/cover',{'id':ident,'data':payload,'applyOpl':True});self.assertTrue(any('COV.png' in p.name for p in (self.service.COLLECTION.state/'backups').iterdir()))
  target=self.opl/'DVD/SLUS_123.45.Colisão.iso';target.write_bytes(b'preserve')
  with self.assertRaises(urllib.error.HTTPError) as c:self.api('/api/collection/update',{'id':ident,'title':'Colisão'})
  self.assertEqual(c.exception.code,409);self.assertEqual(target.read_bytes(),b'preserve');self.assertTrue(new.exists())
  for title in ['../escape','a/b','', 'x'*171]:
   with self.assertRaises(urllib.error.HTTPError):self.api('/api/collection/preview',{'id':ident,'title':title})
 def test_06_resumable_download_and_head(self):
  item=next(i for i in self.api('/api/collection')['items'] if i['category']=='movies');path=self.movies/item['filename']
  with self.request(item['download'],headers={'Range':'bytes=4-19'}) as r:self.assertEqual(r.status,206);self.assertEqual(r.read(),path.read_bytes()[4:20])
  with self.request(item['download'],method='HEAD') as r:self.assertEqual(int(r.headers['Content-Length']),path.stat().st_size);self.assertEqual(r.read(),b'')
  with self.assertRaises(urllib.error.HTTPError) as c:self.request(item['download'],headers={'Range':'bytes=999999999-'})
  self.assertEqual(c.exception.code,416)
  with self.assertRaises(urllib.error.HTTPError):self.request(item['download'],auth=False)
 def test_07_move_existing_iso_to_movies(self):
  game=next(i for i in self.api('/api/collection')['items'] if i['title']=='Nome correto');old=self.opl/'DVD'/game['filename'];source=old.read_bytes();r=self.api('/api/collection/update',{'id':game['id'],'title':'ISO marcada como filme','category':'movies'});self.assertEqual(r['item']['id'],game['id']);self.assertEqual(r['item']['category'],'movies');self.assertFalse(old.exists());self.assertEqual((self.movies/r['item']['filename']).read_bytes(),source)
 def test_08_category_inheritance_and_restart_metadata(self):
  manager=self.service.MANAGER;parent='1111111111111111';child='2222222222222222';manager.remember(parent,{'category':'movies','status':'complete'});manager.remember(child,{'following':parent,'status':'complete'});self.assertEqual(manager.category_for(child),'movies');manager.category(parent,'games');self.assertEqual(manager.task(child)['category'],'games')
  from manager import Manager
  reloaded=Manager(self.state,self.downloads,self.service.rpc);self.assertEqual(reloaded.history[parent]['category'],'games')
 def test_09_invalid_video_and_symlink_rejected(self):
  p=self.downloads/'fake.mp4';p.write_bytes(b'<html>not a movie</html>')
  with self.assertRaises(ValueError):self.service.import_file(p,self.downloads)
  outside=self.root/'secret.iso';self.fixture('valid.iso','iso');outside.write_bytes((self.root/'fixtures/valid.iso').read_bytes());link=self.opl/'DVD/link.iso';link.symlink_to(outside);items=self.api('/api/collection?refresh=1')['items'];self.assertFalse(any(i['filename']=='link.iso' for i in items))
 def test_10_completed_iso_can_be_marked_as_film(self):
  name='Outro filme.iso';self.fixture(name,'iso');gid,_=self.add_wait(name);self.assertTrue((self.opl/'DVD'/name).exists());self.rpc('manager.category',[gid,'movies'])
  for _ in range(100):
   if (self.movies/name).is_file():break
   time.sleep(.1)
  self.assertTrue((self.movies/name).is_file());self.assertTrue((self.opl/'DVD'/name).exists())
 def test_11_new_link_keeps_film_destination(self):
  manager=self.service.MANAGER;old=next(t for t in manager.history.values() if t.get('sourceUrl','').endswith('Filme%20de%20teste.iso'));result=self.rpc('manager.replaceLink',[old['gid'],old['sourceUrl'],'',True]);newgid=result['gid'];self.assertNotEqual(old['gid'],newgid);self.assertEqual(manager.task(newgid)['category'],'movies')
  for _ in range(100):
   states=json.loads((self.state/'imports.json').read_text())
   if states.get(newgid,{}).get('state')=='pronto':break
   time.sleep(.1)
  self.assertEqual(states[newgid]['category'],'movies')
 def test_12_regional_build_uses_existing_base_game_cover(self):
  p=self.opl/'DVD/SLUS_111.11.Avatar (PT-BR) NTSC - experimental v2.iso';p.write_bytes(b'test');cover=self.opl/'ART/Avatar (PT-BR)_COV.png';Image.new('RGB',(40,60),'green').save(cover)
  items=self.api('/api/collection?refresh=1')['items'];item=next(i for i in items if i['filename']==p.name);self.assertTrue(item['hasCover'])

 def test_13_other_video_formats_and_archive(self):
  samples=[]
  for extension,codec in [('mkv','ffv1'),('mov','mpeg4'),('mpg','mpeg2video'),('webm','libvpx'),('vob','mpeg2video'),('ts','mpeg2video')]:
   name='Formato de filme.'+extension;p=self.root/'fixtures'/name
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=25','-t','1','-c:v',codec,str(p)],check=True,capture_output=True)
   samples.append(p);self.add_wait(name,'movies');self.assertEqual((self.movies/name).read_bytes(),p.read_bytes());self.assertFalse((self.opl/'DVD'/name).exists())
  with zipfile.ZipFile(self.root/'fixtures/Videos variados.zip','w') as z:z.write(samples[0],'subpasta/Filme compactado.mkv')
  self.add_wait('Videos variados.zip','movies');self.assertEqual((self.movies/'Filme compactado.mkv').read_bytes(),samples[0].read_bytes())
  listed={i['filename'] for i in self.api('/api/collection?refresh=1')['items']}
  self.assertTrue({p.name for p in samples}|{'Filme compactado.mkv'} <= listed)
  for extension in ['mkv','webm','mpg']:
   fake=self.downloads/('Falso.'+extension);fake.write_bytes(b'<html>pagina de erro</html>')
   with self.assertRaises(ValueError):self.service.import_file(fake,self.downloads,'movies')

if __name__=='__main__':unittest.main(verbosity=2)
