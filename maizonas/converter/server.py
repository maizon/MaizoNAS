#!/usr/bin/env python3
"""Conversor local: DVD navigation, lossless profiles, verified output, no source deletion."""
import base64, struct, collections, hashlib, hmac, json, mimetypes, os, pathlib, queue, re, shutil, signal, subprocess, threading, time, urllib.parse, uuid, xml.etree.ElementTree as ET
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP=pathlib.Path(__file__).resolve().parent
MOVIES=pathlib.Path(os.environ.get('FILMES_DIR',str(pathlib.Path.home()/'Filmes'))).resolve()
STATE=pathlib.Path(os.environ.get('FILMES_STATE',str(pathlib.Path.home()/'.local/share/maizonas/converter')))
ENGINE=os.environ.get('FILMES_ENGINE','/usr/bin')
FFMPEG=str(pathlib.Path(ENGINE)/'ffmpeg'); FFPROBE=str(pathlib.Path(ENGINE)/'ffprobe')
PORT=int(os.environ.get('FILMES_PORT','8090'))
CONFIG=pathlib.Path(os.environ.get('FILMES_AUTH_CONFIG',str(pathlib.Path.home()/'.local/share/maizonas/downloads/config.json')))
EXTENSIONS={'.iso','.mp4','.avi','.mkv','.webm','.mov','.m4v','.mpg','.mpeg','.vob','.ts','.mts','.m2ts','.wmv','.asf','.flv','.ogv','.3gp','.divx','.rmvb','.mxf','.dv','.m2v','.m1v','.mpe','.f4v','.ogm','.3g2','.xvid','.rm','.qt'}
PROFILES={
 'avi_lossless':{'label':'AVI sem perdas','extension':'avi','lossless':True,'description':'Vídeo FFV1 e áudio original quando compatível. Arquivo grande; requer player com FFV1. Não é o perfil do SMS/PS2.'},
 'mp4_lossless':{'label':'MP4 sem perdas','extension':'mp4','lossless':True,'description':'H.264 lossless (CRF 0), com áudio original ou PCM convertido sem perdas para ALAC. Alguns aparelhos não aceitam esse perfil.'},
 'avi_compatible':{'label':'AVI compatível · Xvid','extension':'avi','lossless':False,'description':'Xvid em qualidade alta e MP3 320 kb/s. Há recompressão com perdas. Compatibilidade no console depende do aparelho.'},
 'mp4_compatible':{'label':'MP4 compatível · H.264','extension':'mp4','lossless':False,'description':'H.264 CRF 16 e AAC 320 kb/s. Alta qualidade, com perdas; mais compatível com navegadores e aparelhos.'},
 'mkv_original':{'label':'MKV · fluxos originais','extension':'mkv','lossless':True,'description':'Copia os fluxos originais sem recompressão. Mantém os codecs da origem; não permite mudar a resolução.'},
}
LOCK=threading.RLock(); JOBS={}; WORK=queue.Queue(); STOP=threading.Event(); PROCESS={}
class Cancelled(Exception):pass

def initialize():
 MOVIES.mkdir(parents=True,exist_ok=True);STATE.mkdir(parents=True,exist_ok=True)
 history=STATE/'jobs.json'
 if history.exists():
  for job in json.loads(history.read_text()):
   if job['status'] in ('queued','running'):
    job.update(status='interrupted',phase='Interrompido ao reiniciar; o original foi preservado.')
    for name in job.get('partials',[]):
     p=(MOVIES/name)
     if p.name.startswith('.convert-') and p.resolve().is_relative_to(MOVIES):p.unlink(missing_ok=True)
   JOBS[job['id']]=job

def save():
 with LOCK:
  p=STATE/'jobs.tmp';p.write_text(json.dumps(list(JOBS.values())[-100:],ensure_ascii=False,indent=2));p.replace(STATE/'jobs.json')

def update(job,**values):
 with LOCK:job.update(values);job['updated']=time.time();save()

