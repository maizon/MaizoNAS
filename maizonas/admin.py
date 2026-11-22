"""Local privileged broker. No shell command or arbitrary package API is exposed."""
import base64,configparser,copy,hashlib,ipaddress,json,os,pathlib,re,secrets,signal,socket,socketserver,struct,threading,time,uuid
from . import config as cfg
from . import system as sys
SOCKET=pathlib.Path(os.environ.get('MAIZONAS_SOCKET','/run/maizonas/admin.sock'))
LOCK=threading.RLock();PLANS={};PENDING={};JOBS={};LAST_SMB_REBIND=0

def backup(path,folder):
 p=sys.hostpath(path)
 if p.exists():
  target=folder/str(path).lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes());target.chmod(0o600)

def write_host(path,data,mode=0o600):
 p=sys.hostpath(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name('.'+p.name+'.maizonas-tmp');tmp.write_text(data);tmp.chmod(mode);os.replace(tmp,p)

def service(action):
 if action not in ('start','stop','restart'):raise ValueError('Ação inválida.')
 if sys.available('systemctl') and sys.hostpath('/run/systemd/system').exists():
  name='smb' if sys.command(['systemctl','list-unit-files','smb.service'],check=False).stdout.find('smb.service')>=0 else 'smbd'
  return sys.command(['systemctl',action,name],check=False)
 if sys.available('rc-service'):return sys.command(['rc-service','samba',action],check=False)
 name='/etc/init.d/samba' if sys.hostpath('/etc/init.d/samba').exists() else '/etc/init.d/smbd'
 if action=='restart':
  sys.command([name,'stop'],check=False);time.sleep(2);return sys.command([name,'start'],check=False)
 return sys.command([name,action],check=False)

def samba_text(config):
 settings=config['samba'];nics=sys.interfaces();mode=config['network']['mode'];chosen=config['network'].get('ethernet') if mode=='ethernet' else config['network'].get('wifi') if mode=='wifi' else ''
 names=[n['name'] for n in nics if n['kind'] in ('ethernet','wifi') and (not chosen or n['name']==chosen)]
 if not names:raise ValueError('Nenhuma interface LAN encontrada para o SMB.')
 version=sys.command(['smbd','--version'],check=False).stdout;old=bool(re.search(r'Version 3\.',version));maximum='NT1' if settings['legacy'] else 'SMB2' if old else 'SMB3'
 legacy_auth='yes' if old else 'ntlmv1-permitted'
 path=config['paths']['games']
 return '\n'.join(['# Managed by MaizoNAS; original configuration is backed up.','[global]','    workgroup = WORKGROUP','    server string = MaizoNAS','    security = user','    map to guest = Bad User','    interfaces = 127.0.0.1/8 '+' '.join(names),'    bind interfaces only = yes','    smb ports = '+str(settings['port']),'    min protocol = '+('NT1' if settings['legacy'] else 'SMB2'),'    max protocol = '+maximum,'    ntlm auth = '+(legacy_auth if settings['legacy'] else 'no'),'    hosts allow = 127.0.0.1 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10','    hosts deny = ALL','    load printers = no','    disable spoolss = yes','['+settings['share']+']','    path = '+path,'    browseable = yes','    guest ok = yes','    guest only = yes','    force user = '+config['service_user'],'    read only = '+('yes' if settings['read_only'] else 'no'),'    create mask = 0664','    directory mask = 0775','    wide links = no',''])

def configure_samba(config):
 global LAST_SMB_REBIND
 if not sys.available('smbd'):raise ValueError('Samba não instalado; use Reparar dependências.')
 folder=sys.hostpath('/var/lib/maizonas/backups/samba-'+str(int(time.time())));folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
 backup('/etc/samba/smb.conf',folder)
 # The managed include leaves unrelated shares intact; this installation owns
 # the selected share name and explicit OPL compatibility settings.
 include='/etc/samba/maizonas.conf';backup(include,folder);old=sys.hostpath(include).read_text() if sys.hostpath(include).exists() else None
 write_host(include,samba_text(config),0o644)
 main=sys.hostpath('/etc/samba/smb.conf');main.parent.mkdir(parents=True,exist_ok=True);text=main.read_text() if main.exists() else '[global]\n'
 if not re.search(r'^\s*include\s*=\s*/etc/samba/maizonas.conf\s*$',text,re.M):write_host('/etc/samba/smb.conf',text+'\n[global]\n    include = /etc/samba/maizonas.conf\n',0o644)
 try:sys.command(['testparm','-s','/etc/samba/smb.conf'])
 except Exception:
  original=folder/'etc/samba/smb.conf'
  if original.exists():main.write_bytes(original.read_bytes())
  if old is None:sys.hostpath(include).unlink(missing_ok=True)
  else:write_host(include,old,0o644)
  raise
 service('restart' if config['samba']['enabled'] else 'stop');LAST_SMB_REBIND=time.time()

def dhcp(name):
 pidfile=sys.hostpath('/var/run/udhcpc.'+name+'.pid')
 try:
  pid=int(pidfile.read_text());command=sys.hostpath('/proc/'+str(pid)+'/cmdline').read_bytes()
  if b'udhcpc' in command and name.encode() in command:return
 except (OSError,ValueError):pass
 sys.command(['udhcpc','-n','-t','4','-T','2','-i',name,'-p','/var/run/udhcpc.'+name+'.pid'],timeout=20)

def kill_interface(name,programs):
 for p in sys.hostpath('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   args=(p/'cmdline').read_bytes().split(b'\0');prog=args[0].rsplit(b'/',1)[-1].decode()
   if prog in programs and (name.encode() in args or ('-i'+name).encode() in args):os.kill(int(p.name),signal.SIGTERM)
  except (OSError,UnicodeError):pass

def apply_slitaz(network):
 rows=sys.interfaces();eth=network['ethernet'];wifi=network['wifi'];mode=network['mode']
 primary=eth if mode=='ethernet' or mode=='both' or mode=='auto' and any(n['name']==eth and n['carrier'] for n in rows) else wifi
 if not primary:raise ValueError('Nenhuma interface utilizável para esse modo.')
 enabled=[n for n in (eth,wifi) if n and (mode=='both' or n==primary)]
 file=sys.hostpath('/etc/network.conf');text=file.read_text()
 changes={'INTERFACE':eth or primary,'DHCP':'yes' if network['method']=='dhcp' else 'no','STATIC':'no' if network['method']=='dhcp' else 'yes','WIFI':'yes' if wifi in enabled else 'no'}
 if network['method']=='static':
  address=ipaddress.IPv4Interface(network['address']);changes.update(IP=str(address.ip),NETMASK=str(address.netmask),GATEWAY=network['gateway'],DNS_SERVER=' '.join(network['dns']))
 if network['ssid']:changes['WIFI_ESSID']=network['ssid']
 if network['wifi_password']:changes['WIFI_KEY']=network['wifi_password']
 for key,value in changes.items():
  # Shell configuration remains data, including SSIDs and passwords with quotes.
  quoted="'"+value.replace("'","'\"'\"'")+"'"
  pattern=r'^'+key+r'=.*$'
  text=re.sub(pattern,lambda m:key+'='+quoted,text,flags=re.M) if re.search(pattern,text,re.M) else text+'\n'+key+'='+quoted+'\n'
 write_host('/etc/network.conf',text)
 for nic in enabled:
  sys.command(['ip','link','set',nic,'up'])
  if nic==wifi:
   if network['ssid'] and network['wifi_password']:
    kill_interface(wifi,('wpa_cli','wpa_supplicant','udhcpc'))
    data=sys.command(['wpa_passphrase',network['ssid']],input=network['wifi_password']+'\n').stdout
    data='\n'.join(line for line in data.splitlines() if not line.lstrip().startswith('#psk='))
    write_host('/etc/wpa/wpa.conf','ctrl_interface=/var/run/wpa_supplicant\n'+data+'\n')
   running=False
   for proc in sys.hostpath('/proc').glob('[0-9]*/cmdline'):
    try:
     args=proc.read_bytes()
     if b'wpa_supplicant' in args and wifi.encode() in args:running=True;break
    except OSError:pass
   if not running:
    if not sys.hostpath('/etc/wpa/wpa.conf').exists():raise ValueError('Informe uma rede e senha Wi-Fi antes de ativá-la.')
    sys.command(['wpa_supplicant','-B','-i',wifi,'-c','/etc/wpa/wpa.conf','-D','nl80211,wext'])
    time.sleep(3)
  if network['method']=='dhcp':dhcp(nic)
  else:
   kill_interface(nic,('udhcpc',));sys.command(['ip','addr','flush','dev',nic]);sys.command(['ip','addr','add',network['address'],'dev',nic]);sys.command(['ip','route','replace','default','via',network['gateway'],'dev',nic])
   write_host('/etc/resolv.conf',''.join('nameserver '+s+'\n' for s in network['dns']),0o644)
 routes=sys.command(['ip','route'],check=False).stdout;gateways={}
 for line in routes.splitlines():
  m=re.match(r'default via ([0-9.]+) dev ([^ ]+)',line)
  if m:gateways[m[2]]=m[1]
 for nic in enabled:
  gateway=network['gateway'] if network['method']=='static' else gateways.get(nic)
  if gateway:
   sys.command(['ip','route','del','default','dev',nic],check=False)
   sys.command(['ip','route','add','default','via',gateway,'dev',nic,'metric','10' if nic==primary else '600'])
  rp=sys.hostpath('/proc/sys/net/ipv4/conf/'+nic+'/rp_filter')
  if rp.exists():rp.write_text('2\n' if mode=='both' else '1\n')
 for nic in (eth,wifi):
  if nic and nic not in enabled:
   kill_interface(nic,('wpa_cli','wpa_supplicant','udhcpc'));sys.command(['ip','addr','flush','dev',nic],check=False);sys.command(['ip','link','set',nic,'down'])


def apply_nm(network):
 primary=network['ethernet'] if network['mode'] in ('ethernet','both') or network['mode']=='auto' and any(n['name']==network['ethernet'] and n['carrier'] for n in sys.interfaces()) else network['wifi']
 enabled=[n for n in (network['ethernet'],network['wifi']) if n and (network['mode']=='both' or n==primary)]
 for nic in enabled:
  wireless=nic==network['wifi']
  if wireless:sys.command(['nmcli','radio','wifi','on'])
  if wireless and not network['ssid']:
   sys.command(['nmcli','device','connect',nic],timeout=45);continue
  profile=configparser.ConfigParser(interpolation=None);ident=str(uuid.uuid5(uuid.NAMESPACE_DNS,'maizonas-'+nic))
  profile['connection']={'id':'MaizoNAS '+nic,'uuid':ident,'type':'wifi' if wireless else 'ethernet','interface-name':nic,'autoconnect':'true'}
  if wireless:
   profile['wifi']={'mode':'infrastructure','ssid':network['ssid']}
   if network['wifi_password']:profile['wifi-security']={'key-mgmt':'wpa-psk','psk':network['wifi_password']}
   else:
    saved=sys.hostpath('/etc/NetworkManager/system-connections/maizonas-'+nic+'.nmconnection')
    previous=configparser.ConfigParser(interpolation=None)
    if saved.exists():previous.read(saved)
    if previous.has_section('wifi-security'):profile['wifi-security']=dict(previous['wifi-security'])
    else:raise ValueError('Informe a senha para criar o perfil da rede Wi-Fi.')
  else:profile['ethernet']={}
  profile['ipv4']={'method':'auto' if network['method']=='dhcp' else 'manual','route-metric':'10' if nic==primary else '600'}
  if network['method']=='static':profile['ipv4'].update(address1=network['address']+','+network['gateway'],dns=';'.join(network['dns'])+';')
  profile['ipv6']={'method':'auto'}
  import io
  content=io.StringIO();profile.write(content);path='/etc/NetworkManager/system-connections/maizonas-'+nic+'.nmconnection';write_host(path,content.getvalue())
  sys.command(['nmcli','connection','load',path]);sys.command(['nmcli','connection','up','uuid',ident],timeout=50)
 for nic in (network['ethernet'],network['wifi']):
  if nic and nic not in enabled:sys.command(['nmcli','device','disconnect',nic],check=False)
 if network['wifi'] and network['wifi'] not in enabled:sys.command(['nmcli','radio','wifi','off'])
 for nic in enabled:
  rp=sys.hostpath('/proc/sys/net/ipv4/conf/'+nic+'/rp_filter')
  if rp.exists():rp.write_text('2\n' if network['mode']=='both' else '1\n')

def apply_networkd(network):
 primary=network['ethernet'] if network['mode'] in ('ethernet','both') or network['mode']=='auto' and any(n['name']==network['ethernet'] and n['carrier'] for n in sys.interfaces()) else network['wifi']
 if not primary:raise ValueError('Nenhuma interface disponível.')
 enabled=[n for n in (network['ethernet'],network['wifi']) if n and (network['mode']=='both' or n==primary)]
 for nic in (network['ethernet'],network['wifi']):
  if not nic:continue
  lines=['[Match]','Name='+nic,'[Link]','ActivationPolicy='+('up' if nic in enabled else 'down'),'[Network]']
  if nic in enabled:
   if network['method']=='dhcp':lines+=['DHCP=yes','[DHCPv4]','RouteMetric='+('10' if nic==primary else '600')]
   else:lines+=['Address='+network['address'],'Gateway='+network['gateway'],*['DNS='+s for s in network['dns']]]
   if nic==network['wifi'] and network['ssid']:
    if network['wifi_password']:
     data=sys.command(['wpa_passphrase',network['ssid']],input=network['wifi_password']+'\n').stdout
     data='\n'.join(line for line in data.splitlines() if not line.lstrip().startswith('#psk='))
     write_host('/etc/wpa_supplicant/wpa_supplicant-'+nic+'.conf','ctrl_interface=/run/wpa_supplicant\n'+data+'\n')
    elif not sys.hostpath('/etc/wpa_supplicant/wpa_supplicant-'+nic+'.conf').exists():raise ValueError('Informe a senha para criar o perfil Wi-Fi.')
    sys.command(['systemctl','enable','--now','wpa_supplicant@'+nic+'.service'],timeout=40)
  else:lines+=['LinkLocalAddressing=no']
  write_host('/etc/systemd/network/00-00-maizonas-'+nic+'.network','\n'.join(lines)+'\n',0o644)
 sys.command(['networkctl','reload'])
 for nic in (network['ethernet'],network['wifi']):
  if not nic:continue
  sys.command(['networkctl','reconfigure',nic],timeout=30)
  sys.command(['ip','link','set',nic,'up' if nic in enabled else 'down'])
  rp=sys.hostpath('/proc/sys/net/ipv4/conf/'+nic+'/rp_filter')
  if rp.exists():rp.write_text('2\n' if network['mode']=='both' else '1\n')

def apply_adapter(kind,network):
 if kind=='slitaz':return apply_slitaz(network)
 if kind=='networkmanager':return apply_nm(network)
 if kind=='networkd':return apply_networkd(network)
 raise ValueError('Adaptador de rede não suportado.')

def persist_transaction(tx):
 if not tx.get('_persisted'):return
 folder=sys.hostpath('/var/lib/maizonas/network-transactions');folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
 record={k:v for k,v in tx.items() if k!='files'}
 record['network']={k:v for k,v in tx['network'].items() if k!='wifi_password'}
 record['files']={k:base64.b64encode(v).decode() if v is not None else None for k,v in tx['files'].items()}
 cfg.atomic_json(folder/(tx['id']+'.json'),record)

def recover_transactions():
 folder=sys.hostpath('/var/lib/maizonas/network-transactions')
 if not folder.exists():return
 for file in folder.glob('*.json'):
  try:
   tx=json.loads(file.read_text())
   if tx['state'] not in ('applying','pending','failed','rolling-back'):continue
   tx['files']={k:base64.b64decode(v) if v is not None else None for k,v in tx['files'].items()};tx['state']='pending';PENDING[tx['id']]=tx;rollback(tx)
  except (ValueError,KeyError,OSError):continue

def rollback(tx):
 with LOCK:
  if tx['state'] not in ('applying','pending','failed'):return
  tx['state']='rolling-back'
 try:
  for name,data in tx['files'].items():
   p=sys.hostpath(name)
   if data is None:p.unlink(missing_ok=True)
   else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o600)
  if tx['adapter']=='slitaz':sys.command(['/etc/init.d/network.sh','restart'],timeout=60)
  elif tx['adapter']=='networkd':
   sys.command(['networkctl','reload'],check=False)
   for nic in (tx['network']['ethernet'],tx['network']['wifi']):
    if nic:sys.command(['networkctl','reconfigure',nic],check=False,timeout=30);sys.command(['ip','link','set',nic,'up'],check=False)
  else:
   sys.command(['nmcli','connection','reload'],check=False)
   for ident in tx['connections']:sys.command(['nmcli','connection','up','uuid',ident],timeout=45,check=False)
  tx['state']='rolled-back';tx['message']='Rede anterior restaurada; nenhuma confirmação foi recebida.'
 except Exception:tx['state']='rollback-error';tx['message']='Falha na reversão. Consulte o acesso local ao computador.'
 persist_transaction(tx)


def network_apply(token,config):
 with LOCK:
  plan=PLANS.pop(token,None)
  if not plan or time.time()-plan['created']>300:raise ValueError('Plano expirado. Gere uma nova prévia.')
  if any(t['state'] in ('applying','pending','rolling-back') for t in PENDING.values()):raise ValueError('Já existe uma mudança de rede aguardando confirmação.')
 kind=sys.adapter()
 if kind not in ('slitaz','networkmanager','networkd'):raise ValueError('Controle de rede indisponível: instale NetworkManager ou use o modo somente leitura.')
 network=plan['network']
 if network['ssid'] and not network['wifi_password'] and network['ssid']!=config['network'].get('ssid',''):raise ValueError('Informe a senha da nova rede; para manter a rede salva, deixe nome e senha vazios.')
 paths=['/etc/network.conf','/etc/wpa/wpa.conf'] if kind=='slitaz' else ['/etc/NetworkManager/system-connections/maizonas-'+nic+'.nmconnection' for nic in (network['ethernet'],network['wifi']) if nic]
 if kind=='networkd':paths=[file for nic in (network['ethernet'],network['wifi']) if nic for file in ('/etc/systemd/network/00-00-maizonas-'+nic+'.network','/etc/wpa_supplicant/wpa_supplicant-'+nic+'.conf')]
 tx={'id':secrets.token_hex(12),'state':'applying','message':'Aplicando a rede. Se a conexão cair, aguarde a reversão automática.','created':time.time(),'deadline':time.time()+180,'network':network,'adapter':kind,'files':{p:sys.hostpath(p).read_bytes() if sys.hostpath(p).exists() else None for p in paths},'connections':[]}
 if kind=='networkmanager':tx['connections']=[line.split(':',1)[0] for line in sys.command(['nmcli','-t','-f','UUID,DEVICE','connection','show','--active'],check=False).stdout.splitlines() if ':' in line]
 tx['_persisted']=True;persist_transaction(tx);PENDING[tx['id']]=tx
 def apply():
  try:
   apply_adapter(kind,network);tx['state']='pending';tx['message']='Conecte pelo endereço exibido e confirme a conexão em até 180 segundos.';persist_transaction(tx)
  except Exception:tx['state']='failed';tx['message']='A mudança falhou. Restaurando a configuração anterior.';rollback(tx)
 threading.Thread(target=apply,daemon=True).start()
 return {'id':tx['id'],'deadline':tx['deadline'],'message':tx['message']}

def restart_web():
 def later():
  time.sleep(3);sys.command(['/usr/local/sbin/maizonasctl','restart-web'],timeout=30,check=False)
 threading.Thread(target=later,daemon=True).start()

def dispatch(method,body):
 config=cfg.load()
 if method=='status':
  result=sys.status(config);result['config']=cfg.public(config);result['transactions']=[{'id':t['id'],'state':t['state'],'message':t['message'],'deadline':t['deadline']} for t in list(PENDING.values())[-8:]];result['jobs']=list(JOBS.values())[-8:];return result
 if method=='network.plan':
  network=sys.validate_network(body,sys.interfaces());token=secrets.token_hex(24);PLANS[token]={'network':network,'created':time.time()}
  return {'token':token,'preview':{k:v for k,v in network.items() if k!='wifi_password'},'message':'Mudança transacional: 180 segundos para confirmar; sem confirmação, a rede anterior será restaurada.'}
 if method=='network.apply':return network_apply(body.get('token'),config)
 if method=='network.confirm':
  tx=PENDING.get(body.get('id'))
  if not tx or tx['state']!='pending':raise ValueError('Nenhuma alteração pendente para confirmar.')
  network={k:v for k,v in tx['network'].items() if k!='wifi_password'};config['network']=network;cfg.atomic_json(cfg.CONFIG_PATH,config,0o640,config['service_gid']);tx['state']='confirmed';tx['message']='Rede confirmada e salva.';persist_transaction(tx)
  if config['samba']['enabled']:configure_samba(config)
  return {'message':tx['message']}
 if method=='settings.save':
  history=pathlib.Path(config['paths']['converter_state'])/'jobs.json'
  if history.exists() and any(j.get('status') in ('running','queued') for j in json.loads(history.read_text())):raise ValueError('Aguarde ou cancele as conversões antes de reiniciar a interface com novas configurações.')
  new=sys.validate_settings(body,config)
  password=body.get('password','')
  if password:new['password_hash']=cfg.password_hash(password)
  for path in (new['paths'][k] for k in ('games','movies','downloads')):
   p=sys.hostpath(path);p.mkdir(parents=True,exist_ok=True);os.chown(p,new['service_uid'],new['service_gid'])
  configure_samba(new)
  cfg.atomic_json(cfg.CONFIG_PATH,new,0o640,new['service_gid']);restart_web();return {'message':'Configuração salva. A interface será reiniciada em alguns segundos.','port':new['web_port']}
 if method=='samba.restart':configure_samba(config);return {'message':'SMB reconfigurado e reiniciado.'}
 if method=='samba.test':
  port=config['samba']['port'];share=config['samba']['share'];protocol='NT1' if config['samba']['legacy'] else 'SMB2';r=sys.command(['smbclient','//127.0.0.1/'+share,'-p',str(port),'-N','-m',protocol,'--option=client min protocol='+protocol,'-c','ls'],check=False,timeout=15)
  return {'ok':r.returncode==0,'message':'Conexão SMB e listagem de arquivos aprovadas.' if r.returncode==0 else (r.stderr or r.stdout)[-1800:]}
 if method=='dependencies.repair':
  ident=secrets.token_hex(6);job={'id':ident,'state':'running','message':'Verificando os pacotes do programa…'};JOBS[ident]=job
  def install():
   try:
    sys.command(['/opt/maizonas/scripts/dependencies.sh','--repair'],timeout=1200);job.update(state='done',message='Pacotes verificados. Reinicie a interface se um recurso tiver sido instalado agora.')
   except Exception:job.update(state='error',message='Não foi possível instalar todos os pacotes. Consulte /var/log/maizonas-install.log no computador.')
  threading.Thread(target=install,daemon=True).start();return job
 if method=='logs':
  path=pathlib.Path(config['paths']['state'])/'service.log';text=path.read_text(errors='replace')[-8000:] if path.exists() else 'Nenhum erro registrado.'
  # Do not return download URLs, query tokens or accidental authorization values.
  text=re.sub(r'https?://\S+','[URL omitida]',text);text=re.sub(r'(?i)(password|secret|authorization|psk)[^\n]*',r'\1=[oculto]',text)
  return {'text':text}
 raise ValueError('Operação administrativa não permitida.')

class Handler(socketserver.StreamRequestHandler):
 def handle(self):
  try:
   pid,uid,gid=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12));config=cfg.load()
   if uid not in (0,config['service_uid']):raise ValueError('Processo não autorizado.')
   line=self.rfile.readline(65537)
   if len(line)>65536:raise ValueError('Requisição muito grande.')
   request=json.loads(line)
   with LOCK:result=dispatch(request['method'],request.get('body',{}))
   response={'result':result}
  except Exception as error:response={'error':str(error)}
  self.wfile.write(json.dumps(response,ensure_ascii=False).encode()+b'\n')

