import importlib.util, tempfile, unittest, json, threading
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('studio_server',Path(__file__).parents[1]/'server.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA;s.DATA=Path(self.tmp.name)
        self.old_config=s.seedance.CONFIG_DIR;s.seedance.CONFIG_DIR=s.DATA/'config'
    def tearDown(self): s.DATA=self.old;s.seedance.CONFIG_DIR=self.old_config;self.tmp.cleanup()
    def test_duration_bounds(self):
        with self.assertRaises(s.Invalid): s.settings({'brief':'故事','duration':31,'shot_count':1})
        with self.assertRaises(s.Invalid): s.settings({'brief':'故事','duration':True,'shot_count':1})
        self.assertEqual(s.settings({'brief':'故事','duration':20,'shot_count':2})['duration'],20)
    def test_pacing_allocation(self):
        self.assertEqual(s.settings({'brief':'故事','duration':100,'shot_count':12})['duration'],100)
        values=[6,8,9,10,7,8,9,10,6,9,8,10]
        shots=[{'duration':v} for v in values]
        self.assertEqual(s.allocate_duration(shots,100),shots)
        adjusted=s.allocate_duration([{'duration':v} for v in [3,5,7,9]*3],100)
        self.assertEqual(sum(x['duration'] for x in adjusted),100)
        self.assertGreater(adjusted[3]['duration'],adjusted[0]['duration'])
        for count in range(1,13):
            for total in range(count,count*30+1):
                result=s.allocate_duration([{'duration':i%10+1} for i in range(count)],total)
                self.assertEqual(sum(x['duration'] for x in result),total)
                self.assertTrue(all(1<=x['duration']<=30 for x in result))

    def test_thirty_second_shot(self):
        self.assertEqual(s.settings({'brief':'故事','duration':30,'shot_count':1})['duration'],30)
        shot=dict(id='s1',title='镜头',description='男孩',camera='固定',duration=30,prompt='A boy',negative='',seed=1)
        self.assertEqual(s.shots_valid([shot],{'shot_count':1,'duration':30})[0]['duration'],30)
        self.assertEqual(s.build_graph(shot,'c'*32)['55']['inputs']['length'],361)
        paced=s.allocate_duration([{'duration':4},{'duration':8},{'duration':8},{'duration':10}],100)
        self.assertEqual(sum(x['duration'] for x in paced),100)
        self.assertTrue(all(1<=x['duration']<=30 for x in paced))

    def test_path_traversal(self):
        for pid in ['../secret','a/../../x','a'*31,'g'*32]:
            with self.assertRaises(s.Invalid): s.directory(pid)
    def test_revision_and_busy(self):
        with self.assertRaises(s.Conflict): s.guard({'status':'draft','revision':2},{'revision':1})
        with self.assertRaises(s.Conflict): s.guard({'status':'rendering','revision':2},{'revision':2})
    def test_shot_duration(self):
        shot=dict(id='s1',title='镜头',description='男孩',camera='固定',duration=2,prompt='A boy',negative='',seed=1)
        with self.assertRaises(s.Invalid):s.shots_valid([shot],{'shot_count':1,'duration':3})
        self.assertEqual(s.shots_valid([shot],{'shot_count':1,'duration':2})[0]['prompt'],'A boy')
        self.assertEqual(s.shots_valid([shot],{'shot_count':1,'duration':100},match_total=False)[0]['duration'],2)
        for value in [0,31,1.5,True]:
            with self.assertRaises(s.Invalid):s.shots_valid([dict(shot,duration=value)],{'shot_count':1,'duration':2},match_total=False)
    def test_description_and_camera_drive_generation(self):
        shot=dict(id='s1',description='白衣女鬼清晰站在楼道中央',camera='缓慢推进',duration=2,prompt='A visible ghost in corridor',negative='',seed=1)
        original=s.signature(shot)
        changed=dict(shot,description='白衣女鬼向镜头走来')
        self.assertNotEqual(original,s.signature(changed))
        self.assertNotEqual(original,s.signature(dict(shot,camera='固定机位')))
        graph=s.build_graph(changed,'c'*32,'A white-clothed ghost walks toward the camera in a corridor. Slow camera push in.')
        self.assertEqual(graph['6']['inputs']['text'],'A white-clothed ghost walks toward the camera in a corridor. Slow camera push in.')
        self.assertNotIn('highest priority',graph['6']['inputs']['text'])
        self.assertEqual(s.build_graph(changed,'c'*32)['6']['inputs']['text'],changed['prompt'])
        self.assertEqual(graph['3']['inputs']['sampler_name'],'euler')
        self.assertEqual(graph['55']['inputs']['length'],49)
    def test_compile_prompts_caches_and_preserves_revision(self):
        shot=dict(id='s1',description='男孩躺在草坪',camera='固定',duration=2,prompt='A boy outdoors',negative='',seed=1)
        p={'id':'e'*32,'shots':[shot],'revision':7,'approved_revision':7,'status':'rendering'};s.save(p)
        prompt='A boy lies on a lawn under a blue sky. The camera stays still.'
        def fake(url,body=None,**kwargs):
            if url.endswith('/queue'):return {'queue_running':[],'queue_pending':[]}
            if url.endswith('/api/chat'):
                self.assertIn(shot['description'],body['messages'][1]['content'])
                self.assertIn(shot['camera'],body['messages'][1]['content'])
                return {'message':{'content':json.dumps({'prompts':[{'id':'s1','prompt':prompt+' --ar 9:16 --v 6.0'}]})}}
            return {}
        with patch.object(s,'request',side_effect=fake) as req:
            compiled=s.compile_prompts(p['id'],p)
            self.assertEqual(compiled[s.signature(shot)],prompt)
        saved=s.load(p['id']);self.assertEqual(saved['approved_revision'],7);self.assertEqual(saved['revision'],7)
        with patch.object(s,'request') as req:
            self.assertEqual(s.compile_prompts(p['id'],saved),compiled);req.assert_not_called()
        changed=dict(shot,description='男孩坐在草坪');saved['shots']=[changed]
        self.assertNotIn(s.signature(changed),compiled)
    def test_compile_rejects_wrong_id_without_saving_cache(self):
        shot=dict(id='s1',description='男孩',camera='固定',duration=2,prompt='Boy',negative='',seed=1)
        p={'id':'f'*32,'shots':[shot],'revision':1,'status':'rendering'};s.save(p)
        def fake(url,body=None,**kwargs):
            if url.endswith('/api/chat'):return {'message':{'content':'{"prompts":[{"id":"wrong","prompt":"A boy."}]}'}}
            return {}
        with patch.object(s,'request',side_effect=fake):
            with self.assertRaises(s.Invalid):s.compile_prompts(p['id'],p)
        self.assertNotIn('render_prompts',s.load(p['id']))
    def test_release_memory_only_when_idle(self):
        s.save({'id':'d'*32,'status':'rendering'})
        with patch.object(s,'render_job'),patch.object(s,'request',return_value={'queue_running':[],'queue_pending':[]}) as req:
            s.render('d'*32)
            self.assertEqual(req.call_args.args,(s.COMFY+'/free',{'unload_models':True,'free_memory':True}))
        with patch.object(s,'render_job'),patch.object(s,'request',return_value={'queue_running':[[1,'other']], 'queue_pending':[]}) as req:
            s.render('d'*32)
            self.assertEqual(req.call_count,1)
    def test_recovery(self):
        p={'id':'a'*32,'status':'rendering','revision':1};s.save(p);s.recover()
        self.assertEqual(s.load(p['id'])['status'],'interrupted')
    def test_cancel_scope(self):
        with patch.object(s,'request') as r:
            s.cancel_prompt('mine');r.assert_called_once_with(s.COMFY+'/queue',{'delete':['mine']})
    def test_confirm_and_render_http(self):
        server=s.ThreadingHTTPServer(('127.0.0.1',0),s.Handler)
        old=s.PORT;s.PORT=server.server_port
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        p={'id':'b'*32,'status':'draft','revision':1,'approved_revision':None,'duration':2,'shot_count':1,'title':'test','shots':[dict(id='s1',title='镜头',description='男孩',camera='固定',duration=2,prompt='A boy',negative='',seed=1)]}
        s.save(p)
        def post(action,data,token=s.TOKEN,origin=None):
            headers={'X-Studio-Token':token,'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            return urlopen(Request(f'http://127.0.0.1:{s.PORT}/api/projects/{p["id"]}/{action}',data=json.dumps(data).encode(),headers=headers))
        try:
            with self.assertRaises(HTTPError) as e:post('render',{'revision':1})
            self.assertEqual(e.exception.code,409)
            with self.assertRaises(HTTPError) as e:post('confirm',{'revision':1},origin='https://evil.com')
            self.assertEqual(e.exception.code,403)
            post('confirm',{'revision':1}).close()
            edit=dict(revision=1,title='edited',shots=p['shots'])
            edit['shots'][0]['camera']='推进'
            edit['shots'][0]['duration']=5
            req=Request(f'http://127.0.0.1:{s.PORT}/api/projects/{p["id"]}',data=json.dumps(edit).encode(),headers={'X-Studio-Token':s.TOKEN,'Content-Type':'application/json'},method='PUT')
            with urlopen(req) as response: edited=json.load(response)
            self.assertIsNone(edited['approved_revision'])
            self.assertEqual(edited['duration'],5)
            self.assertEqual(s.load(p['id'])['duration'],5)
            self.assertEqual(edited['revision'],2)
            with self.assertRaises(HTTPError) as e:post('render',{'revision':2})
            self.assertEqual(e.exception.code,409)
            post('confirm',{'revision':2}).close()
            with patch.object(s,'launch') as launch:
                post('render',{'revision':2}).close();launch.assert_called_once()
                with self.assertRaises(HTTPError) as e:post('render',{'revision':2})
                self.assertEqual(e.exception.code,409)
            media=s.directory(p['id'])/'test.mp4';media.write_bytes(b'0123456789')
            req=Request(f'http://127.0.0.1:{s.PORT}/media/{p["id"]}/test.mp4',headers={'Range':'bytes=2-5'})
            with urlopen(req) as response:
                self.assertEqual(response.status,206)
                self.assertEqual(response.read(),b'2345')
        finally:server.shutdown();server.server_close();s.PORT=old
if __name__=='__main__':unittest.main()
