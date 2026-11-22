#!/usr/bin/env python3
"""Root-owned service launcher; the HTTP application drops all root privileges."""
import os,pathlib,signal,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
from maizonas import config

def main():
 role=sys.argv[1] if len(sys.argv)>1 else ''
 if role not in ('web','admin'):raise SystemExit('Uso: launcher.py web|admin [--daemon]')
 os.chdir('/')
 conf=config.load();run=pathlib.Path('/run/maizonas');run.mkdir(exist_ok=True);pidfile=run/(role+'.pid')
 if '--daemon' in sys.argv:
  if os.fork():return
  os.setsid()
  if os.fork():os._exit(0)
  fd=os.open('/dev/null',os.O_RDONLY);state=pathlib.Path(conf['paths']['state']);state.mkdir(parents=True,exist_ok=True)
  if role=='admin':
   logdir=pathlib.Path(os.environ.get('MAIZONAS_HOST_ROOT','/'))/'var/log/maizonas';logdir.mkdir(parents=True,exist_ok=True);logdir.chmod(0o750);logpath=logdir/'admin.log'
  else:logpath=state/'service.log'
  log=os.open(logpath,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
  if role=='web':os.fchown(log,conf['service_uid'],conf['service_gid'])
  os.dup2(fd,0);os.dup2(log,1);os.dup2(log,2)
 pidfile.write_text(str(os.getpid()))
 if role=='web' and os.geteuid()==0:
  import pwd
  try:os.initgroups(conf['service_user'],conf['service_gid'])
  except KeyError:os.setgroups([conf['service_gid']])
  os.setgid(conf['service_gid']);os.setuid(conf['service_uid'])
 os.environ['HOME']=conf['service_home']
 try:
  if role=='web':from maizonas.app import main as run_service
  else:from maizonas.admin import main as run_service
  run_service()
 finally:
  try:pidfile.unlink()
  except OSError:pass
if __name__=='__main__':main()
