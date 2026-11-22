"""Portable host inspection and strictly argument-based command execution."""
import ipaddress,json,os,pathlib,re,shutil,socket,subprocess,time
HOST=pathlib.Path(os.environ.get('MAIZONAS_HOST_ROOT','/'))

def hostpath(value):
 p=pathlib.Path(value)
 if not p.is_absolute() or '..' in p.parts:raise ValueError('Caminho de sistema inválido.')
 return HOST/str(p).lstrip('/')

def command(args,timeout=20,check=True,input=None):
 if not isinstance(args,list) or not all(isinstance(a,str) and '\x00' not in a for a in args):raise ValueError('Comando inválido.')
 actual=(['chroot',str(HOST)] if str(HOST)!='/' else [])+args
 r=subprocess.run(actual,input=input,capture_output=True,text=True,errors='replace',timeout=timeout)
 if check and r.returncode:raise ValueError((r.stderr or r.stdout or 'Comando indisponível.').strip()[-1800:])
 return r

def available(name):
 if not re.fullmatch(r'[a-zA-Z0-9_.+-]+',name):return False
 if str(HOST)=='/':return bool(shutil.which(name))
 return any(hostpath(p+'/'+name).is_file() for p in ('/usr/bin','/usr/sbin','/bin','/sbin','/usr/local/bin'))

def interfaces():
 rows={}
 text=command(['ip','-o','link','show'],check=False).stdout
 for line in text.splitlines():
  m=re.match(r'\d+: ([^:@]+)(?:@[^:]+)?: <([^>]+)>',line)
  if not m or m[1]=='lo':continue
  name=m[1];base=hostpath('/sys/class/net/'+name)
  def read(file,default=''):
   try:return (base/file).read_text().strip()
   except OSError:return default
  rows[name]={'name':name,'kind':'wifi' if (base/'wireless').exists() else 'virtual' if not (base/'device').exists() else 'ethernet','up':'UP' in m[2].split(','),'carrier':read('carrier')=='1','speed':read('speed'),'addresses':[],'mac':read('address')}
 for line in command(['ip','-o','-4','addr','show'],check=False).stdout.splitlines():
  m=re.match(r'\d+: ([^ ]+)\s+inet ([^ ]+)',line)
  if m and m[1] in rows:rows[m[1]]['addresses'].append(m[2])
 return list(rows.values())

def adapter():
 if available('nmcli') and command(['nmcli','-t','-f','STATE','general'],timeout=3,check=False).returncode==0:return 'networkmanager'
 if hostpath('/etc/slitaz-release').exists():return 'slitaz'
 if available('networkctl') and hostpath('/run/systemd/netif').exists():return 'networkd'
 return 'unsupported'

def package_manager():
 for manager in ('apt-get','dnf','pacman','zypper','apk','tazpkg'):
  if available(manager):return manager
 return None

def status(config):
 nics=interfaces();paths=config['paths'];disk=shutil.disk_usage(paths['games'])
 def listening(port):
  for nic in nics:
   for addr in nic['addresses']:
    try:
     with socket.create_connection((addr.split('/')[0],port),timeout=.4):return True
    except OSError:pass
  return False
 missing=[name for name in ('aria2c','ffmpeg','ffprobe','7z') if not shutil.which(name)]
 return {'interfaces':nics,'routes':command(['ip','route'],check=False).stdout,'adapter':adapter(),'packageManager':package_manager(),'smbListeningIPv4':listening(config['samba']['port']),'smbShare':config['samba']['share'],'smbPort':config['samba']['port'],'webPort':config['web_port'],'disk':{'total':disk.total,'free':disk.free,'used':disk.used},'missingRuntimePackages':missing,'sambaInstalled':available('smbd'),'time':time.time()}

