#!/usr/bin/env python3
"""Build a reproducible source installer archive without local data or credentials."""
import gzip,hashlib,io,pathlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
FILES=['install.sh','uninstall.sh','README.md','CHANGELOG.md','LICENSE','maizonas','scripts','tests','docs']
def allowed(p):return not any(part in ('__pycache__','.git','.venv','preview') for part in p.parts) and p.suffix not in ('.pyc','.log','.sqlite','.sqlite3') and p.name not in ('config.json','history.json','.env')
def main():
 dist=ROOT/'dist';dist.mkdir(exist_ok=True);dest=dist/'maizonas-2.0.0.tar.gz'
 with dest.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as tar:
  paths=[]
  for name in FILES:
   p=ROOT/name
   if p.is_file():paths.append(p)
   else:paths.extend(q for q in p.rglob('*') if q.is_file())
  for p in sorted(paths):
   relative=p.relative_to(ROOT)
   if not allowed(relative) or p.is_symlink():continue
   info=tar.gettarinfo(str(p),'maizonas-2.0.0/'+str(relative));info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=0
   info.mode=0o755 if p.suffix=='.sh' or p.name in ('maizonasctl','completed.py') else 0o644
   with p.open('rb') as file:tar.addfile(info,file)
 digest=hashlib.sha256(dest.read_bytes()).hexdigest();dest.with_suffix(dest.suffix+'.sha256').write_text(digest+'  '+dest.name+'\n');print(dest);print('SHA256',digest)
if __name__=='__main__':main()
