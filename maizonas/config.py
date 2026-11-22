import base64, hashlib, hmac, json, os, pathlib, secrets, tempfile
CONFIG_PATH=pathlib.Path(os.environ.get('MAIZONAS_CONFIG','/etc/maizonas/config.json'))

def password_hash(password, salt=None):
 if not isinstance(password,str) or len(password)<8:raise ValueError('Use uma senha de pelo menos 8 caracteres.')
 salt=salt or secrets.token_hex(16)
 return salt+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()

def verify_password(password, encoded):
 try:salt,expected=encoded.split('$');return hmac.compare_digest(password_hash(password,salt).split('$')[1],expected)
 except (ValueError,TypeError):return False

def atomic_json(path, value, mode=0o600, gid=None):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
 try:
  os.fchmod(fd,mode)
  if gid is not None:os.fchown(fd,-1,gid)
  with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def load(path=None):
 return json.loads(pathlib.Path(path or CONFIG_PATH).read_text())

def public(config):
 return {key:config[key] for key in ('name','web_port','rpc_port','paths','network','samba','username','converter') if key in config}

def authorized(header,config):
 try:
  kind,data=header.split(' ',1)
  if kind!='Basic':return False
  username,password=base64.b64decode(data,validate=True).decode().split(':',1)
  if not hmac.compare_digest(username,config['username']):return False
  # Migrations keep the existing login, even if its old password was short.
  salt,expected=config['password_hash'].split('$')
  value=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()
  return hmac.compare_digest(value,expected)
 except (ValueError,UnicodeError,KeyError,TypeError):return False