def source_path(name):
 if not isinstance(name,str):raise ValueError('Selecione um arquivo.')
 p=MOVIES/name
 if p.is_symlink() or not p.resolve().is_relative_to(MOVIES) or not p.is_file() or any(x.startswith('.') for x in p.relative_to(MOVIES).parts):raise ValueError('Arquivo fora da pasta Filmes ou não disponível.')
 if p.suffix.lower() not in EXTENSIONS:raise ValueError('Formato de origem não reconhecido.')
 return p.resolve()

def files():
 rows=[]
 for p in MOVIES.rglob('*'):
  if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS and not any(x.startswith('.') for x in p.relative_to(MOVIES).parts):
   s=p.stat();rows.append({'name':str(p.relative_to(MOVIES)),'size':s.st_size,'mtime':s.st_mtime,'dvd':p.suffix.lower()=='.iso'})
 return sorted(rows,key=lambda r:r['name'].casefold())

def capture(args,timeout=120):
 r=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout)
 if r.returncode:raise ValueError((r.stderr.strip() or 'Falha ao ler o arquivo.')[-2200:])
 return r.stdout

def input_args(path,title=None):
 # The native DVD demuxer reads navigation, cells and original title timestamps.
 return (['-f','dvdvideo','-title',str(title),'-preindex','1'] if path.suffix.lower()=='.iso' else [])+['-i',str(path)]

def probe(path,title=None):
 text=capture([FFPROBE,'-v','error',*input_args(path,title),'-show_streams','-show_format','-of','json'],180)
 data=json.loads(text[text.index('{'):])
 videos=[s for s in data.get('streams',[]) if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')]
 if not videos:raise ValueError('Este arquivo não contém vídeo legível.')
 data['video']=videos[0];data['audio']=[s for s in data['streams'] if s.get('codec_type')=='audio']
 data['duration']=float(data.get('format',{}).get('duration') or videos[0].get('duration') or 0)
 return data

def analyze(name):
 path=source_path(name)
 if path.suffix.lower()=='.iso':
  result=subprocess.run(['lsdvd','-Ox','-a','-v','-c',str(path)],capture_output=True,text=True,timeout=120)
  start=result.stdout.find('<lsdvd>')
  if start<0:raise ValueError('A ISO não é um DVD-Video legível. ISOs de jogos/dados não podem virar um filme.')
  try:root=ET.fromstring(result.stdout[start:])
  except ET.ParseError:raise ValueError('Não foi possível ler a estrutura de títulos deste DVD.')
  titles=[]
  for t in root.findall('track'):
   n=int(t.findtext('ix','0'));duration=float(t.findtext('length','0'))
   if duration>0:titles.append({'id':n,'duration':duration,'chapters':len(t.findall('chapter')),'audio':[{'language':a.findtext('langcode','und'),'codec':a.findtext('format','')} for a in t.findall('audio')]})
  if not titles:raise ValueError('Nenhum título de vídeo encontrado no DVD.')
  longest=max(titles,key=lambda t:t['duration'])['id'];info=probe(path,longest)
 else:titles=[];longest=None;info=probe(path)
 v=info['video']
 return {'name':name,'dvd':bool(titles),'titles':titles,'defaultTitle':longest,'duration':info['duration'],'video':{k:v.get(k) for k in ('codec_name','width','height','sample_aspect_ratio','display_aspect_ratio','pix_fmt','field_order','avg_frame_rate')},'audio':[{'codec':a['codec_name'],'language':a.get('tags',{}).get('language','und'),'channels':a.get('channels')} for a in info['audio']],'note':'Cada título selecionado gera um arquivo separado. Menus interativos não são convertidos; os originais são preservados.' if titles else 'A sincronização já incorreta na origem não pode ser corrigida automaticamente por comparação de tempos.'}

def start_job(body):
 path=source_path(body.get('source'));profile=body.get('profile','mp4_lossless');resolution=str(body.get('resolution','original'))
 if profile not in PROFILES or resolution not in ('original','1080','720','480','360'):raise ValueError('Perfil ou resolução inválida.')
 if PROFILES[profile]['lossless'] and resolution!='original':raise ValueError('O modo sem perdas mantém a resolução original. Para redimensionar, selecione um perfil compatível.')
 requested=body.get('titles',[])
 if not isinstance(requested,list) or len(requested)>99 or any(type(t)!=int or not 1<=t<=99 for t in requested):raise ValueError('Seleção de títulos inválida.')
 titles=sorted(set(requested))
 if path.suffix.lower()=='.iso':
  if not titles:raise ValueError('Analise o DVD e selecione pelo menos um título.')
 else:titles=[None]
 with LOCK:
  if sum(j['status'] in ('queued','running') for j in JOBS.values())>=10:raise ValueError('A fila já tem dez tarefas; aguarde uma terminar.')
  job={'id':uuid.uuid4().hex[:12],'source':str(path.relative_to(MOVIES)),'profile':profile,'resolution':resolution,'titles':titles,'status':'queued','phase':'Aguardando na fila','progress':0,'created':time.time(),'updated':time.time(),'outputs':[],'partials':[],'cancel':False,'sourceStamp':[path.stat().st_size,path.stat().st_mtime_ns]}
  JOBS[job['id']]=job;save();WORK.put(job)
 return job

def check(job):
 if STOP.is_set() or job.get('cancel'):raise Cancelled()
 if shutil.disk_usage(MOVIES).free<256*1024*1024:raise ValueError('Pouco espaço livre. A tarefa foi interrompida e o original foi preservado.')

# Consume stdout continuously; FFmpeg progress and hash data must never fill a pipe.
def execute(job,cmd,phase,duration=0,start=0,end=70):
 check(job);update(job,phase=phase);lines=[];last=[0]
 log=STATE/(job['id']+'.log')
 with log.open('a') as stderr:
  proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=stderr,text=True,start_new_session=True)
  PROCESS[job['id']]=proc
  def consume():
   for line in proc.stdout:
    if line.startswith('out_time_us=') and duration:
     try:progress=min(end,start+float(line.split('=',1)[1])/1e6/duration*(end-start))
     except ValueError:continue
     if time.time()-last[0]>1:update(job,progress=round(progress,1));last[0]=time.time()
    elif not line.startswith(('frame=','fps=','stream_','bitrate=','total_size=','out_time_','out_time=','dup_frames=','drop_frames=','speed=','progress=')):lines.append(line)
  reader=threading.Thread(target=consume,daemon=True);reader.start()
  try:
   while proc.poll() is None:check(job);time.sleep(.3)
   reader.join(timeout=5)
   if proc.returncode:raise ValueError(log.read_text(errors='replace')[-2600:] or 'O motor recusou o arquivo.')
  finally:
   if proc.poll() is None:
    os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=8)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   reader.join(timeout=5);PROCESS.pop(job['id'],None);proc.stdout.close()
 return ''.join(lines)

