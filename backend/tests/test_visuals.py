import base64, importlib.util, io, tempfile, unittest
from pathlib import Path
from PIL import Image
spec=importlib.util.spec_from_file_location('visuals',Path(__file__).parents[1]/'visuals.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
def sample(format='PNG',size=(64,32)):
    out=io.BytesIO();Image.new('RGB',size,'red').save(out,format)
    mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}[format]
    return f'data:{mime};base64,'+base64.b64encode(out.getvalue()).decode()
class VisualsTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_store_normalizes_stable_hash(self):
        a=v.store_image(self.folder,sample())['image_asset'];b=v.store_image(self.folder,sample())['image_asset']
        self.assertEqual(a,b)
        with Image.open(v.asset_path(self.folder,a)) as img:
            self.assertEqual(img.format,'JPEG');self.assertEqual(img.mode,'RGB');self.assertFalse(img.getexif())
        self.assertTrue(v.image_data_url(self.folder,a).startswith('data:image/jpeg;base64,'))
    def test_paths(self):
        for asset in ['../foo.jpg','img-xyz.jpg','/tmp/x','img-'+'a'*64+'.jpg']:
            with self.assertRaises(v.VisualError):v.asset_path(self.folder,asset)
        name='img-'+'b'*64+'.jpg';(self.folder/name).symlink_to('/etc/hosts')
        with self.assertRaises(v.VisualError):v.asset_path(self.folder,name)
    def test_invalid_uploads(self):
        for data in ['hello','data:text/plain;base64,aGVsbG8=','data:image/png;base64,aGVsbG8=',sample().replace('image/png','image/jpeg'),'data:image/jpeg;base64,!!!!!']:
            with self.assertRaises(v.VisualError):v.store_image(self.folder,data)
        with self.assertRaises(v.VisualError):v.store_image(self.folder,sample(size=(8,64)))
        with self.assertRaises(v.VisualError):v.store_image(self.folder,sample(size=(5000,4100)))
    def test_scale(self):
        asset=v.store_image(self.folder,sample(size=(3000,1500)))['image_asset']
        with Image.open(v.asset_path(self.folder,asset)) as image:self.assertEqual(image.size,(2048,1024))
    def test_fingerprint_and_decorate(self):
        p={'id':'p','character':{'name':'A','appearance':'短发','image_asset':'img-'+'b'*64+'.jpg'}}
        shot={'description':'草地','camera':'固定','prompt':'a boy','negative':'text','duration':2}
        fingerprint=v.fingerprint(p,shot)
        self.assertEqual(fingerprint,v.fingerprint(p,dict(shot,duration=10)))
        self.assertNotEqual(fingerprint,v.fingerprint(p,dict(shot,description='街道')))
        self.assertNotEqual(fingerprint,v.fingerprint(dict(p,character=dict(p['character'],appearance='长发')),shot))
        shot.update(image_asset='img-'+'a'*64+'.jpg',image_fingerprint=fingerprint);p['shots']=[shot]
        v.decorate(p);self.assertTrue(p['images_ready']);self.assertFalse(p['visual_mode'])
        shot['camera']='推进';v.decorate(p);self.assertFalse(p['images_ready'])
    def test_payload_and_response(self):
        asset=v.store_image(self.folder,sample())['image_asset']
        p={'character':{'name':'A','appearance':'短发','image_asset':asset}}
        body=v.seedream_payload(p,{'description':'草地'},'seedream-5-pro',self.folder)
        self.assertEqual(body['image'],[v.image_data_url(self.folder,asset)])
        self.assertNotIn('sequential_image_generation',body)
        self.assertNotIn('image',v.seedream_payload(p,None,'seedream-5-pro',self.folder))
        original=sample();self.assertEqual(v.response_image({'data':[{'b64_json':original.split(',')[1]}]}),original)
        with self.assertRaises(v.VisualError):v.response_image({'error':'secret'})
        with self.assertRaises(v.VisualError):v.seedream_payload({}, {},'model',self.folder)
if __name__=='__main__':unittest.main()
