import copy, importlib.util, io, json, shutil, subprocess, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request,urlopen

spec=importlib.util.spec_from_file_location('cloud_server',Path(__file__).parents[1]/'server.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
c=s.seedance

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA;self.old_config=c.CONFIG_DIR
        s.DATA=Path(self.tmp.name);c.CONFIG_DIR=s.DATA/'config'
        self.config={**c.DEFAULTS,'provider':'seedance'}
        self.shot=dict(id='shot-1',title='镜头',description='小狗在院门口奔跑',camera='固定监控',prompt='A dog running.',negative='watermark',duration=2,seed=2**40)
        self.p=dict(id='a'*32,title='test',status='rendering',duration=2,shot_count=1,revision=1,approved_revision=1,shots=[self.shot],render_config=dict(self.config),style='纪录片')
        s.save(self.p);s.CANCEL[self.p['id']]=threading.Event()
    def tearDown(self):
        s.DATA=self.old;c.CONFIG_DIR=self.old_config;self.tmp.cleanup()
    def test_preferences_never_persist_or_return_key(self):
        with patch.object(c,'keychain',return_value={'configured':True}) as vault:
            result=c.save_preferences({**self.config,'api_key':'test-secret-do-not-log'})
            self.assertNotIn('test-secret',json.dumps(result))
            text=(c.CONFIG_DIR/'settings.json').read_text();self.assertNotIn('test-secret',text)
            self.assertEqual((c.CONFIG_DIR/'settings.json').stat().st_mode & 0o777,0o600)
            self.assertIn(unittest.mock.call('set','test-secret-do-not-log'),vault.call_args_list)
            vault.reset_mock();c.save_preferences({'api_key':''})
            self.assertNotIn('set',[x.args[0] for x in vault.call_args_list])
            c.save_preferences({'clear_key':True});self.assertIn(unittest.mock.call('delete'),vault.call_args_list)
    def test_invalid_settings_do_not_touch_key(self):
        with patch.object(c,'keychain') as vault:
            for body in [{'provider':'evil'},{'resolution':'4k'},{'seedance_model':'https://evil'},{'api_key':'x\ny'},{'api_key':'x','clear_key':True}]:
                with self.assertRaises(c.CloudError):c.save_preferences(body)
            vault.assert_not_called()
    def test_cloud_requires_explicit_matching_config_and_key(self):
        with patch.object(c,'preferences',return_value=self.config),patch.object(c,'api_key',return_value='test'):
            with self.assertRaises(s.Conflict):s.render_configuration({})
            with self.assertRaises(s.Conflict):s.render_configuration({**self.config,'resolution':'1080p'})
            result=s.render_configuration(self.config);self.assertEqual(result['provider'],'seedance');self.assertNotIn('api_key',result)
        with patch.object(c,'preferences',return_value=self.config),patch.object(c,'api_key',side_effect=c.CloudError('missing')):
            with self.assertRaises(c.CloudError):s.render_configuration(self.config)
    def test_payload_uses_chinese_pacing_and_short_clip_minimum(self):
        result=c.payload(self.shot,self.config,'纪录片')
        self.assertEqual(result['duration'],4);self.assertEqual(result['ratio'],'16:9');self.assertFalse(result['generate_audio'])
        self.assertLess(result['seed'],2**32)
        self.assertIn(self.shot['description'],result['content'][0]['text']);self.assertIn(self.shot['camera'],result['content'][0]['text'])
        self.assertEqual(c.payload(dict(self.shot,duration=9),self.config)['duration'],9)
    def test_first_frame_payload(self):
        frame='data:image/jpeg;base64,fixture'
        result=c.payload(self.shot,self.config,first_frame=frame)
        self.assertEqual(result['ratio'],'adaptive')
        self.assertEqual(result['content'][1],{'type':'image_url','image_url':{'url':frame},'role':'first_frame'})
        self.assertNotIn('reference_image',json.dumps(result))
    def test_image_errors_are_safe_and_never_retried(self):
        for code in [400,401,408,500]:
            with patch.object(c,'build_opener') as opener:
                opener.return_value.open.side_effect=HTTPError(c.BASE,code,'secret',{},io.BytesIO(b'secret'))
                with self.assertRaises(c.CloudError) as result:c.image_call('secret',{})
                self.assertNotIn('secret',str(result.exception))
                self.assertEqual(isinstance(result.exception,c.Rejected),code in [400,401])
                self.assertEqual(opener.return_value.open.call_count,1)
    def test_image_request_uses_fixed_endpoint_without_redirect(self):
        with patch.object(c,'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"data":[]}')
            self.assertEqual(c.image_call('fixture',{'model':c.DEFAULTS['seedream_model']}),{'data':[]})
            req=opener.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,'https://ark.cn-beijing.volces.com/api/v3/images/generations')
            self.assertEqual(req.method,'POST')
            self.assertIsInstance(opener.call_args.args[0],c.NoRedirect)
    def test_480p_preferences_and_thirty_second_payload(self):
        config={**self.config,'resolution':'480p'}
        with patch.object(c,'keychain',return_value={'configured':False}):
            self.assertEqual(c.save_preferences(config)['resolution'],'480p')
            self.assertEqual(c.preferences()['resolution'],'480p')
        for frame in [None,'data:image/jpeg;base64,fixture']:
            result=c.payload(dict(self.shot,duration=30),config,first_frame=frame)
            self.assertEqual(result['duration'],30)
            self.assertEqual(result['resolution'],'480p')
        with self.assertRaises(c.CloudError):c.payload(dict(self.shot,duration=31),config)
        for model in ['doubao-seedance-2-0-260128','doubao-seedance-1-0-pro-250528']:
            with self.assertRaises(c.CloudError):c.payload(dict(self.shot,duration=30),dict(config,seedance_model=model))

    @unittest.skipUnless(Path('/opt/homebrew/bin/ffmpeg').is_file(),'ffmpeg required')
    def test_real_480p_thirty_second_output(self):
        self.p['shots'][0]['duration']=30;self.p['duration']=30
        self.p['render_config']['resolution']='480p';s.save(self.p)
        fixture=s.DATA/'fixture-long.mp4'
        subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:size=320x180:rate=24','-t','30','-c:v','libx264',str(fixture)],check=True)
        def download(pid,url,target):shutil.copyfile(fixture,target)
        with patch.object(c,'api_key',return_value='test'),patch.object(s,'cloud_task',return_value={'content':{'video_url':'mock'}}),patch.object(s,'download_cloud',side_effect=download):
            s.render(self.p['id'])
        import av
        with av.open(str(s.directory(self.p['id'])/'final.mp4')) as video:
            self.assertEqual((video.streams.video[0].width,video.streams.video[0].height),(854,480))
            self.assertAlmostEqual(video.duration/1e6,30,places=1)
            self.assertEqual(video.streams.video[0].frames,720)

    def test_signature_isolated_by_engine_model_resolution_and_edit(self):
        original=s.cloud_signature(self.shot,self.p)
        self.assertNotEqual(original,s.signature(self.shot))
        for field,value in [('seedance_model','ep-other'),('resolution','1080p')]:
            p=copy.deepcopy(self.p);p['render_config'][field]=value
            self.assertNotEqual(original,s.cloud_signature(self.shot,p))
        self.assertNotEqual(original,s.cloud_signature(dict(self.shot,duration=3),self.p))
    def test_submit_persists_id_before_poll_and_resume_does_not_resubmit(self):
        def fake(key,method='GET',suffix='',body=None):
            if method=='POST':return {'id':'cgt-test'}
            saved=s.load(self.p['id'])['cloud_tasks'][s.cloud_signature(self.shot,self.p)]
            self.assertEqual(saved['id'],'cgt-test')
            return {'status':'succeeded','content':{'video_url':'https://test.volces.com/clip.mp4'}}
        with patch.object(c,'call',side_effect=fake) as call:
            s.cloud_task(self.p['id'],self.shot,self.p,'secret',1)
            s.cloud_task(self.p['id'],self.shot,self.p,'secret',1)
            self.assertEqual(sum(x.args[1:]==('POST',) for x in call.call_args_list),1)
    def test_unknown_post_outcome_is_not_automatically_resubmitted(self):
        with patch.object(c,'call',side_effect=c.CloudError('timeout')) as call:
            with self.assertRaises(c.CloudError):s.cloud_task(self.p['id'],self.shot,self.p,'test',1)
            with self.assertRaisesRegex(c.CloudError,'重复扣费'):s.cloud_task(self.p['id'],self.shot,self.p,'test',1)
            self.assertEqual(call.call_count,1)
    def test_rejected_post_can_be_explicitly_retried(self):
        with patch.object(c,'call',side_effect=c.Rejected('401')) as call:
            for _ in range(2):
                with self.assertRaises(c.Rejected):s.cloud_task(self.p['id'],self.shot,self.p,'test',1)
            self.assertEqual(call.call_count,2)
    def test_cancel_only_queued_owned_task_and_preserve_running(self):
        for status in ['queued','running']:
            s.cloud_record(self.p['id'],s.cloud_signature(self.shot,self.p),{'id':'cgt-owned','status':status})
            s.CANCEL[self.p['id']].set()
            with patch.object(c,'call',return_value={'status':status}) as call:
                with self.assertRaises(s.Cancelled):s.cloud_task(self.p['id'],self.shot,self.p,'test',1)
                methods=[x.args[1] if len(x.args)>1 else 'GET' for x in call.call_args_list]
                self.assertEqual('DELETE' in methods,status=='queued')
                self.assertTrue(all(x.kwargs['suffix']=='/cgt-owned' for x in call.call_args_list))
            saved=s.load(self.p['id'])['cloud_tasks'][s.cloud_signature(self.shot,self.p)]
            self.assertEqual(saved['id'],'cgt-owned')
    def test_auth_probe_does_not_create_paid_task(self):
        with patch.object(c,'api_key',return_value='test'),patch.object(c,'call',return_value={'items':[]}) as call:
            self.assertTrue(c.test_connection()['ok']);call.assert_called_once_with('test',suffix='?page_size=1')
    def test_errors_do_not_echo_secrets(self):
        for code in [401,403,408,429,500]:
            error=HTTPError(c.BASE,code,'secret',{},io.BytesIO(b'{"error":"secret"}'))
            with patch.object(c,'build_opener') as opener:
                opener.return_value.open.side_effect=error
                with self.assertRaises(c.CloudError) as result:c.call('secret','POST',body={})
                self.assertNotIn('secret',str(result.exception))
                if code==408:self.assertNotIsInstance(result.exception,c.Rejected)
    def test_download_rejects_non_provider_urls(self):
        for url in ['file:///etc/passwd','http://127.0.0.1','https://evil.test/a','https://test.volces.com@evil.test/a']:
            with self.assertRaises(c.CloudError):s.download_cloud(self.p['id'],url,s.DATA/'bad.mp4')
    def test_cloud_route_never_calls_local_models(self):
        with patch.object(s,'render_cloud') as cloud,patch.object(s,'request') as local,patch.object(s,'render_job') as job:
            s.render(self.p['id']);cloud.assert_called_once();local.assert_not_called();job.assert_not_called()
    def test_settings_http_auth_and_render_lock(self):
        server=s.ThreadingHTTPServer(('127.0.0.1',0),s.Handler);old=s.PORT;s.PORT=server.server_port
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def post(body,token=s.TOKEN):
            return urlopen(Request(f'http://127.0.0.1:{s.PORT}/api/preferences',data=json.dumps(body).encode(),headers={'X-Studio-Token':token,'Content-Type':'application/json'}))
        try:
            with self.assertRaises(HTTPError) as error:post({},'invalid')
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError) as error:post(self.config)
            self.assertEqual(error.exception.code,409)
            s.update(self.p['id'],status='draft')
            with patch.object(c,'keychain',return_value={'configured':False}):
                with post(self.config) as response:self.assertEqual(json.load(response)['provider'],'seedance')
        finally:server.shutdown();server.server_close();s.PORT=old
    @unittest.skipUnless(Path('/opt/homebrew/bin/ffmpeg').is_file(),'ffmpeg required')
    def test_real_cloud_postprocessing_and_cache_reuse(self):
        fixture=s.DATA/'fixture.mp4'
        subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','4','-c:v','libx264',str(fixture)],check=True)
        def download(pid,url,target):shutil.copyfile(fixture,target)
        with patch.object(c,'api_key',return_value='test'),patch.object(s,'cloud_task',return_value={'content':{'video_url':'mock'}}) as tasks,patch.object(s,'download_cloud',side_effect=download),patch.object(s,'request') as local:
            s.render(self.p['id']);self.assertEqual(tasks.call_count,1);local.assert_not_called()
            s.render(self.p['id']);self.assertEqual(tasks.call_count,1)
        result=s.load(self.p['id']);self.assertEqual(result['status'],'completed')
        import av
        with av.open(str(s.directory(self.p['id'])/'final.mp4')) as container:
            stream=container.streams.video[0]
            self.assertEqual((stream.width,stream.height),(1280,720));self.assertAlmostEqual(container.duration/1e6,2,places=1)
            self.assertEqual(len(container.streams.audio),0)

if __name__=='__main__':unittest.main()