def encoding(info,profile,resolution):
 opts=[];v=info['video']
 if profile=='mkv_original':return ['-c','copy']
 if profile=='avi_lossless':opts=['-c:v','ffv1','-level','3','-coder','1','-context','1','-g','1','-slicecrc','1']
 elif profile=='mp4_lossless':
  if v.get('pix_fmt') not in ('yuv420p','yuv422p','yuv444p','yuvj420p','yuvj422p','yuvj444p','yuv420p10le','yuv422p10le','yuv444p10le','gray','gray10le'):raise ValueError('Este formato de pixels não pode ser preservado pelo H.264 lossless. Use AVI sem perdas ou MKV original.')
  opts=['-c:v','libx264','-crf','0','-preset','medium']
 elif profile=='avi_compatible':opts=['-c:v','libxvid','-q:v','2','-pix_fmt','yuv420p']
 else:opts=['-c:v','libx264','-crf','16','-preset','medium','-pix_fmt','yuv420p']
 if resolution!='original':opts+=['-vf',f'scale=-2:min(ih\\,{resolution})']
 if profile=='avi_compatible':
  # Square pixels prevent many older AVI players from stretching DVD video.
  height=resolution if resolution!='original' else str(v['height'])
  opts=[*opts[:opts.index('-vf')]] if '-vf' in opts else opts
  opts+=['-vf',f'scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=-2:min(ih\\,{height})']
 for i,a in enumerate(info['audio']):
  codec=a['codec_name']
  if PROFILES[profile]['lossless'] and (a.get('sample_fmt','').startswith('dbl') or int(a.get('bits_per_raw_sample') or 0)>32):raise ValueError('Este áudio exige mais de 32 bits. Use MKV original para preservar o fluxo.')
  if profile=='avi_compatible':target='libmp3lame';opts += [f'-b:a:{i}','320k']
  elif profile=='mp4_compatible':target='aac';opts += [f'-b:a:{i}','320k']
  elif profile=='mp4_lossless':
   if codec in ('aac','ac3','eac3','mp3','alac','dts'):target='copy'
   elif codec.startswith('pcm_') and 'f' not in codec:target='alac'
   else:raise ValueError('Este áudio não pode ser mantido sem perdas neste MP4. Use AVI sem perdas ou MKV original.')
  else:
   if codec in ('ac3','mp3','mp2','aac','pcm_s16le','pcm_s24le','pcm_s32le','pcm_f32le'):target='copy'
   else:target='pcm_f32le' if a.get('sample_fmt','').startswith(('flt','dbl')) else 'pcm_s32le'
  opts += [f'-c:a:{i}',target]
 if profile.startswith('mp4'):opts+=['-movflags','+faststart']
 return opts

