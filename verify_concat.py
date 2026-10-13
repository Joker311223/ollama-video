"""Integration check: real ffmpeg, mocked Comfy transport, temporary project data."""
import importlib.util,pathlib,tempfile,json,threading,subprocess
from unittest.mock import patch
import av
root=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('studio',root/'backend/server.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
with tempfile.TemporaryDirectory() as temp:
 fixture=pathlib.Path(temp)/'fixture.mp4'
 subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=512x288:rate=12','-t','3','-c:v','libx264','-pix_fmt','yuv420p',str(fixture)],check=True)
 s.DATA=pathlib.Path(temp);pid='f'*32;s.CANCEL[pid]=threading.Event()
 shots=[dict(id=f'shot-{i}',title='fixture',description='测试画面',camera='固定',prompt='A boy lying on grass.',negative='',duration=2,seed=i) for i in [1,2]]
 p=dict(id=pid,title='test',status='rendering',revision=1,approved_revision=1,duration=4,shot_count=2,shots=shots);s.save(p)
 h={'outputs':{'58':{'images':[{'filename':'clip.mp4','type':'output','subfolder':''}]}}}
 with patch.object(s,'ensure_comfy'),patch.object(s,'compile_prompts',return_value={s.signature(x):x['prompt'] for x in shots}),patch.object(s,'request',side_effect=[{'prompt_id':'a'},{'prompt_id':'b'}]) as requests,patch.object(s,'await_prompt',return_value=h),patch.object(s,'urlopen',side_effect=lambda *a,**k:fixture.open('rb')):
  s.render_job(pid)
  assert requests.call_count==2
 result=s.load(pid)
 with av.open(str(s.directory(pid)/'final.mp4')) as c:
  duration=c.duration/1e6;frames=sum(1 for frame in c.decode(video=0))
 assert result['status']=='completed' and abs(duration-4)<.1,(result,duration)
 assert len([x for x in result['shots'] if x.get('video_url')])==2
 print(json.dumps({'multi_shot_concat':'passed','duration':duration,'frames':frames,'shots':2}))
