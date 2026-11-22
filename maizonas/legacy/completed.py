#!/usr/bin/python3
import json,pathlib,sys,os
root=pathlib.Path(os.environ.get('PS2_DOWNLOAD_STATE',str(pathlib.Path.home()/'.local/share/maizonas/downloads')))
gid=sys.argv[1]
if len(gid)==16 and all(c in '0123456789abcdef' for c in gid):
    imports=root/'imports.json'
    if imports.exists():
        try:
            if json.loads(imports.read_text()).get(gid,{}).get('state') in ('extraindo','pronto','erro'): sys.exit(0)
        except ValueError: pass
    path=root/'queue'/(gid+'.json'); path.write_text(json.dumps({'gid':gid}))