def hash_streams(job,path,title,phase,progress,audio_formats):
 audio_args=[value for i,codec in enumerate(audio_formats) for value in (f'-c:a:{i}',codec)]
 text=execute(job,[FFMPEG,'-nostdin','-hide_banner','-v','error',*input_args(path,title),'-map','0:v:0','-map','0:a?','-c:v','rawvideo',*audio_args,'-fps_mode','passthrough','-f','streamhash','-hash','sha256','-'],phase)
 hashes=[line.strip().split(',',2)[-1] for line in text.splitlines() if re.match(r'^\d+,[va],',line)]
 if not hashes:raise ValueError('Não foi possível conferir os dados decodificados.')
 update(job,progress=progress);return hashes

def packet_hashes(job,path,title,phase):
 data=execute(job,[FFMPEG,'-nostdin','-v','error',*input_args(path,title),'-map','0:v:0','-map','0:a?','-c','copy','-f','streamhash','-hash','sha256','-'],phase)
 return [line.split(',',2)[-1].strip() for line in data.splitlines() if re.match(r'^\d+,[va],',line)]

def timeline(job,path,title,phase):
 # Compare decoded presentation times, not packet DTS (B frames are reordered).
 text=execute(job,[FFPROBE,'-v','error',*input_args(path,title),'-show_frames','-show_entries','frame=media_type,stream_index,best_effort_timestamp_time,nb_samples','-of','compact=p=0:nk=0'],phase)
 streams={};video=[]
 for line in text.splitlines():
  fields=dict(part.split('=',1) for part in line.split('|') if '=' in part)
  typ=fields.get('media_type');stamp=fields.get('best_effort_timestamp_time')
  if typ not in ('video','audio') or stamp in (None,'N/A'):continue
  key=(typ,fields.get('stream_index'));s=streams.setdefault(key,{'first':None,'last':None,'count':0,'backwards':0})
  timestamp=float(stamp)
  if s['first'] is None:s['first']=timestamp
  if s['last'] is not None and timestamp<s['last']-.002:s['backwards']+=1
  s['last']=timestamp;s['count']+=1
  if typ=='video':video.append(timestamp)
 rows=sorted(streams.items(),key=lambda row:(0 if row[0][0]=='video' else 1,int(row[0][1])));v=next((s for (typ,index),s in rows if typ=='video'),None)
 if not v:raise ValueError('Não foi possível validar os tempos de apresentação.')
 return {'streams':[{'type':key[0],**value} for key,value in rows],'videoTimes':video}

