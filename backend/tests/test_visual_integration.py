import base64, hashlib, importlib.util, io, json, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
spec=importlib.util.spec_from_file_location('visual_server',Path(__file__).parents[1]/'server.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)

def image_url():
    data=io.BytesIO();Image.new('RGB',(64,32),'blue').save(data,'PNG')
    return 'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()

class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA;s.DATA=Path(self.tmp.name)
        self.pid='a'*32;s.CANCEL[self.pid]=threading.Event()
        self.p={'id':self.pid,'revision':1,'approved_revision':None,'visual_mode':True,'status':'draft','title':'test','shot_count':1,'duration':2,'character':{'name':'男孩','appearance':'短发蓝衣'},'shots':[{'id':'s1','title':'镜头','description':'男孩坐在草坪','camera':'固定','prompt':'A boy on grass','negative':'text','duration':2,'seed':3}]}
        s.save(self.p)
    def tearDown(self):s.DATA=self.old;self.tmp.cleanup();s.CANCEL.pop(self.pid,None)
    def upload(self,target):self.p=s.visual_action(self.p,'image-upload',{'target':target,'data_url':image_url()})
    def test_upload_confirm_and_edit_invalidation(self):
        self.upload('character');self.upload('s1')
        with self.assertRaises(s.Conflict):s.require_images(self.p)
        self.p=s.visual_action(self.p,'image-confirm',{'shot_id':'s1'})
        s.require_images(self.p)
        original_asset=self.p['character']['image_asset'];self.p['character']['image_asset']='img-'+'f'*64+'.jpg'
        with self.assertRaises(s.Conflict):s.require_images(self.p)
        self.p['character']['image_asset']=original_asset
        changed=dict(self.p['shots'][0],duration=5,image_asset='evil',image_fingerprint='evil')
        clean=s.shots_valid([changed],self.p,match_total=False)
        self.assertEqual(clean[0]['image_asset'],self.p['shots'][0]['image_asset'])
        self.p['shots']=clean;s.require_images(self.p)
        self.p['shots'][0]['description']='男孩走在街上'
        with self.assertRaises(s.Conflict):s.require_images(self.p)
        s.visual_action(self.p,'image-confirm',{'shot_id':'s1'});s.require_images(self.p)
        with self.assertRaises(s.Invalid):s.visual_action(self.p,'image-confirm',{'shot_id':'character'})
    def test_character_change_and_legacy(self):
        self.upload('character');self.upload('s1');s.visual_action(self.p,'image-confirm',{'shot_id':'s1'})
        s.visual_action(self.p,'character',{'name':'男孩','appearance':'长发红衣'})
        with self.assertRaises(s.Conflict):s.require_images(self.p)
        legacy={'id':self.pid,'shots':[]};s.decorate_project(legacy)
        self.assertFalse(legacy['visual_mode']);s.require_images(legacy)
    def test_uncertain_image_not_resubmitted(self):
        model='doubao-seedream-5-0-pro-260628'
        with patch.object(s.seedance,'preferences',return_value={'seedream_model':model}),patch.object(s.seedance,'api_key',return_value='fake'),patch.object(s,'launch'):
            s.visual_action(self.p,'image-generate',{'target':'character','seedream_model':model})
        with patch.object(s.seedance,'api_key',return_value='fake'),patch.object(s.seedance,'image_call',side_effect=s.seedance.CloudError('timeout')):
            with self.assertRaises(s.seedance.CloudError):s.generate_image(self.pid)
        p=s.load(self.pid);p['status']='failed';s.save(p)
        with patch.object(s.seedance,'preferences',return_value={'seedream_model':model}),patch.object(s.seedance,'api_key',return_value='fake'),patch.object(s,'launch') as launch:
            with self.assertRaises(s.Conflict):s.visual_action(p,'image-generate',{'target':'character','seedream_model':model})
            launch.assert_not_called()
    def test_paid_success_is_saved_before_cancel(self):
        model='doubao-seedream-5-0-pro-260628'
        self.p['image_job']={'target':'character','model':model,'fingerprint':'request1'};s.save(self.p)
        def response(*args):
            s.CANCEL[self.pid].set()
            return {'data':[{'b64_json':image_url().split(',')[1]}]}
        with patch.object(s.seedance,'api_key',return_value='fake'),patch.object(s.seedance,'image_call',side_effect=response):
            with self.assertRaises(s.Cancelled):s.generate_image(self.pid)
        p=s.load(self.pid);self.assertTrue(p['character']['image_url']);self.assertEqual(p['image_requests']['request1']['status'],'succeeded')
    def test_image_signature_and_cloud_configuration(self):
        shot=self.p['shots'][0]
        old=hashlib.sha256(json.dumps({'pipeline_version':2,**{k:shot[k] for k in ['description','camera','prompt','negative','duration','seed']}},sort_keys=True).encode()).hexdigest()[:16]
        self.assertEqual(s.signature(shot),old)
        self.assertNotEqual(s.signature(shot),s.signature(dict(shot,image_asset='img-'+'a'*64+'.jpg')))
        config={'provider':'seedance','seedance_model':'model','resolution':'720p','seedream_model':'image-model'}
        with patch.object(s.seedance,'preferences',return_value=config),patch.object(s.seedance,'api_key',return_value='fake'):
            self.assertNotIn('seedream_model',s.render_configuration(config))
    def test_comfy_upload_uses_multipart(self):
        self.upload('character');asset=self.p['character']['image_asset'];result=io.BytesIO(json.dumps({'name':'image.jpg','subfolder':''}).encode())
        with patch.object(s,'urlopen',return_value=result) as opened:
            self.assertEqual(s.upload_comfy_image(self.pid,asset),'image.jpg')
            request=opened.call_args.args[0];self.assertIn('multipart/form-data',request.headers['Content-type']);self.assertIn(b'Content-Type: image/jpeg',request.data)
    def test_imaging_is_busy_and_recovered(self):
        self.p['status']='imaging';s.save(self.p)
        with self.assertRaises(s.Conflict):s.guard(self.p,{'revision':1})
        s.recover();self.assertEqual(s.load(self.pid)['status'],'interrupted')
    def test_http_visual_contract_gates_and_locks(self):
        server=s.ThreadingHTTPServer(('127.0.0.1',0),s.Handler);old=s.PORT;s.PORT=server.server_port
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        def call(action,body,method='POST',global_route=False):
            route='/api/preferences' if global_route else '/api/projects/'+self.pid+'/'+action
            request=Request(f'http://127.0.0.1:{s.PORT}'+route,data=json.dumps(body).encode(),method=method,headers={'Content-Type':'application/json','X-Studio-Token':s.TOKEN})
            try:
                with urlopen(request) as response:return response.status,json.load(response)
            except HTTPError as error:
                with error:return error.code,json.load(error)
        try:
            with patch.object(s.seedance,'call') as paid:
                self.assertEqual(call('confirm',{'revision':1})[0],409)
                self.p['approved_revision']=1;s.save(self.p)
                self.assertEqual(call('render',{'revision':1})[0],409)
                paid.assert_not_called()
            requests={'character':{'name':'Boy','appearance':'blue shirt'},'image-upload':{'target':'character','data_url':image_url()},'image-generate':{'target':'character','seedream_model':'model'},'image-confirm':{'shot_id':'s1'}}
            for action,body in requests.items():
                self.assertEqual(call(action,dict(body,revision=0))[0],409,action)
                self.assertEqual(call(action,dict(body,revision=1),method='PUT')[0],400,action)
            status,p=call('character',dict(requests['character'],revision=1));self.assertEqual(status,200)
            status,p=call('image-upload',dict(requests['image-upload'],revision=p['revision']));self.assertEqual(status,200)
            status,p=call('image-upload',{'revision':p['revision'],'target':'s1','data_url':image_url()});self.assertEqual(status,200)
            status,p=call('image-confirm',{'revision':p['revision'],'shot_id':'s1'});self.assertEqual(status,200);self.assertTrue(p['images_ready'])
            with patch.object(s.seedance,'preferences',return_value={'seedream_model':'model'}),patch.object(s.seedance,'api_key',return_value='fake'),patch.object(s,'launch') as launch:
                status,p=call('image-generate',{'revision':p['revision'],'target':'s1','seedream_model':'model'});self.assertEqual(status,200);self.assertEqual(p['status'],'imaging');launch.assert_called_once()
            self.assertEqual(call('character',{'revision':p['revision'],'name':'other','appearance':'red'})[0],409)
            with patch.object(s.seedance,'save_preferences') as prefs:
                self.assertEqual(call('',{},global_route=True)[0],409);prefs.assert_not_called()
        finally:
            server.shutdown();server.server_close();s.PORT=old
    def test_local_graph_contains_uploaded_start_image(self):
        self.upload('character');self.upload('s1');s.visual_action(self.p,'image-confirm',{'shot_id':'s1'})
        shot=self.p['shots'][0];submitted=[]
        def fake_request(url,body=None,**kwargs):
            if url.endswith('/prompt'):
                submitted.append(body['prompt']);return {'prompt_id':'test-prompt'}
            return {}
        def fake_encode(args,**kwargs):Path(args[-1]).write_bytes(b'encoded')
        with patch.object(s,'compile_prompts',return_value={s.signature(shot):'A boy on the grass.'}),patch.object(s,'ensure_comfy'),patch.object(s,'upload_comfy_image',return_value='uploaded.jpg') as upload,patch.object(s,'request',side_effect=fake_request),patch.object(s,'await_prompt',return_value={'outputs':{'58':{'videos':[{'filename':'video.mp4'}]}}}),patch.object(s,'urlopen',return_value=io.BytesIO(b'raw')),patch.object(s.subprocess,'run',side_effect=fake_encode),patch.object(s,'finish_video') as finish:
            s.render_job(self.pid)
        upload.assert_called_once_with(self.pid,shot['image_asset'])
        self.assertEqual(submitted[0]['90'],{'class_type':'LoadImage','inputs':{'image':'uploaded.jpg'}})
        self.assertEqual(submitted[0]['55']['inputs']['start_image'],['90',0]);finish.assert_called_once()
    def test_cloud_task_passes_actual_first_frame(self):
        self.upload('character');self.upload('s1');s.visual_action(self.p,'image-confirm',{'shot_id':'s1'})
        self.p['render_config']={'provider':'seedance','seedance_model':'doubao-seedance-2-5-260628','resolution':'720p'};s.save(self.p)
        captured=[]
        def cloud(key,method='GET',suffix='',body=None):
            if method=='POST':captured.append(body);return {'id':'cloud-test'}
            return {'status':'succeeded','content':{'video_url':'https://example.volces.com/video.mp4'}}
        with patch.object(s.seedance,'call',side_effect=cloud):
            s.cloud_task(self.pid,self.p['shots'][0],self.p,'fake',1)
        references=[x for x in captured[0]['content'] if x.get('role')=='first_frame']
        self.assertEqual(len(references),1)
        self.assertEqual(references[0]['image_url']['url'],s.visuals.image_data_url(s.directory(self.pid),self.p['shots'][0]['image_asset']))
if __name__=='__main__':unittest.main()
