#!/usr/bin/env python3
"""Idempotent install/migration. Media is never copied, renamed or deleted."""
import argparse,hashlib,json,os,pathlib,re,secrets,shlex,shutil,subprocess,sys,time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
from maizonas import config as cfg

def parser():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--user',required=True);p.add_argument('--runtime',default='');p.add_argument('--host-root',default='/');p.add_argument('--start',type=int,default=1);p.add_argument('--dvd',type=int,default=1);p.add_argument('--dry-run',action='store_true');return p

def main():
 args=parser().parse_args();root=pathlib.Path(args.host_root)
 def host(path):return root/str(path).lstrip('/')
 def run(command,**kwargs):
  kwargs.setdefault('check',True)
  return subprocess.run((['chroot',str(root)] if str(root)!='/' else [])+command,**kwargs)
 user=next((row.split(':') for row in host('/etc/passwd').read_text().splitlines() if row.split(':')[0]==args.user),None)
 if not user or int(user[2])==0:raise SystemExit('Use um usuário comum existente.')
 uid,gid=int(user[2]),int(user[3]);home=user[5];source=pathlib.Path(args.source);target=host('/opt/maizonas');configuration=host('/etc/maizonas/config.json');generated_password=None
 previous=json.loads(configuration.read_text()) if configuration.exists() else None
 oldstate=pathlib.Path(home)/'.local/share/ps2-downloads';migrate=(oldstate/'config.json').exists()
 if previous:settings=previous
 else:
  legacy=json.loads((oldstate/'config.json').read_text()) if migrate else None
  plain=legacy['password'] if legacy else secrets.token_urlsafe(18);generated_password=None if legacy else plain;salt=secrets.token_hex(16)
  state=str(oldstate) if migrate else str(pathlib.Path(home)/'.local/share/maizonas/downloads')
  eth=next((p.name for p in host('/sys/class/net').iterdir() if p.name!='lo' and (p/'device').exists() and not (p/'wireless').exists()),'')
  wifi=next((p.name for p in host('/sys/class/net').iterdir() if (p/'wireless').exists()),'')
  engine='/opt/filmes-conversor/engine/bin' if pathlib.Path('/opt/filmes-conversor/engine/bin/ffmpeg').exists() else str(pathlib.Path(shutil.which('ffmpeg') or '/usr/bin/ffmpeg').parent)
  settings={'version':2,'name':'MaizoNAS','username':'ps2' if migrate else 'admin','password_hash':salt+'$'+hashlib.pbkdf2_hmac('sha256',plain.encode(),bytes.fromhex(salt),260000).hex(),'service_user':args.user,'service_uid':uid,'service_gid':gid,'service_home':home,'web_port':8088,'rpc_port':6800,'legacy_converter_redirect':migrate,'paths':{'games':str(pathlib.Path(home)/'PS2'),'movies':str(pathlib.Path(home)/'Filmes'),'downloads':str(pathlib.Path(home)/'Downloads/PS2-Automatico') if migrate else str(pathlib.Path(home)/'Downloads/MaizoNAS'),'state':state,'collection_state':str(pathlib.Path(home)/'.local/share/ps2-collection') if migrate else str(pathlib.Path(home)/'.local/share/maizonas/collection'),'converter_state':str(pathlib.Path(home)/'.local/share/filmes-conversor') if migrate else str(pathlib.Path(home)/'.local/share/maizonas/converter')},'network':{'mode':'ethernet' if eth else 'wifi','ethernet':eth,'wifi':wifi,'method':'dhcp','address':'','gateway':'','dns':[],'ssid':''},'samba':{'enabled':True,'port':445,'share':'PS2','legacy':True,'read_only':False},'converter':{'engine':engine}}
 if args.dry_run:
  print(json.dumps({'target':str(target),'runtime':args.runtime or 'native','migratingCurrent':migrate,'init':'systemd' if host('/run/systemd/system').exists() else 'slitaz' if host('/etc/slitaz-release').exists() else 'openrc' if host('/sbin/openrc-run').exists() else 'sysv','paths':settings['paths'],'sourceReplaced':False,'mediaDeleted':False},indent=2));return
 if os.geteuid()!=0:raise SystemExit('Instalação exige root.')
 # Sources outside the application/state folders; never copy .git or credentials.
 if not target.exists() or not os.path.samefile(source,target):
  stage=target.with_name('maizonas.new-'+str(os.getpid()));shutil.copytree(source,stage,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','.pytest_cache','dist','build','*.bundle','.env','config.json','history.json','*.sqlite3','*.log'))
  if target.exists():
   saved=host('/var/lib/maizonas/backups/app-'+str(int(time.time())));saved.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(target,saved,ignore=shutil.ignore_patterns('__pycache__','*.pyc'));saved.chmod(0o700)
   # Keep the destination inode: SliTaz's runtime bind mount must keep seeing it.
   keep={str(p.relative_to(stage)) for p in stage.rglob('*')}
   for p in sorted(target.rglob('*'),key=lambda p:len(p.parts),reverse=True):
    if str(p.relative_to(target)) not in keep:
     if p.is_dir():p.rmdir()
     else:p.unlink()
   shutil.copytree(stage,target,dirs_exist_ok=True);shutil.rmtree(stage)
  else:stage.rename(target)
 for file in target.rglob('*'):
  os.chown(file,0,0)
  if file.is_file():file.chmod(0o755 if file.suffix=='.sh' or file.name in ('maizonasctl','completed.py') else 0o644)
 target.chmod(0o755);os.chown(target,0,0)
 for value in settings['paths'].values():
  folder=pathlib.Path(value);folder.mkdir(parents=True,exist_ok=True);os.chown(folder,uid,gid)
 for name in ('DVD','CD','ART','CFG','CHT','VMC','THM','APPS','POPS','LNG'):
  folder=pathlib.Path(settings['paths']['games'])/name;folder.mkdir(exist_ok=True);os.chown(folder,uid,gid)
 state=pathlib.Path(settings['paths']['state'])
 for name in ('queue','tasks','work'):
  folder=state/name;folder.mkdir(exist_ok=True);os.chown(folder,uid,gid)
 rpc_config=state/'config.json'
 if not rpc_config.exists():cfg.atomic_json(rpc_config,{'secret':secrets.token_hex(32),'password':secrets.token_urlsafe(32)});os.chown(rpc_config,uid,gid)
 secret=json.loads(rpc_config.read_text())['secret']
 aria=state/'aria2.conf';original=aria.read_text() if aria.exists() else ''
 if original and not (state/'aria2.conf.before-maizonas').exists():(state/'aria2.conf.before-maizonas').write_text(original);(state/'aria2.conf.before-maizonas').chmod(0o600)
 lines={'dir':settings['paths']['downloads'],'enable-rpc':'true','rpc-listen-all':'false','rpc-listen-port':str(settings['rpc_port']),'rpc-secret':secret,'input-file':str(state/'session.txt'),'save-session':str(state/'session.txt'),'save-session-interval':'15','force-save':'true','continue':'true','enable-color':'false','on-download-complete':'/opt/maizonas/maizonas/legacy/completed.py','log':str(state/'aria2.log'),'log-level':'warn','max-concurrent-downloads':'3','file-allocation':'none','seed-time':'0'}
 for key in ('max-concurrent-downloads','max-overall-download-limit','max-overall-upload-limit'):
  m=re.search(r'^'+key+r'=(.*)$',original,re.M)
  if m:lines[key]=m[1]
 text=original
 for key,value in lines.items():
  text,n=re.subn(r'^'+re.escape(key)+r'=.*$',lambda m:key+'='+value,text,flags=re.M)
  if not n:text+='\n'+key+'='+value
 aria.write_text(text+'\n');aria.chmod(0o600);os.chown(aria,uid,gid)
 session=state/'session.txt';session.touch(exist_ok=True);os.chown(session,uid,gid)
 configuration.parent.mkdir(parents=True,exist_ok=True);cfg.atomic_json(configuration,settings,0o640,gid)
 env=configuration.parent/'install.env';env.write_text('MAIZONAS_RUNTIME='+shlex.quote(args.runtime)+'\nMAIZONAS_PYTHON='+shlex.quote(shutil.which('python3') or '/usr/bin/python3')+'\n');env.chmod(0o600)
 ctl=host('/usr/local/sbin/maizonasctl');ctl.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target/'scripts/maizonasctl',ctl);ctl.chmod(0o755)
 # Bindings for /host and the application/config are set by the same launcher
 # used at every boot. In runtime mode make the first installation visible now.
 if args.runtime:
  for origin in ('/etc/maizonas','/opt/maizonas'):
   dest=host(args.runtime+origin);dest.mkdir(parents=True,exist_ok=True)
   if subprocess.run(['mountpoint','-q',str(dest)]).returncode:run(['mount','--bind',origin,args.runtime+origin])
 if args.dvd:
  engine=settings['converter']['engine'];r=subprocess.run([engine+'/ffmpeg','-hide_banner','-demuxers'],capture_output=True,text=True)
  if 'dvdvideo' not in r.stdout:
   subprocess.run(['/bin/sh','/opt/maizonas/scripts/engine.sh'],check=True);settings['converter']['engine']='/opt/maizonas-engine/bin';cfg.atomic_json(configuration,settings,0o640,gid)
 # Host auto-start, with the old web services retired only at the final start.
 if host('/run/systemd/system').exists():
  unit=host('/etc/systemd/system/maizonas.service');unit.parent.mkdir(parents=True,exist_ok=True);unit.write_text('[Unit]\nDescription=MaizoNAS collection and server manager\nAfter=network-online.target\nWants=network-online.target\n[Service]\nType=forking\nPIDFile=/run/maizonas/web.pid\nExecStart=/usr/local/sbin/maizonasctl start\nExecStop=/usr/local/sbin/maizonasctl stop\nRestart=on-failure\nTimeoutStopSec=45\n[Install]\nWantedBy=multi-user.target\n');run(['systemctl','daemon-reload']);run(['systemctl','enable','maizonas'])
 elif host('/sbin/openrc-run').exists():
  init=host('/etc/init.d/maizonas');init.write_text('#!/sbin/openrc-run\ndescription="MaizoNAS"\ndepend() { need net; }\nstart() { /usr/local/sbin/maizonasctl start; }\nstop() { /usr/local/sbin/maizonasctl stop; }\n');init.chmod(0o755);run(['rc-update','add','maizonas','default'])
 else:
  init=host('/etc/init.d/maizonas');init.write_text('#!/bin/sh\n### BEGIN INIT INFO\n# Provides: maizonas\n# Required-Start: $network $remote_fs\n# Required-Stop: $network\n# Default-Start: 2 3 4 5\n# Default-Stop: 0 1 6\n### END INIT INFO\nexec /usr/local/sbin/maizonasctl "${1:-start}"\n');init.chmod(0o755)
  local=host('/etc/init.d/local.sh')
  if local.exists():
   content=local.read_text()
   for name in ('ps2-downloads','filmes-conversor'):content=re.sub(r'^/etc/init.d/'+name+r' start$',r'# Replaced by MaizoNAS: /etc/init.d/'+name+' start',content,flags=re.M)
   if not re.search(r'^/etc/init.d/maizonas start$',content,re.M):content+='\n# Unified collection, downloader, converter and administration.\n/etc/init.d/maizonas start\n'
   local.write_text(content)
  elif shutil.which('update-rc.d'):run(['update-rc.d','maizonas','defaults'])
  else:print('Aviso: init não reconhecido; use maizonasctl start no seu gerenciador de serviços.')
 oldhook=host('/etc/ipup.d/samba-ethernet')
 if oldhook.exists():
  saved=host('/var/lib/maizonas/backups/samba-ethernet.before-maizonas')
  if not saved.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(oldhook,saved)
  oldhook.write_text('#!/bin/sh\n# MaizoNAS now watches IPv4 changes and manages SMB rebinding.\nexit 0\n');oldhook.chmod(0o755)
 desktop=pathlib.Path(home)/'.local/share/applications/maizonas.desktop';desktop.parent.mkdir(parents=True,exist_ok=True);desktop.write_text('[Desktop Entry]\nType=Application\nName=MaizoNAS\nComment=Coleção, downloads e servidor\nExec=xdg-open http://127.0.0.1:'+str(settings['web_port'])+'/\nIcon=network-server\nTerminal=false\nCategories=Network;\n');os.chown(desktop,uid,gid)
 if args.start:
  # Preserve and drain active jobs before migration; avoid silently discarding work.
  if migrate:
   for name in ('ps2-downloads','filmes-conversor'):
    if host('/etc/init.d/'+name).exists():run(['/etc/init.d/'+name,'stop'],check=False)
   time.sleep(3)
  run(['/usr/local/sbin/maizonasctl','stop'],check=False);run(['/usr/local/sbin/maizonasctl','start'])
 print('MaizoNAS instalado. Abra http://IP_DO_COMPUTADOR:'+str(settings['web_port'])+'/')
 print('Login: '+settings['username'])
 if generated_password:print('Senha inicial (guarde agora): '+generated_password)
 else:print('Senha: a mesma já usada no gerenciador. Nenhuma mídia foi movida ou apagada.')
if __name__=='__main__':main()