def restore_avi_starts(path,original,converted):
 # AVI's strh.dwStart is expressed in dwScale/dwRate units. FFmpeg's muxer
 # writes zero unconditionally. Restore each stream's original relative start
 # without touching encoded media; keep the format's native time granularity.
 old=original['streams'];new=converted['streams']
 if len(old)!=len(new):raise ValueError('As faixas do AVI não correspondem à origem.')
 common=max(b['first']-a['first'] for a,b in zip(old,new))
 headers=[]
 with path.open('r+b') as f:
  if f.read(4)!=b'RIFF':raise ValueError('Cabeçalho AVI inválido.')
  f.seek(8)
  if f.read(4)!=b'AVI ':raise ValueError('Arquivo não é AVI.')
  def walk(begin,end):
   pos=begin
   while pos+8<=end:
    f.seek(pos);header=f.read(8)
    if len(header)!=8:break
    tag,size=struct.unpack('<4sI',header);data=pos+8
    if tag==b'LIST':
     kind=f.read(4)
     if kind in (b'hdrl',b'strl'):walk(data+4,data+size)
    elif tag==b'strh' and size>=48:
     f.seek(data);raw=f.read(48);kind=raw[:4]
     if kind in (b'vids',b'auds'):
      scale,rate,start=struct.unpack_from('<III',raw,20)
      headers.append((data,scale,rate,start,'video' if kind==b'vids' else 'audio'))
    pos=data+size+(size&1)
  # Only parse the RIFF header list, never search inside encoded frame data.
  pos=12
  while pos<min(path.stat().st_size,16*1024*1024):
   f.seek(pos);raw=f.read(12)
   if len(raw)<12:break
   tag,size,kind=struct.unpack('<4sI4s',raw)
   if tag==b'LIST' and kind==b'hdrl':walk(pos+12,pos+8+size);break
   pos+=8+size+(size&1)
  if len(headers)!=len(old):raise ValueError('Não foi possível restaurar os tempos das faixas do AVI.')
  adjustments=[]
  for (offset,scale,rate,start,typ),a,b in zip(headers,old,new):
   if typ!=a['type'] or not scale or not rate:raise ValueError('Base de tempo AVI inválida.')
   delta=(a['first']+common)-b['first'];units=max(0,round(delta*rate/scale));value=start+units
   if value>0xffffffff:raise ValueError('Início de faixa fora do limite do AVI.')
   f.seek(offset+28);f.write(struct.pack('<I',value));adjustments.append(round(units*scale/rate*1000,3))
  f.flush();os.fsync(f.fileno())
 return adjustments

def compare_timeline(original,converted):
 a=original['streams'];b=converted['streams']
 if len(a)!=len(b):raise ValueError('Quantidade de faixas mudou; saída não foi publicada.')
 va=next(s for s in a if s['type']=='video');vb=next(s for s in b if s['type']=='video');shift=vb['first']-va['first'];worst=0
 for old,new in zip(a,b):
  if old['type']!=new['type'] or new['backwards']:raise ValueError('Tempos de apresentação inconsistentes; saída não foi publicada.')
  for edge in ('first','last'):
   error=abs((new[edge]-old[edge])-shift);worst=max(worst,error)
   if error>.04001:raise ValueError(f'Diferença de tempo entre faixas ({error:.3f} s). Saída retida; use MKV original ou confira a origem.')
 at=original['videoTimes'];bt=converted['videoTimes']
 if len(at)==len(bt):
  for x,y in zip(at,bt):
   error=abs((y-x)-shift);worst=max(worst,error)
   if error>.04001:raise ValueError('A linha de tempo do vídeo mudou durante a conversão; saída não publicada.')
 return {'maxTimestampDifferenceMs':round(worst*1000,2),'checked':'Tempos de vídeo e início/fim de cada faixa de áudio comparados com a origem. Não é uma avaliação perceptiva de movimento labial.'}

