"""Real media integration tests; all state and media isolated in TemporaryDirectory."""
import base64,importlib.util,json,os,pathlib,subprocess,tempfile,threading,time,unittest,urllib.request,urllib.error

class ConverterTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='filmes-test-');cls.root=pathlib.Path(cls.tmp.name);cls.movies=cls.root/'Filmes';cls.movies.mkdir();cls.state=cls.root/'state';cls.config=cls.root/'auth.json';cls.config.write_text(json.dumps({'password':'integration-password'}))
  os.environ.update(FILMES_DIR=str(cls.movies),FILMES_STATE=str(cls.state),FILMES_AUTH_CONFIG=str(cls.config))
  spec=importlib.util.spec_from_file_location('converter',pathlib.Path(__file__).resolve().parents[1]/'maizonas/converter/server.py');cls.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.s);cls.s.initialize()
  cls.source=cls.movies/'Amostra com duas faixas.mkv'
  cls.cmd(['/usr/bin/ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=96x64:r=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-f','lavfi','-i','sine=frequency=880:sample_rate=48000','-t','2','-map','0:v','-map','1:a','-map','2:a','-c:v','ffv1','-c:a','pcm_s16le',str(cls.source)])
  cls.original=cls.source.read_bytes()
  # A real authored DVD with two different title lengths, NAV packets and AC-3.
  cls.dvd=cls.root/'DVD';cls.dvd.mkdir()
  for i,length in [(1,2),(2,3)]:
   cls.cmd(['/usr/bin/ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=720x480:r=30000/1001','-f','lavfi','-i','sine=frequency='+str(300*i)+':sample_rate=48000','-t',str(length),'-target','ntsc-dvd','-aspect','4:3',str(cls.root/f'title{i}.mpg')])
  xml=cls.root/'dvd.xml';xml.write_text(f'<dvdauthor dest="{cls.dvd}"><vmgm/><titleset><titles><video format="ntsc" aspect="4:3"/><audio format="ac3"/><pgc><vob file="{cls.root}/title1.mpg"/></pgc><pgc><vob file="{cls.root}/title2.mpg"/></pgc></titles></titleset></dvdauthor>')
  cls.cmd(['dvdauthor','-x',str(xml)],env={**os.environ,'VIDEO_FORMAT':'NTSC'})
  cls.iso=cls.movies/'DVD de teste.iso';cls.cmd(['genisoimage','-quiet','-dvd-video','-o',str(cls.iso),str(cls.dvd)])
  cls.http=cls.s.ThreadingHTTPServer(('127.0.0.1',0),cls.s.Handler);threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
 @classmethod
 def cmd(cls,args,**kwargs):
  r=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,**kwargs)
  if r.returncode:raise RuntimeError(r.stderr[-4000:])
  return r.stdout
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.tmp.cleanup()
 def api(self,path,body=None,auth=True):
  headers={'Authorization':'Basic '+base64.b64encode(b'ps2:integration-password').decode()} if auth else {}
  data=None
  if body is not None:headers['Content-Type']='application/json';data=json.dumps(body).encode()
  return urllib.request.urlopen(urllib.request.Request(self.base+path,data=data,headers=headers),timeout=20)
 def makejob(self,profile,name=None,titles=None):
  job=self.s.start_job({'source':name or self.source.name,'profile':profile,'resolution':'original','titles':titles or []});self.s.update(job,status='running');self.s.convert(job);return job
 def test_01_files_and_auth(self):
  with self.assertRaises(urllib.error.HTTPError):self.api('/api/status',auth=False)
  with self.api('/api/status') as r:self.assertEqual(len(json.load(r)['files']),2)
  for name in ['../auth.json','/etc/passwd','inexistente.mp4']:
   with self.assertRaises(ValueError):self.s.source_path(name)
  link=self.movies/'link.mkv';link.symlink_to(self.source)
  with self.assertRaises(ValueError):self.s.source_path(link.name)
  link.unlink()
  with self.assertRaises(ValueError):self.s.start_job({'source':self.source.name,'profile':'mp4_lossless','resolution':'720'})
 def test_02_lossless_avi(self):
  job=self.makejob('avi_lossless');self.assertTrue(job['outputs'][0]['report']['losslessVerified']);self.assertEqual(job['outputs'][0]['report']['audioTracks'],2);self.assertEqual(self.source.read_bytes(),self.original)
 def test_03_lossless_mp4(self):
  job=self.makejob('mp4_lossless');report=job['outputs'][0]['report'];self.assertEqual(report['sourceHashes'],report['outputHashes']);self.assertEqual(report['audioTracks'],2)
  with self.api('/api/download?job='+job['id']+'&index=0') as r:self.assertEqual(len(r.read()),job['outputs'][0]['size'])
  req=urllib.request.Request(self.base+'/api/download?job='+job['id']+'&index=0',headers={'Authorization':'Basic '+base64.b64encode(b'ps2:integration-password').decode(),'Range':'bytes=0-31'})
  with urllib.request.urlopen(req) as r:self.assertEqual(r.status,206);self.assertEqual(len(r.read()),32)
 def test_04_original_mkv_and_compatible(self):
  job=self.makejob('mkv_original');self.assertEqual(job['outputs'][0]['report']['sourceHashes'],job['outputs'][0]['report']['outputHashes'])
  for mode in ['avi_compatible','mp4_compatible']:
   job=self.makejob(mode);self.assertFalse(job['outputs'][0]['report']['losslessVerified'])
 def test_05_dvd_titles_and_navigation(self):
  info=self.s.analyze(self.iso.name);self.assertEqual(len(info['titles']),2);self.assertEqual(info['defaultTitle'],2)
  for profile in ['mp4_lossless','avi_lossless','mkv_original']:
   job=self.makejob(profile,self.iso.name,[1,2]);self.assertEqual(len(job['outputs']),2)
   for output in job['outputs']:self.assertTrue(output['report']['losslessVerified']);self.assertLessEqual(output['report']['timing']['maxTimestampDifferenceMs'],40)
  self.assertTrue(self.iso.is_file())
 def test_07_preserves_original_audio_offset(self):
  delayed=self.movies/'Audio atrasado na origem.mkv'
  self.cmd(['/usr/bin/ffmpeg','-v','error','-i',str(self.source),'-itsoffset','0.2','-i',str(self.source),'-map','0:v:0','-map','1:a','-c','copy',str(delayed)])
  for mode in ['mp4_lossless','avi_lossless']:
   job=self.makejob(mode,delayed.name)
   self.assertLessEqual(job['outputs'][0]['report']['timing']['maxTimestampDifferenceMs'],40)
   info=self.s.probe(self.movies/job['outputs'][0]['name']);self.assertEqual(len(info['audio']),2)
  delayed.unlink()

 def test_06_timing_rejection_and_cancel(self):
  original={'streams':[{'type':'video','first':0,'last':10,'backwards':0},{'type':'audio','first':0,'last':10,'backwards':0}],'videoTimes':[0,1,2]}
  bad=json.loads(json.dumps(original));bad['streams'][1]['first']=.5
  with self.assertRaises(ValueError):self.s.compare_timeline(original,bad)
  job=self.s.start_job({'source':self.source.name,'profile':'mp4_lossless'});job['cancel']=True
  with self.assertRaises(self.s.Cancelled):self.s.convert(job)
  self.assertEqual(self.source.read_bytes(),self.original)
 def test_08_web_queue_worker_and_cancellation(self):
  while not self.s.WORK.empty():self.s.WORK.get_nowait();self.s.WORK.task_done()
  with self.api('/api/jobs',{'source':self.source.name,'profile':'mp4_lossless','resolution':'original'}) as response:cancelled=json.load(response)
  with self.api('/api/cancel',{'id':cancelled['id']}) as response:self.assertTrue(json.load(response)['ok'])
  with self.api('/api/jobs',{'source':self.source.name,'profile':'mp4_lossless','resolution':'original'}) as response:job=json.load(response)
  thread=threading.Thread(target=self.s.worker,daemon=True);thread.start()
  try:
   for _ in range(200):
    row=self.s.JOBS[job['id']]
    if row['status'] in ('done','error'):break
    time.sleep(.1)
   self.assertEqual(row['status'],'done',row['phase']);self.assertEqual(self.s.JOBS[cancelled['id']]['status'],'cancelled');self.assertEqual(self.source.read_bytes(),self.original)
  finally:self.s.STOP.set();thread.join(timeout=15);self.s.STOP.clear()

if __name__=='__main__':unittest.main(verbosity=2)
