"""Local collection catalogue, cover management and resumable downloads."""
import base64,contextlib,errno,hashlib,html,io,json,mimetypes,os,re,shutil,sqlite3,tempfile,threading,time,uuid
from pathlib import Path
from urllib.parse import quote
from PIL import Image,ImageOps

SERIAL=re.compile(r'^([A-Z]{4})[_-](\d{3})[._](\d{2})(?:[. _-]+|$)',re.I)
GAME_TYPES={'.iso','.zso','.chd'}
VIDEO_TYPES={'.mp4','.avi','.mkv','.webm','.mov','.m4v','.mpg','.mpeg','.mpe','.vob','.ts','.m2ts','.mts','.m2v','.m1v','.wmv','.asf','.flv','.f4v','.ogv','.ogm','.3gp','.3g2','.divx','.xvid','.rm','.rmvb','.mxf','.dv','.qt'}
MOVIE_TYPES=VIDEO_TYPES|{'.iso'}

class Conflict(ValueError):pass

def game_name(path):
 name=path.stem;m=SERIAL.match(name)
 serial=f'{m[1].upper()}_{m[2]}.{m[3]}' if m else ''
 title=name[m.end():] if m else name
 title=re.sub(r'\s+',' ',title.replace('_',' ')).strip(' .')
 return serial,title or name

def title_value(value):
 if not isinstance(value,str):raise ValueError('Nome inválido.')
 value=re.sub(r'\s+',' ',value).strip()
 if not value or len(value)>170 or any(ord(c)<32 or c in '/\\<>:"|?*' for c in value):raise ValueError('Use um nome de 1 a 170 caracteres, sem barras ou caracteres de arquivo inválidos.')
 if value in ('.','..') or value.endswith('.'):raise ValueError('Nome de arquivo inválido.')
 return value