class Server(socketserver.ThreadingUnixStreamServer):daemon_threads=True

def watchdog(stop):
 previous=None;last_restart=0;previous_auto=None
 while not stop.wait(8):
  try:
   for tx in list(PENDING.values()):
    if tx['state'] in ('applying','pending') and time.time()>tx['deadline']:rollback(tx)
   if any(t['state'] in ('applying','pending','rolling-back') for t in PENDING.values()):continue
   config=cfg.load();rows=sys.interfaces();current=tuple(sorted((n['name'],tuple(n['addresses'])) for n in rows if n['kind'] in ('ethernet','wifi') and n['addresses']))
   if previous is not None and current!=previous and time.time()-last_restart>15 and time.time()-LAST_SMB_REBIND>15 and config['samba']['enabled']:
    configure_samba(config);last_restart=time.time()
   previous=current
   if sys.adapter()=='slitaz' and config['network']['mode']=='ethernet':
    eth=next((n for n in rows if n['name']==config['network']['ethernet']),None)
    wifi=next((n for n in rows if n['name']==config['network']['wifi']),None)
    if eth and not eth['up']:sys.command(['ip','link','set',eth['name'],'up'])
    elif eth and eth['carrier'] and (not eth['addresses'] or wifi and wifi['up']):apply_slitaz({**config['network'],'wifi_password':''})
   if config['network']['mode']=='auto':
    auto=next((n['carrier'] for n in rows if n['name']==config['network']['ethernet']),False)
    if previous_auto is not None and auto!=previous_auto:
     network={**config['network'],'wifi_password':''};apply_adapter(sys.adapter(),network)
    previous_auto=auto
  except Exception:pass # Status still exposes missing services; never log secrets.

def main():
 if os.geteuid()!=0:raise RuntimeError('O broker administrativo deve iniciar pelo serviço do sistema.')
 config=cfg.load();SOCKET.parent.mkdir(parents=True,exist_ok=True);SOCKET.unlink(missing_ok=True);recover_transactions()
 if config['samba']['enabled'] and not sys.hostpath('/etc/samba/maizonas.conf').exists():
  try:configure_samba(config)
  except Exception:pass # Missing packages/configuration are visible in the web diagnostics.
 with Server(str(SOCKET),Handler) as server:
  os.chown(SOCKET,0,config['service_gid']);SOCKET.chmod(0o660);stop=threading.Event();threading.Thread(target=watchdog,args=(stop,),daemon=True).start()
  def shutdown(*args):stop.set();threading.Thread(target=server.shutdown,daemon=True).start()
  signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
  try:server.serve_forever(poll_interval=.5)
  finally:stop.set();SOCKET.unlink(missing_ok=True)
if __name__=='__main__':main()