def convert(job):
 path=source_path(job['source']);stat=path.stat()
 if [stat.st_size,stat.st_mtime_ns]!=job['sourceStamp']:raise ValueError('O arquivo mudou depois de entrar na fila; analise novamente.')
 folder=MOVIES/'Convertidos';folder.mkdir(exist_ok=True)
 if folder.is_symlink():raise ValueError('A pasta Convertidos não pode ser um link.')
 profile=PROFILES[job['profile']];reports=[]
 for index,title in enumerate(job['titles']):
  check(job);base=index/len(job['titles'])*100;span=100/len(job['titles'])
  info=probe(path,title);duration=info['duration'];v=info['video']
  label=(f' - T{title:02d}' if title else '')+' - '+job['id'][:6]
  dest=folder/(path.stem[:140]+label+'.'+profile['extension']);partial=folder/('.convert-'+job['id']+f'-{index}.'+profile['extension'])
  job['partials'].append(str(partial.relative_to(MOVIES)));save()
  args=[FFMPEG,'-nostdin','-hide_banner','-v','warning','-copyts','-start_at_zero',*input_args(path,title),'-map','0:v:0','-map','0:a?','-map_metadata','0','-threads','2',*encoding(info,job['profile'],job['resolution']),'-fps_mode','cfr' if profile['extension']=='avi' else 'passthrough']
  if profile['extension']=='avi':
   fps=Fraction(v.get('avg_frame_rate') or v.get('r_frame_rate') or '25')
   if fps<=0:fps=Fraction(25)
   args+=['-r',str(fps)]
  args+=['-progress','pipe:1','-nostats','-n',str(partial)]
  execute(job,args,f'Convertendo {index+1}/{len(job["titles"])}'+(f' · título {title}' if title else ''),duration,base,base+span*.65)
  output=probe(partial)
  if len(output['audio'])!=len(info['audio']):raise ValueError('Uma faixa de áudio ficou ausente; saída não publicada.')
  if profile['lossless']:
   hashfn=packet_hashes if job['profile']=='mkv_original' else hash_streams
   if job['profile']=='mkv_original':
    src_hash=hashfn(job,path,title,'Conferindo fluxos originais');dst_hash=hashfn(job,partial,None,'Conferindo fluxos convertidos')
   else:
    formats=['pcm_f32le' if a.get('sample_fmt','').startswith('flt') else 'pcm_s32le' for a in info['audio']]
    src_hash=hashfn(job,path,title,'Decodificando a origem para comparação',base+span*.73,formats);dst_hash=hashfn(job,partial,None,'Comparando imagem e áudio sem perdas',base+span*.83,formats)
   if src_hash!=dst_hash:raise ValueError('A comparação sem perdas não passou. Nenhuma saída foi publicada; o original está preservado.')
  else:
   execute(job,[FFMPEG,'-nostdin','-v','error','-xerror','-i',str(partial),'-map','0:v:0','-map','0:a?','-fps_mode','passthrough','-f','null','-'],'Validando decodificação')
   src_hash=dst_hash=None
  original_timing=timeline(job,path,title,'Conferindo linha de tempo original');converted_timing=timeline(job,partial,None,'Conferindo sincronização da saída')
  avi_adjustments=None
  if profile['extension']=='avi':
   avi_adjustments=restore_avi_starts(partial,original_timing,converted_timing)
   if any(avi_adjustments):converted_timing=timeline(job,partial,None,'Validando o início das faixas do AVI')
  timing=compare_timeline(original_timing,converted_timing)
  if avi_adjustments:timing['aviStreamStartAdjustmentsMs']=avi_adjustments
  if [path.stat().st_size,path.stat().st_mtime_ns]!=job['sourceStamp']:raise ValueError('O original mudou durante a conversão.')
  report={'source':job['source'],'title':title,'profile':job['profile'],'losslessVerified':profile['lossless'],'sourceHashes':src_hash,'outputHashes':dst_hash,'timing':timing,'resolution':[output['video']['width'],output['video']['height']],'duration':output['duration'],'audioTracks':len(output['audio']),'sourcePreserved':True}
  with partial.open('rb') as f:os.fsync(f.fileno())
  os.link(partial,dest);partial.unlink();dest.chmod(0o664)
  dest.with_suffix(dest.suffix+'.verificacao.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
  with LOCK:job['outputs'].append({'name':str(dest.relative_to(MOVIES)),'size':dest.stat().st_size,'report':report})
  update(job,progress=round(base+span,1))
 update(job,status='done',phase='Concluído e validado. Original preservado.',progress=100)

def worker():
 while not STOP.is_set():
  try:job=WORK.get(timeout=1)
  except queue.Empty:continue
  try:
   if job['cancel']:raise Cancelled()
   update(job,status='running',phase='Analisando a origem');convert(job)
  except Cancelled:update(job,status='cancelled',phase='Cancelado. Original preservado.')
  except Exception as error:update(job,status='error',phase=str(error))
  finally:
   for name in job.get('partials',[]):
    p=MOVIES/name
    if p.name.startswith('.convert-') and p.resolve().is_relative_to(MOVIES):p.unlink(missing_ok=True)
   WORK.task_done()

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def auth(self):
  try:
   password=json.loads(CONFIG.read_text())['password'];expected='Basic '+base64.b64encode(('ps2:'+password).encode()).decode()
   return hmac.compare_digest(self.headers.get('Authorization',''),expected)
  except Exception:return False
 def guard(self):
  if self.auth():return True
  self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Conversor Filmes", charset="UTF-8"');self.send_header('Content-Length','0');self.end_headers();return False
 def respond(self,data,status=200,kind='application/json; charset=utf-8'):
  if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if not self.guard():return
  url=urllib.parse.urlsplit(self.path);params=urllib.parse.parse_qs(url.query)
  try:
   if url.path=='/api/status':
    with LOCK:jobs=json.loads(json.dumps(list(JOBS.values())[-100:]))
    return self.respond({'files':files(),'jobs':jobs[::-1],'profiles':PROFILES,'free':shutil.disk_usage(MOVIES).free,'folder':str(MOVIES)})
   if url.path=='/api/analyze':return self.respond(analyze(params.get('file',[''])[0]))
   if url.path=='/api/download':
    job=JOBS.get(params.get('job',[''])[0]);index=int(params.get('index',['0'])[0])
    if not job or not 0<=index<len(job['outputs']):raise ValueError('Arquivo não encontrado.')
    p=source_path(job['outputs'][index]['name']);size=p.stat().st_size;start=0;end=size-1;status=200
    requested=self.headers.get('Range')
    if requested:
     m=re.fullmatch(r'bytes=(\d+)-(\d*)',requested)
     if not m:raise ValueError('Intervalo inválido.')
     start=int(m[1]);end=min(size-1,int(m[2]) if m[2] else size-1);status=206
     if start>end:raise ValueError('Intervalo fora do arquivo.')
    self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(p.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(p.name));self.send_header('Accept-Ranges','bytes')
    if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    self.end_headers()
    with p.open('rb') as f:
     f.seek(start);remaining=end-start+1
     while remaining:
      chunk=f.read(min(1024*1024,remaining))
      if not chunk:break
      self.wfile.write(chunk);remaining-=len(chunk)
    return
   static={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
   if url.path in static:
    p=APP/'web'/static[url.path];return self.respond(p.read_bytes(),kind=mimetypes.guess_type(p.name)[0]+'; charset=utf-8')
   self.respond({'error':'Não encontrado.'},404)
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception as error:self.respond({'error':str(error)},400)
 def do_POST(self):
  if not self.guard():return
  try:
   origin=self.headers.get('Origin')
   if origin and urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host'):raise ValueError('Origem de requisição inválida.')
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=32768 or self.headers.get_content_type()!='application/json':raise ValueError('Requisição inválida.')
   body=json.loads(self.rfile.read(length))
   if self.path=='/api/jobs':return self.respond(start_job(body),201)
   if self.path=='/api/cancel':
    with LOCK:
     job=JOBS[body['id']]
     if job['status'] not in ('queued','running'):raise ValueError('Esta tarefa já terminou.')
     job['cancel']=True;save()
    return self.respond({'ok':True})
   self.respond({'error':'Não encontrado.'},404)
  except Exception as error:self.respond({'error':str(error)},400)

def main():
 initialize()
 if not pathlib.Path(FFMPEG).exists():raise RuntimeError('Motor FFmpeg com navegação DVD ainda não instalado.')
 if '--daemon' in os.sys.argv:
  if os.fork():return
  os.setsid()
  if os.fork():os._exit(0)
  fd=os.open('/dev/null',os.O_RDONLY);log=os.open(STATE/'service.log',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
  os.dup2(fd,0);os.dup2(log,1);os.dup2(log,2)
 (STATE/'service.pid').write_text(str(os.getpid()))
 thread=threading.Thread(target=worker,daemon=True);thread.start();server=ThreadingHTTPServer(('0.0.0.0',PORT),Handler)
 def shutdown(*args):STOP.set();threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
 try:server.serve_forever(poll_interval=.5)
 finally:STOP.set();thread.join(timeout=15);server.server_close();(STATE/'service.pid').unlink(missing_ok=True)
if __name__=='__main__':main()