class Collection:
 def __init__(self,opl,movies,state):
  self.opl=Path(opl);self.movies=Path(movies);self.state=Path(state);self.lock=threading.RLock();self.last_scan=0
  for p in [self.state,self.state/'covers',self.state/'thumbs',self.state/'backups']:p.mkdir(parents=True,exist_ok=True)
  self.movies.mkdir(parents=True,exist_ok=True)
  self.database=self.state/'collection.sqlite3'
  with self.db() as db:
   db.execute('CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,path TEXT UNIQUE,category TEXT,title TEXT,custom INTEGER DEFAULT 0,serial TEXT,size INTEGER,mtime REAL,device INTEGER,inode INTEGER,present INTEGER DEFAULT 1,added REAL,updated REAL)')
 def db(self):
  @contextlib.contextmanager
  def connection():
   db=sqlite3.connect(self.database,timeout=20);db.row_factory=sqlite3.Row
   try:
    with db:yield db
   finally:db.close()
  return connection()
 def roots(self):return [(self.opl/'DVD','games'),(self.opl/'CD','games'),(self.movies,'movies')]
 def safe(self,path):
  p=Path(path)
  for root,category in self.roots():
   try:p.absolute().relative_to(root.absolute())
   except ValueError:continue
   if p.is_symlink():raise ValueError('Arquivo com link não é permitido.')
   for parent in p.parents:
    if parent==root:break
    if parent.is_symlink():raise ValueError('Pasta com link não é permitida.')
   try:p.resolve().relative_to(root.resolve())
   except ValueError:raise ValueError('Arquivo fora da coleção.') from None
   return p,category
  raise ValueError('Arquivo fora da coleção.')
 def scan(self,force=False):
  with self.lock:
   if not force and time.monotonic()-self.last_scan<4:return
   now=time.time()
   with self.db() as db:
    db.execute('UPDATE items SET present=0')
    for root,category in self.roots():
     paths=root.rglob('*') if category=='movies' else root.glob('*')
     for p in paths:
      types=MOVIE_TYPES if category=='movies' else GAME_TYPES
      if p.suffix.lower() not in types or any(x.startswith('.') for x in p.relative_to(root).parts) or not p.is_file():continue
      try:self.safe(p)
      except ValueError:continue
      st=p.stat();row=db.execute('SELECT * FROM items WHERE path=?',(str(p),)).fetchone()
      if row is None:
       possible=db.execute('SELECT * FROM items WHERE present=0 AND device=? AND inode=?',(st.st_dev,st.st_ino)).fetchall()
       row=next((r for r in possible if not Path(r['path']).exists()),None)
      serial,title=game_name(p) if category=='games' else ('',p.stem)
      if row:
       db.execute('UPDATE items SET path=?,category=?,title=?,serial=?,size=?,mtime=?,device=?,inode=?,present=1 WHERE id=?',(str(p),category,row['title'] if row['custom'] else title,serial,st.st_size,st.st_mtime,st.st_dev,st.st_ino,row['id']))
      else:db.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,str(p),category,title,0,serial,st.st_size,st.st_mtime,st.st_dev,st.st_ino,1,now,now))
   self.last_scan=time.monotonic()
 def row(self,item_id):
  if not re.fullmatch('[0-9a-f]{32}',str(item_id)):raise ValueError('Item inválido.')
  with self.db() as db:r=db.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
  if r is None:raise ValueError('Item não encontrado.')
  r=dict(r);p,_=self.safe(r['path'])
  if not p.is_file():raise ValueError('O arquivo não está mais na coleção. Atualize a lista.')
  return r
 def cover_path(self,r):
  custom=self.state/'covers'/(r['id']+'.png')
  if custom.is_file():return custom
  p=Path(r['path']);names=[p.stem,r['title']]
  # Regional experimental builds can reuse the existing cover of the same base game.
  base_title=re.sub(r'\s+(?:PAL|NTSC)(?:-[A-Z])?\s*-\s*experimental(?:\s+v\d+)?$','',r['title'],flags=re.I)
  if base_title!=r['title']:names.append(base_title)
  if r['serial']:names.insert(0,r['serial'])
  if r['category']=='games':
   for name in names:
    for suffix in ['_COV.png','_COV.jpg','_COV2.png','_ICO.png']:
     candidate=self.opl/'ART'/(name+suffix)
     if candidate.is_file() and not candidate.is_symlink():return candidate
  else:
   for folder in [p.parent,self.movies/'Capas']:
    for name in [p.stem,r['title']]:
     for suffix in ['.jpg','.png','.jpeg','.webp']:
      candidate=folder/(name+suffix)
      if candidate.is_file() and not candidate.is_symlink():return candidate
  return None
 def cfg_title(self,r):
  if not r['serial']:return ''
  for ext in ['.cfg','.CFG']:
   p=self.opl/'CFG'/(r['serial']+ext)
   if p.is_file() and not p.is_symlink():
    try:
     match=re.search(r'^Title=(.+)$',p.read_text(errors='replace'),re.M)
     if match:return match[1].strip()
    except OSError:pass
  return ''
 def public(self,r):
  cover=self.cover_path(r);p=Path(r['path']);version=str(cover.stat().st_mtime_ns) if cover else '0'
  return {**{k:r[k] for k in ['id','category','title','serial','size','mtime','added']},'filename':p.name,'folder':'Filmes' if r['category']=='movies' else p.parent.name,'format':p.suffix[1:].upper(),'hasCover':bool(cover),'cover':f'/api/collection/cover?id={r["id"]}&v={version}','download':f'/api/collection/file?id={r["id"]}','suggestedTitle':self.cfg_title(r),'renameSuggested':p.name!=self.filename(r,r['title'])}
 def list(self,force=False):
  self.scan(force)
  with self.db() as db:rows=[dict(r) for r in db.execute('SELECT * FROM items WHERE present=1 ORDER BY title COLLATE NOCASE')]
  items=[self.public(r) for r in rows];space=shutil.disk_usage(self.movies)
  return {'items':items,'counts':{'games':sum(i['category']=='games' for i in items),'movies':sum(i['category']=='movies' for i in items),'withoutCover':sum(not i['hasCover'] for i in items)},'bytes':sum(i['size'] for i in items),'free':space.free,'moviesFolder':str(self.movies),'scannedAt':time.time()}
 def filename(self,r,title,category=None):
  category=category or r['category'];p=Path(r['path']);prefix=r['serial']+'.' if category=='games' and r['serial'] else ''
  return prefix+title+p.suffix.lower()
 def preview(self,item_id,title,category=None):
  r=self.row(item_id);title=title_value(title);category=category or r['category']
  if category not in ['games','movies']:raise ValueError('Categoria inválida.')
  if category!=r['category'] and Path(r['path']).suffix.lower()!='.iso':raise ValueError('Somente ISO pode trocar entre Jogos e Filmes.')
  if category=='games' and r['category']=='movies':raise ValueError('Uma ISO de filme não pode virar jogo. A importação de jogos é feita pelo downloader.')
  filename=self.filename(r,title,category)
  if len(filename.encode('utf-8'))>250:raise ValueError('O nome do arquivo ficou longo demais. Use um título mais curto.')
  return {'title':title,'filename':filename,'folder':'Filmes' if category=='movies' else Path(r['path']).parent.name,'category':category}
 def backup(self,p):
  if p.exists():
   target=self.state/'backups'/(str(time.time_ns())+'-'+p.name);shutil.copy2(p,target);return str(target)
 def invalidate_cache(self):
  for folder in ['DVD','CD']:
   p=self.opl/folder/'games.bin'
   if p.is_file() and not p.is_symlink():
    target=self.state/'backups'/(str(time.time_ns())+'-'+folder+'-games.bin');p.rename(target)
 def audit(self,event):
  with (self.state/'changes.jsonl').open('a') as f:f.write(json.dumps({'time':time.time(),**event},ensure_ascii=False)+'\n')
 def update(self,item_id,title,rename=True,category=None):
  with self.lock:
   r=self.row(item_id);proposed=self.preview(item_id,title,category);old=Path(r['path']);new=old
   if rename or proposed['category']!=r['category']:
    folder=self.movies if proposed['category']=='movies' else old.parent;new=folder/proposed['filename'];self.safe(new)
    if new!=old:
     if new.exists():raise Conflict('Já existe um arquivo com esse nome. Escolha outro.')
     try:os.link(old,new)
     except OSError as e:
      if e.errno!=errno.EXDEV:raise
      fd,temp=tempfile.mkstemp(prefix='.collection-',dir=new.parent)
      try:
       with os.fdopen(fd,'wb') as out,old.open('rb') as src:shutil.copyfileobj(src,out,1024*1024);out.flush();os.fsync(out.fileno())
       os.link(temp,new)
      finally:os.unlink(temp)
     try:old.unlink()
     except OSError:new.unlink();raise
   serial,_=game_name(new) if proposed['category']=='games' else ('','');st=new.stat()
   try:
    with self.db() as db:db.execute('UPDATE items SET path=?,title=?,category=?,serial=?,custom=1,updated=?,size=?,mtime=? WHERE id=?',(str(new),proposed['title'],proposed['category'],serial,time.time(),st.st_size,st.st_mtime,item_id))
   except Exception:
    if new!=old:new.rename(old)
    raise
   # Keep title-based cover aliases available when a game file changes its name.
   if new!=old and r['category']=='games':
    for suffix in ['_COV.png','_COV2.png','_ICO.png']:
     source=self.opl/'ART'/(old.stem+suffix);target=self.opl/'ART'/(new.stem+suffix)
     if source.is_file() and not source.is_symlink() and not target.exists():os.link(source,target)
    self.invalidate_cache()
   self.audit({'action':'rename','id':item_id,'before':str(old),'after':str(new),'title':proposed['title']});self.last_scan=0
   return {'message':'Nome e organização atualizados.','item':self.public(self.row(item_id))}
 def upload_cover(self,item_id,data,apply_opl=False):
  with self.lock:
   r=self.row(item_id)
   if not isinstance(data,str) or len(data)>12*1024*1024:raise ValueError('A capa deve ter no máximo 8 MiB.')
   try:
    raw=base64.b64decode(data.split(',',1)[-1],validate=True)
    if len(raw)>8*1024*1024:raise ValueError()
    with Image.open(io.BytesIO(raw)) as image:
     if image.width*image.height>20000000:raise ValueError()
     image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1000,1500));out=io.BytesIO();image.save(out,'PNG');payload=out.getvalue()
   except Exception:raise ValueError('Envie uma imagem PNG, JPG ou WebP válida, até 8 MiB e 20 megapixels.') from None
   target=self.state/'covers'/(item_id+'.png');self.backup(target);fd,tmp=tempfile.mkstemp(dir=target.parent)
   try:
    with os.fdopen(fd,'wb') as out:out.write(payload)
    os.replace(tmp,target)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
   if apply_opl and r['category']=='games':
    cover=self.opl/'ART'/((r['serial'] or Path(r['path']).stem)+'_COV.png');cover.parent.mkdir(exist_ok=True);self.backup(cover);image=image.copy();image.thumbnail((256,384));fd,tmp=tempfile.mkstemp(dir=cover.parent)
    try:
     with os.fdopen(fd,'wb') as out:image.save(out,'PNG')
     os.chmod(tmp,0o664);os.replace(tmp,cover)
    finally:
     if os.path.exists(tmp):os.unlink(tmp)
   self.audit({'action':'cover','id':item_id,'opl':bool(apply_opl and r['category']=='games')})
   return {'message':'Capa salva.','item':self.public(self.row(item_id))}
 def cover(self,item_id):
  r=self.row(item_id);p=self.cover_path(r)
  if not p:
   title=html.escape(r['title'][:48]);label='FILME' if r['category']=='movies' else 'PLAYSTATION 2'
   data=f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="340" viewBox="0 0 240 340"><rect width="240" height="340" fill="#222c36"/><path d="M30 250L180 100M0 280L210 70" stroke="#34424e" stroke-width="40"/><text x="22" y="35" fill="#aebdbf" font-family="sans-serif" font-size="12">{label}</text><foreignObject x="20" y="170" width="200" height="140"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#f2eee4;font:700 23px sans-serif;overflow-wrap:anywhere">{title}</div></foreignObject></svg>'
   return data.encode(),'image/svg+xml'
  key=hashlib.sha256((str(p)+str(p.stat().st_mtime_ns)+str(p.stat().st_size)).encode()).hexdigest()[:24];cache=self.state/'thumbs'/(key+'.webp')
  if not cache.exists():
   try:
    with Image.open(p) as im:im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((320,480));out=io.BytesIO();im.save(out,'WEBP',quality=82);cache.write_bytes(out.getvalue())
   except Exception:raise ValueError('Não foi possível abrir esta capa.') from None
  return cache.read_bytes(),'image/webp'
 def send_file(self,handler,item_id,head=False):
  r=self.row(item_id);p=Path(r['path']);size=p.stat().st_size;start,end=0,size-1;partial=False
  try:
   value=handler.headers.get('Range')
   if value:
    if not value.startswith('bytes=') or ',' in value:raise ValueError()
    a,b=value[6:].split('-',1)
    if a:start=int(a);end=min(end,int(b)) if b else end
    else:
     count=int(b)
     if count<=0:raise ValueError()
     start=max(0,size-count)
    if not 0<=start<=end<size:raise ValueError()
    partial=True
  except ValueError:
   handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}');handler.send_header('Content-Length','0');handler.end_headers();return
  handler.send_response(206 if partial else 200);handler.send_header('Content-Type',mimetypes.guess_type(p.name)[0] or 'application/octet-stream');handler.send_header('Content-Length',str(max(0,end-start+1)));handler.send_header('Accept-Ranges','bytes');handler.send_header('Content-Disposition',"attachment; filename=collection-download"+p.suffix+"; filename*=UTF-8''"+quote(p.name));handler.send_header('Cache-Control','private, no-store')
  if partial:handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  handler.end_headers()
  if head:return
  try:
   with p.open('rb') as src:
    src.seek(start);left=end-start+1
    while left:
     b=src.read(min(left,1024*1024))
     if not b:break
     handler.wfile.write(b);left-=len(b)
  except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
