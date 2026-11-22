"""Persistent download history and safe HTTP link replacement for the PS2 panel."""
import copy, email.message, json, os, pathlib, re, shutil, threading, time, urllib.error, urllib.parse, urllib.request

class Manager:
    KEYS=['gid','status','totalLength','completedLength','downloadSpeed','uploadSpeed','files','bittorrent','errorCode','errorMessage','connections','following','followedBy','belongsTo']
    def __init__(self,root,downloads,rpc):
        self.root=root;self.downloads=downloads;self.rpc=rpc
        self.lock=threading.RLock();self.actions=threading.Lock()
        self.path=root/'history.json';self.stat={};self.options={};self.last=0;self.last_error=''
        try:self.history=json.loads(self.path.read_text())
        except (OSError,ValueError):self.history={}
    def write(self):
        fd,temp=__import__('tempfile').mkstemp(prefix='.history-',dir=self.root)
        try:
            with os.fdopen(fd,'w') as f:json.dump(self.history,f,ensure_ascii=False)
            os.chmod(temp,0o600);os.replace(temp,self.path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def call(self,method,params=None):
        answer=self.rpc(method,params or [])
        if 'error'in answer:raise ValueError(answer['error'].get('message','Falha no aria2'))
        return answer['result']
    def update(self):
        with self.lock:
            results=self.call('system.multicall',[[
                {'methodName':'aria2.getGlobalStat','params':[]},
                {'methodName':'aria2.getGlobalOption','params':[]},
                {'methodName':'aria2.tellActive','params':[self.KEYS]},
                {'methodName':'aria2.tellWaiting','params':[0,1000,self.KEYS]},
                {'methodName':'aria2.tellStopped','params':[0,1000,self.KEYS]},
            ]])
            if any(not isinstance(v,list) for v in results):raise ValueError('Nao foi possivel consultar o aria2')
            self.stat=results[0][0];self.options=results[1][0]
            live=results[2][0]+results[3][0]+results[4][0];seen=set()
            for task in live:
                gid=task['gid'];seen.add(gid);previous=self.history.get(gid,{})
                # Keep the last known total even if an expired URL reports a zero-length error.
                if int(task.get('totalLength','0'))==0 and int(previous.get('totalLength','0'))>0:task['totalLength']=previous['totalLength']
                previous.update(task);previous.setdefault('created',time.time());previous['updated']=time.time()
                self.history[gid]=previous
            for task in self.history.values():
                parent=self.history.get(task.get('following') or task.get('belongsTo'),{})
                if parent and task.get('category','auto')=='auto' and parent.get('category') in ('movies','games'):
                    task['category']=parent['category']
            for gid,task in self.history.items():
                if gid not in seen and task.get('status') in ('active','waiting','paused'):
                    task['status']='interrupted';task['downloadSpeed']='0'
                    task['errorMessage']='Tarefa interrompida. Retome com o mesmo link ou atualize o link.'
            self.last=time.time();self.last_error='';self.write()
    def watch(self,stop):
        while not stop.is_set():
            try:self.update()
            except Exception:self.last_error='Servico de downloads temporariamente indisponivel. Tentando reconectar.'
            stop.wait(5)
    def task(self,gid):
        if not re.fullmatch('[0-9a-f]{16}',str(gid)):raise ValueError('Download invalido')
        with self.lock:
            task=copy.deepcopy(self.history.get(gid,{}))
        try:
            current=self.call('aria2.tellStatus',[gid,self.KEYS])
            if int(current.get('totalLength','0'))==0 and task.get('totalLength'):current['totalLength']=task['totalLength']
            task.update(current)
        except ValueError:
            if not task:raise ValueError('Download nao encontrado no historico')
        return task
    def remember(self,gid,metadata):
        with self.lock:
            task=self.history.setdefault(gid,{'gid':gid,'created':time.time()})
            task.update(metadata);task['updated']=time.time();self.write()
    @staticmethod
    def url(value):
        if not isinstance(value,str) or len(value)>32768:raise ValueError('Link invalido')
        value=value.strip();p=urllib.parse.urlsplit(value)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
            raise ValueError('Use um link direto HTTP ou HTTPS, sem usuario ou senha na URL')
        return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
    def probe(self,url):
        """Read metadata only; never consume a whole multi-GB response."""
        headers={'User-Agent':'aria2/1.37.0','Accept-Encoding':'identity'}
        try:
            try:response=urllib.request.urlopen(urllib.request.Request(url,method='HEAD',headers=headers),timeout=15)
            except urllib.error.HTTPError as e:
                if e.code not in (405,501):raise
                response=urllib.request.urlopen(urllib.request.Request(url,headers={**headers,'Range':'bytes=0-0'}),timeout=15)
            with response:
                kind=response.headers.get_content_type()
                if kind in ('text/html','application/xhtml+xml'):raise ValueError('Esse link abre uma pagina. Use o link direto do arquivo.')
                cr=response.headers.get('Content-Range','')
                size=int(cr.rsplit('/',1)[-1]) if cr and cr.rsplit('/',1)[-1].isdigit() else int(response.headers.get('Content-Length','0'))
                msg=email.message.Message();msg['Content-Disposition']=response.headers.get('Content-Disposition','')
                return {'length':size,'etag':response.headers.get('ETag','').strip('"'),'filename':msg.get_filename() or ''}
        except urllib.error.HTTPError as e:
            if e.code in (401,403):raise ValueError('O novo link expirou ou exige autorizacao. Gere outro link direto.') from None
            raise ValueError('O servidor recusou o link (HTTP '+str(e.code)+').') from None
        except (urllib.error.URLError,TimeoutError,OSError):raise ValueError('Nao foi possivel verificar o novo link. Confira a conexao ou tente novamente.') from None
    def file(self,task):
        if task.get('bittorrent'):raise ValueError('Troca de link direto se aplica a HTTP/HTTPS. Para torrents, adicione um novo magnet ou .torrent.')
        files=[f for f in task.get('files',[]) if f.get('selected','true')=='true']
        if len(files)!=1:raise ValueError('A troca de link exige um unico arquivo HTTP/HTTPS')
        p=pathlib.Path(files[0]['path'])
        try:p.resolve().relative_to(self.downloads.resolve())
        except ValueError:raise ValueError('O arquivo esta fora da pasta de downloads') from None
        if p.is_symlink() or any(v.is_symlink() for v in p.parents if v!=self.downloads):raise ValueError('O caminho contem um link de pasta')
        return p,files[0]
    def replace(self,gid,url,source_page='',restart=False):
        url=self.url(url)
        if source_page:source_page=self.url(source_page)
        with self.actions:
            task=self.task(gid);p,file=self.file(task)
            if task.get('status')=='complete' and not restart:raise ValueError('O download ja esta completo. Use Repetir extracao ou Baixar do zero se estiver danificado.')
            probe=self.probe(url);expected=int(task.get('totalLength','0')) or int(file.get('length','0'))
            if not probe['length']:raise ValueError('O servidor nao informou o tamanho do arquivo; nao e possivel validar uma retomada segura.')
            if expected and expected!=probe['length'] and not restart:raise ValueError('O novo link tem tamanho diferente. O arquivo parcial foi preservado; use o link do mesmo arquivo.')
            if task.get('etag') and probe['etag'] and task['etag']!=probe['etag'] and not restart:raise ValueError('O novo link identifica outro arquivo (ETag diferente). O parcial foi preservado.')
            live=self.rpc('aria2.tellStatus',[gid]).get('result')
            if live and live.get('status') in ('active','waiting','paused'):
                if live['status']!='paused':
                    self.call('aria2.forcePause',[gid])
                    for _ in range(50):
                        live=self.call('aria2.tellStatus',[gid])
                        if live['status']=='paused':break
                        time.sleep(.1)
                    else:raise ValueError('O download ainda esta pausando; tente novamente')
                if not restart:
                    old=[u['uri'] for u in file.get('uris',[])]
                    self.call('aria2.changeUri',[gid,int(file.get('index','1')),old,[url],0])
                    self.call('aria2.unpause',[gid]);newgid=gid
                else:
                    self.call('aria2.forceRemove',[gid]);newgid=None
            else:newgid=None
            if newgid is None:
                if restart and p.exists():
                    backup=p.with_name(p.name+'.backup-'+str(time.time_ns()))
                    p.rename(backup)
                    control=pathlib.Path(str(p)+'.aria2')
                    if control.exists():control.rename(pathlib.Path(str(backup)+'.aria2'))
                options={'dir':str(p.parent),'out':p.name,'continue':'true','auto-file-renaming':'false','max-tries':'3','retry-wait':'5'}
                if not pathlib.Path(str(p)+'.aria2').exists():options.update({'split':'1','max-connection-per-server':'1'})
                newgid=self.call('aria2.addUri',[[url],options])
            self.remember(newgid,{'status':'waiting','sourcePage':source_page or task.get('sourcePage',''),'sourceUrl':url,'category':task.get('category','auto'),'etag':probe['etag'],'totalLength':str(probe['length']),'files':[file],'previousGid':gid if gid!=newgid else task.get('previousGid','')})
            if gid!=newgid:self.remember(gid,{'replacedBy':newgid})
            self.call('aria2.saveSession')
            return {'gid':newgid,'message':'Link atualizado. Download retomado; o parcial foi mantido.' if not restart else 'Novo download iniciado. O arquivo anterior foi guardado como backup.'}
    def retry(self,gid):
        task=self.task(gid)
        if task.get('status') in ('active','waiting'):return {'gid':gid,'message':'O download ja esta na fila.'}
        if task.get('status')=='paused':self.call('aria2.unpause',[gid]);return {'gid':gid,'message':'Download retomado.'}
        if task.get('bittorrent'):raise ValueError('Para reiniciar um torrent encerrado, adicione novamente o magnet ou .torrent.')
        urls=[task.get('sourceUrl','')]+[u['uri'] for f in task.get('files',[]) for u in f.get('uris',[])]
        url=next((u for u in urls if u),None)
        if not url:raise ValueError('Link nao encontrado. Use Atualizar link.')
        return self.replace(gid,url,task.get('sourcePage',''))
    def settings(self,values):
        concurrent=int(values.get('concurrent',10));download=int(values.get('downloadKiB',0));upload=int(values.get('uploadKiB',0))
        if not 1<=concurrent<=50 or not 0<=download<=10000000 or not 0<=upload<=10000000:raise ValueError('Valores de limite invalidos')
        options={'max-concurrent-downloads':str(concurrent),'max-overall-download-limit':str(download*1024),'max-overall-upload-limit':str(upload*1024)}
        with self.actions:
            self.call('aria2.changeGlobalOption',[options])
            p=self.root/'aria2.conf';s=p.read_text()
            for key,value in options.items():
                s,count=re.subn(r'^'+re.escape(key)+r'=.*$',key+'='+value,s,flags=re.M)
                if not count:s+='\n'+key+'='+value+'\n'
            fd,temp=__import__('tempfile').mkstemp(dir=self.root)
            try:
                with os.fdopen(fd,'w') as out:out.write(s)
                os.chmod(temp,0o600);os.replace(temp,p)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        self.options.update(options);return {'message':'Limites salvos. Zero significa velocidade sem limite.'}
    def state(self):
        with self.lock:
            tasks=copy.deepcopy(list(self.history.values()));stat=copy.deepcopy(self.stat);options=copy.deepcopy(self.options)
        for task in tasks:
            task.pop('sourceUrl',None)
            for file in task.get('files',[]):file.pop('uris',None)
        tasks.sort(key=lambda t:(t.get('status')in('active','waiting','paused'),t.get('updated',0)),reverse=True)
        disk=shutil.disk_usage(self.downloads)
        try:imports=json.loads((self.root/'imports.json').read_text())
        except (OSError,ValueError):imports={}
        return {'tasks':tasks,'stats':stat,'options':{k:options.get(k,'0') for k in ('max-concurrent-downloads','max-overall-download-limit','max-overall-upload-limit')},'disk':{'free':disk.free,'total':disk.total},'imports':imports,'error':self.last_error,'updated':self.last}
    @staticmethod
    def checked_category(category):
        if category not in ('auto','games','movies'):raise ValueError('Destino inválido. Escolha Automático, Jogos ou Filmes.')
        return category
    def category_for(self,gid):
        task=self.task(gid);category=task.get('category','auto')
        if category in ('movies','games'):return category
        parent=task.get('following') or task.get('belongsTo')
        if parent and parent!=gid:
            try:category=self.task(parent).get('category','auto')
            except ValueError:pass
        return self.checked_category(category)
    def category(self,gid,category):
        category=self.checked_category(category);self.task(gid)
        self.remember(gid,{'category':category})
        with self.lock:
            for child,task in self.history.items():
                if task.get('following')==gid or task.get('belongsTo')==gid:task['category']=category
            self.write()
        return {'message':'Destino atualizado: '+{'auto':'automático','games':'Jogos / OPL','movies':'Filmes'}[category]+'.','category':category}
    def add_torrent(self,encoded,category='auto'):
        category=self.checked_category(category)
        if not isinstance(encoded,str) or len(encoded)>14*1024*1024:raise ValueError('Arquivo .torrent muito grande.')
        with self.actions:
            gid=self.call('aria2.addTorrent',[encoded,[],{'dir':str(self.downloads),'pause':'true'}])
            self.remember(gid,{'status':'paused','category':category})
            self.call('aria2.unpause',[gid]);self.call('aria2.saveSession')
        return {'gid':gid,'message':'Torrent adicionado à fila.'}
    def add(self,urls,source_page='',category='auto'):
        category=self.checked_category(category)
        if not isinstance(urls,list) or not 1<=len(urls)<=100:raise ValueError('Informe de 1 a 100 links')
        if source_page:source_page=self.url(source_page)
        cleaned=[]
        for value in urls:
            if isinstance(value,str) and value.strip().startswith('magnet:?'):cleaned.append(value.strip())
            else:cleaned.append(self.url(value))
        gids=[]
        with self.actions:
            for url in dict.fromkeys(cleaned):
                with self.lock:
                    duplicate=next((t for t in self.history.values() if t.get('sourceUrl')==url and t.get('status')in('active','waiting','paused')),None)
                if duplicate:
                    if category!='auto':self.category(duplicate['gid'],category)
                    gids.append(duplicate['gid']);continue
                gid=self.call('aria2.addUri',[[url],{'dir':str(self.downloads),'max-tries':'3','retry-wait':'5','pause':'true'}])
                self.remember(gid,{'status':'paused','sourcePage':source_page,'sourceUrl':url,'category':category})
                self.call('aria2.unpause',[gid])
                gids.append(gid)
            self.call('aria2.saveSession')
        return {'gids':gids,'message':str(len(gids))+' download(s) na fila. Links duplicados ativos foram reutilizados.'}
    def cancel(self,gid):
        task=self.task(gid)
        if task.get('status')in('active','waiting','paused'):self.call('aria2.forceRemove',[gid])
        else:self.rpc('aria2.removeDownloadResult',[gid])
        self.remember(gid,{'status':'removed','dismissed':True,'downloadSpeed':'0'})
        self.call('aria2.saveSession')
        return {'message':'Tarefa retirada da lista. Os arquivos no disco foram preservados.'}