def validate_network(body,nics):
 if not isinstance(body,dict):raise ValueError('Configuração de rede inválida.')
 mode=body.get('mode','auto')
 if mode not in ('auto','ethernet','wifi','both'):raise ValueError('Modo inválido.')
 known={n['name']:n for n in nics};eth=body.get('ethernet','');wifi=body.get('wifi','')
 for name,kind in ((eth,'ethernet'),(wifi,'wifi')):
  if name and (name not in known or known[name]['kind']!=kind or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,32}',name)):raise ValueError('Interface inválida.')
 if mode=='ethernet' and not eth or mode=='wifi' and not wifi or mode=='both' and (not eth or not wifi):raise ValueError('Selecione as interfaces do modo escolhido.')
 if not eth and not wifi:raise ValueError('Nenhuma interface disponível.')
 method=body.get('method','dhcp')
 if method not in ('dhcp','static'):raise ValueError('Método de endereço inválido.')
 result={'mode':mode,'ethernet':eth,'wifi':wifi,'method':method,'address':'','gateway':'','dns':[],'ssid':body.get('ssid',''),'wifi_password':body.get('wifi_password','')}
 if not isinstance(result['ssid'],str) or len(result['ssid'].encode())>32 or any(c in result['ssid'] for c in '\x00\n\r'):raise ValueError('Nome Wi-Fi inválido.')
 password=result['wifi_password']
 if not isinstance(password,str) or password and not (8<=len(password)<=63 or re.fullmatch('[a-fA-F0-9]{64}',password)):raise ValueError('Senha Wi-Fi deve ter de 8 a 63 caracteres (ou chave hexadecimal de 64).')
 if method=='static':
  try:
   address=ipaddress.IPv4Interface(body.get('address',''));gateway=ipaddress.IPv4Address(body.get('gateway',''))
   if gateway not in address.network or gateway==address.ip or address.ip in (address.network.network_address,address.network.broadcast_address):raise ValueError()
   dns=[str(ipaddress.IPv4Address(s.strip())) for s in str(body.get('dns','')).replace(',',' ').split()]
   if not dns:raise ValueError()
  except ValueError:raise ValueError('Informe IP/prefixo, gateway e DNS válidos. O IP do computador deve ser diferente do roteador.') from None
  if mode=='both':raise ValueError('No modo Ambas, use DHCP para evitar endereços duplicados.')
  result.update(address=str(address),gateway=str(gateway),dns=dns)
 return result

def validate_settings(body,config):
 if not isinstance(body,dict):raise ValueError('Configuração inválida.')
 new=json.loads(json.dumps(config))
 for field in ('web_port','rpc_port'):
  value=body.get(field,new[field])
  if type(value)!=int or not 1024<=value<=65535:raise ValueError('Portas web/RPC devem estar entre 1024 e 65535.')
  new[field]=value
 smb=body.get('samba',{})
 if not isinstance(smb,dict):raise ValueError('Configuração SMB inválida.')
 for field in ('enabled','legacy','read_only'):
  value=smb.get(field,new['samba'][field])
  if type(value)!=bool:raise ValueError('Opção SMB inválida.')
  new['samba'][field]=value
 port=smb.get('port',new['samba']['port'])
 if type(port)!=int or not 1<=port<=65535:raise ValueError('Porta SMB inválida.')
 new['samba']['port']=port;share=smb.get('share',new['samba']['share'])
 if not isinstance(share,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',share):raise ValueError('Nome do compartilhamento inválido.')
 new['samba']['share']=share
 if len({new['web_port'],new['rpc_port'],new['samba']['port']})!=3:raise ValueError('As portas não podem ser iguais.')
 for key in ('games','movies','downloads'):
  value=body.get('paths',{}).get(key,new['paths'][key])
  if not isinstance(value,str) or any(c in value for c in '\x00\n\r') or not pathlib.Path(value).is_absolute() or '..' in pathlib.Path(value).parts or value.rstrip('/')=='' or (len(pathlib.Path(value).parts)<2 or pathlib.Path(value).parts[1] in ('etc','usr','bin','sbin','dev','proc','sys','root','boot','run')):raise ValueError('Use pastas absolutas de dados, fora das pastas do sistema.')
  folder=pathlib.Path(value)
  if len(folder.parts)<3 or any(hostpath(parent).is_symlink() for parent in (folder,*folder.parents) if str(parent)!='/'):raise ValueError('Use uma pasta de dados própria, sem links simbólicos.')
  resolved=folder
  allowed=[pathlib.Path(p) for p in ('/home','/srv','/mnt','/media','/var/lib/maizonas')]
  if not any(resolved.is_relative_to(base) and resolved!=base for base in allowed):raise ValueError('Use uma pasta dentro de /home, /srv, /mnt, /media ou /var/lib/maizonas.')
  new['paths'][key]=str(folder)
 if len(set(new['paths'][k] for k in ('games','movies','downloads')))!=3:raise ValueError('Use pastas diferentes para jogos, filmes e downloads.')
 return new
