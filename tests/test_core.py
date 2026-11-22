import base64,copy,importlib,json,os,pathlib,socket,socketserver,subprocess,sys,tempfile,threading,time,unittest,urllib.request,urllib.error
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from maizonas import config,system
NICS=[{'name':'eth0','kind':'ethernet','carrier':True,'up':True,'addresses':['192.168.0.4/24'],'speed':'100'},{'name':'wlan0','kind':'wifi','carrier':False,'up':False,'addresses':[],'speed':'-1'}]
def freeport():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def settings(root):
 return {'version':2,'name':'MaizoNAS','username':'admin','password_hash':config.password_hash('test-password'),'service_user':'tux','service_uid':os.getuid(),'service_gid':os.getgid(),'service_home':str(root),'web_port':freeport(),'rpc_port':freeport(),'legacy_converter_redirect':False,'paths':{'games':str(root/'games'),'movies':str(root/'movies'),'downloads':str(root/'downloads'),'state':str(root/'state'),'collection_state':str(root/'collection'),'converter_state':str(root/'converter')},'network':{'mode':'ethernet','ethernet':'eth0','wifi':'wlan0','method':'dhcp','address':'','gateway':'','dns':[],'ssid':''},'samba':{'enabled':True,'port':445,'share':'PS2','legacy':True,'read_only':False},'converter':{'engine':os.environ.get('FILMES_ENGINE','/usr/bin')}}
class ValidationTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.c=settings(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_password_and_public_config(self):
  self.assertTrue(config.verify_password('test-password',self.c['password_hash']));self.assertFalse(config.verify_password('wrong-password',self.c['password_hash']));self.assertNotIn('password_hash',config.public(self.c));self.assertNotIn('secret',json.dumps(config.public(self.c)))
  header='Basic '+base64.b64encode(b'admin:test-password').decode();self.assertTrue(config.authorized(header,self.c));self.assertFalse(config.authorized(header.replace('Basic','Bearer'),self.c))
 def test_network_validation(self):
  good={'mode':'both','ethernet':'eth0','wifi':'wlan0','method':'dhcp','ssid':'Minha rede'};self.assertEqual(system.validate_network(good,NICS)['mode'],'both')
  for change in [{'ethernet':'eth0;reboot'},{'mode':'wrong'},{'ssid':'bad\nnetwork'},{'wifi_password':'short'},{'mode':'both','method':'static','address':'192.168.0.4/24','gateway':'192.168.0.1','dns':'1.1.1.1'}]:
   with self.assertRaises(ValueError):system.validate_network({**good,**change},NICS)
  static={'mode':'ethernet','ethernet':'eth0','method':'static','address':'192.168.0.4/24','gateway':'192.168.0.1','dns':'1.1.1.1,8.8.8.8'};self.assertEqual(len(system.validate_network(static,NICS)['dns']),2)
  for address in ['192.168.0.1/24','192.168.0.255/24','invalid']:
   with self.assertRaises(ValueError):system.validate_network({**static,'address':address},NICS)
 def test_settings_validation(self):
  validated=copy.deepcopy(self.c);validated['paths'].update(games='/srv/maizonas/games',movies='/srv/maizonas/movies',downloads='/srv/maizonas/downloads');good=system.validate_settings({'web_port':18088,'samba':{'share':'MY_PS2'}},validated);self.assertEqual(good['samba']['share'],'MY_PS2')
  for change in [{'web_port':445},{'samba':{'port':self.c['rpc_port']}},{'samba':{'share':'bad\n[evil]'}},{'paths':{'games':'/etc/cron.d'}},{'paths':{'games':'/'}},{'paths':{'games':'relative'}}]:
   with self.assertRaises(ValueError):system.validate_settings(change,self.c)
 def test_samba_explicit_ipv4_and_compatibility(self):
  from maizonas import admin
  with patch.object(admin.sys,'interfaces',return_value=NICS),patch.object(admin.sys,'command',return_value=subprocess.CompletedProcess([],0,stdout='Version 4.20',stderr='')):
   text=admin.samba_text(self.c);self.assertIn('interfaces = 127.0.0.1/8 eth0',text);self.assertIn('min protocol = NT1',text);self.assertIn('ntlmv1-permitted',text)
   modern=copy.deepcopy(self.c);modern['samba']['legacy']=False;self.assertIn('min protocol = SMB2',admin.samba_text(modern))
 def test_network_plan_never_returns_password(self):
  from maizonas import admin
  with patch.object(admin.cfg,'load',return_value=self.c),patch.object(admin.sys,'interfaces',return_value=NICS):
   result=admin.dispatch('network.plan',{'mode':'wifi','wifi':'wlan0','ssid':'Test','wifi_password':'very-secret-pass'})
   self.assertNotIn('very-secret-pass',json.dumps(result));self.assertIn('token',result)
 def test_rollback_restores_files(self):
  from maizonas import admin
  with patch.object(admin.sys,'HOST',self.root),patch.object(admin.sys,'command',return_value=subprocess.CompletedProcess([],0,stdout='',stderr='')):
   f=self.root/'etc/network.conf';f.parent.mkdir(parents=True);f.write_bytes(b'NEW')
   tx={'state':'pending','files':{'/etc/network.conf':b'OLD'},'adapter':'slitaz','connections':[]};admin.rollback(tx);self.assertEqual(f.read_bytes(),b'OLD');self.assertEqual(tx['state'],'rolled-back')
 def test_networkd_profile_and_transaction_recovery(self):
  from maizonas import admin
  command=subprocess.CompletedProcess([],0,stdout='',stderr='')
  with patch.object(admin.sys,'HOST',self.root),patch.object(admin.sys,'command',return_value=command):
   network={'mode':'ethernet','ethernet':'eth0','wifi':'wlan0','method':'static','address':'192.168.0.4/24','gateway':'192.168.0.1','dns':['1.1.1.1'],'ssid':'','wifi_password':''}
   admin.apply_networkd(network)
   self.assertIn('Address=192.168.0.4/24',(self.root/'etc/systemd/network/00-00-maizonas-eth0.network').read_text())
   self.assertIn('ActivationPolicy=down',(self.root/'etc/systemd/network/00-00-maizonas-wlan0.network').read_text())
   f=self.root/'etc/network.conf';f.write_bytes(b'NEW')
   tx={'id':'test-recovery','state':'pending','files':{'/etc/network.conf':b'ORIGINAL'},'adapter':'slitaz','connections':[],'network':network,'deadline':time.time()+180,'_persisted':True}
   admin.persist_transaction(tx);admin.recover_transactions();self.assertEqual(f.read_bytes(),b'ORIGINAL')
   record=self.root/'var/lib/maizonas/network-transactions/test-recovery.json';self.assertEqual(record.stat().st_mode&0o777,0o600)
   admin.PENDING.clear()
 def test_virtual_interfaces_are_not_physical_ethernet(self):
  for name in ['eth0','dummy0','wlan0']:(self.root/'sys/class/net'/name).mkdir(parents=True)
  (self.root/'sys/class/net/eth0/device').mkdir();(self.root/'sys/class/net/wlan0/wireless').mkdir()
  text='2: dummy0: <BROADCAST,UP> mtu 1500\n4: eth0: <BROADCAST,UP,LOWER_UP> mtu 1500\n5: wlan0: <BROADCAST> mtu 1500\n'
  def command(args,**kwargs):return subprocess.CompletedProcess([],0,stdout=text if 'link' in args else '',stderr='')
  with patch.object(system,'HOST',self.root),patch.object(system,'command',side_effect=command):
   rows={r['name']:r['kind'] for r in system.interfaces()};self.assertEqual(rows,{'eth0':'ethernet','dummy0':'virtual','wlan0':'wifi'})

 def test_package_manager_recipes(self):
  for manager in ['apt-get','dnf','pacman','zypper','apk','tazpkg']:
   bin=self.root/manager;bin.mkdir();log=self.root/(manager+'.log');program=bin/manager;program.write_text('#!/bin/sh\necho "$@" >> "$MAIZO_TEST_LOG"\n');program.chmod(0o755)
   seven=bin/'7z';seven.write_text('#!/bin/sh\nexit 0\n');seven.chmod(0o755)
   result=subprocess.run(['/bin/sh',str(ROOT/'scripts/dependencies.sh'),'--runtime'],env={**os.environ,'PATH':str(bin),'MAIZO_TEST_LOG':str(log)},capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(log.read_text())
 def test_shell_scripts_parse(self):
  for p in [ROOT/'install.sh',ROOT/'uninstall.sh',*list((ROOT/'scripts').glob('*.sh')),ROOT/'scripts/maizonasctl']:
   self.assertEqual(subprocess.run(['/bin/sh','-n',str(p)],capture_output=True).returncode,0,str(p))

class WebIntegrationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='maizonas-web-');cls.root=pathlib.Path(cls.tmp.name);cls.config=settings(cls.root)
  for p in cls.config['paths'].values():pathlib.Path(p).mkdir(parents=True,exist_ok=True)
  state=pathlib.Path(cls.config['paths']['state'])
  for name in ('queue','tasks','work'):(state/name).mkdir()
  (state/'config.json').write_text(json.dumps({'password':'unused-test-password','secret':'test-only-rpc-secret'}));(state/'session.txt').touch()
  (state/'aria2.conf').write_text('\n'.join(['enable-rpc=true','rpc-listen-all=false','rpc-listen-port='+str(cls.config['rpc_port']),'rpc-secret=test-only-rpc-secret','dir='+cls.config['paths']['downloads'],'save-session='+str(state/'session.txt'),'input-file='+str(state/'session.txt'),'on-download-complete='+str(ROOT/'maizonas/legacy/completed.py'),'file-allocation=none']))
  (pathlib.Path(cls.config['paths']['games'])/'DVD').mkdir();(pathlib.Path(cls.config['paths']['games'])/'ART').mkdir()
  cls.settings=cls.root/'settings.json';config.atomic_json(cls.settings,cls.config)
  cls.sock=cls.root/'admin.sock'
  class FakeAdmin(socketserver.StreamRequestHandler):
   def handle(self):
    request=json.loads(self.rfile.readline());method=request['method']
    if method=='status':result={'interfaces':NICS,'routes':'default via 192.168.0.1 dev eth0','adapter':'slitaz','packageManager':'tazpkg','smbListeningIPv4':True,'smbShare':'PS2','smbPort':445,'webPort':cls.config['web_port'],'disk':{'total':1000000000,'free':900000000,'used':100000000},'missingRuntimePackages':[],'config':config.public(cls.config),'transactions':[],'jobs':[]}
    elif method=='samba.test':result={'ok':True,'message':'SMB testado'}
    else:result={'message':'Operação simulada no teste'}
    self.wfile.write(json.dumps({'result':result}).encode()+b'\n')
  cls.broker=socketserver.ThreadingUnixStreamServer(str(cls.sock),FakeAdmin);threading.Thread(target=cls.broker.serve_forever,daemon=True).start()
  env={**os.environ,'PYTHONPATH':str(ROOT),'MAIZONAS_CONFIG':str(cls.settings),'MAIZONAS_SOCKET':str(cls.sock)}
  cls.log=(cls.root/'web.log').open('wb');cls.process=subprocess.Popen([sys.executable,'-m','maizonas.app'],env=env,stdout=cls.log,stderr=subprocess.STDOUT);cls.base='http://127.0.0.1:'+str(cls.config['web_port'])
  for _ in range(100):
   try:
    with socket.create_connection(('127.0.0.1',cls.config['web_port']),timeout=.1):break
   except OSError:
    if cls.process.poll() is not None:raise RuntimeError((cls.root/'web.log').read_text())
    time.sleep(.1)
 @classmethod
 def tearDownClass(cls):
  cls.process.terminate();cls.process.wait(timeout=25);cls.log.close();cls.broker.shutdown();cls.broker.server_close();cls.tmp.cleanup()
 def request(self,path,body=None,auth=True,extra=None):
  headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-password').decode()} if auth else {};headers.update(extra or {})
  if body is not None:headers['Content-Type']='application/json';body=json.dumps(body).encode()
  return urllib.request.urlopen(urllib.request.Request(self.base+path,data=body,headers=headers),timeout=20)
 def test_home_is_collection_and_all_routes(self):
  with self.assertRaises(urllib.error.HTTPError):self.request('/',auth=False)
  for path,marker in [('/','id="grid"'),('/downloads','id="add"'),('/convert','id="source"'),('/settings','id="network-form"'),('/shell.js','MaizoNAS')]:
   with self.request(path) as r:self.assertIn(marker,r.read().decode())
 def test_converter_admin_and_auth_are_unified(self):
  for path in ['/api/admin/status','/api/converter/status','/api/collection','/api/state']:
   with self.request(path) as r:data=json.load(r);self.assertIsInstance(data,dict);self.assertNotIn('password_hash',json.dumps(data))
  with self.request('/api/admin/samba/test',{}) as r:self.assertTrue(json.load(r)['ok'])
 def test_cross_origin_and_arbitrary_rpc_rejected(self):
  with self.assertRaises(urllib.error.HTTPError) as result:self.request('/api/admin/settings',{},extra={'Origin':'https://evil.example'})
  self.assertEqual(result.exception.code,403)
  with self.assertRaises(urllib.error.HTTPError):self.request('/jsonrpc',{'method':'aria2.changeGlobalOption','params':[{'on-download-complete':'evil'}]})
 def test_unsupported_path_and_no_root_privilege_api(self):
  with self.assertRaises(urllib.error.HTTPError):self.request('/api/admin/shell',{'command':'reboot'})
  with self.assertRaises(urllib.error.HTTPError):self.request('/api/converter/analyze?file=../../etc/passwd')
if __name__=='__main__':unittest.main(verbosity=2)
