#!/usr/bin/env python3
"""镜序 local-only storyboard and ComfyUI job server."""
import copy, hashlib, json, math, os, re, secrets, subprocess, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import urlparse, unquote
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.getenv('STUDIO_WORKSPACE', str(ROOT)))
DATA = Path(os.getenv('STUDIO_DATA_DIR', str(Path.home() / 'Movies/镜序'))).expanduser()
PORT = int(os.getenv('STUDIO_PORT', '8765'))
TOKEN = os.getenv('STUDIO_TOKEN') or secrets.token_urlsafe(32)
OLLAMA = 'http://127.0.0.1:11434'
COMFY = 'http://127.0.0.1:8188'
MODEL = 'qwen3.5:9b'
LOCK = threading.RLock()
GPU = threading.Lock()
CANCEL = {}
BUSY = {'planning', 'rendering'}
ID = re.compile(r'^[a-f0-9]{32}$')

class Invalid(Exception): pass
class Conflict(Exception): pass
class Cancelled(Exception): pass

def request(url, body=None, timeout=10):
    req = Request(url, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with urlopen(req, timeout=timeout) as r: return json.load(r)

def now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
def directory(pid):
    if not ID.fullmatch(pid): raise Invalid('项目 ID 无效')
    return DATA / pid

def save(p):
    with LOCK:
        folder=directory(p['id']); folder.mkdir(parents=True,exist_ok=True)
        p['updated_at']=now()
        temporary=folder / 'project.tmp'
        temporary.write_text(json.dumps(p,ensure_ascii=False,indent=2))
        os.replace(temporary,folder/'project.json')

def load(pid):
    with LOCK:
        try: return json.loads((directory(pid)/'project.json').read_text())
        except FileNotFoundError: raise Invalid('项目不存在')

def projects():
    DATA.mkdir(parents=True,exist_ok=True)
    result=[]
    for f in DATA.glob('*/project.json'):
        try: result.append(json.loads(f.read_text()))
        except (ValueError,OSError): pass
    return sorted(result,key=lambda p:p.get('updated_at',''),reverse=True)

def recover():
    for p in projects():
        if p['status'] in BUSY:
            p.update(status='interrupted',error='应用退出导致任务中断；可以重新规划或继续生成。'); save(p)

def integer(value, lo, hi, name):
    if type(value) is not int or not lo <= value <= hi: raise Invalid(f'{name} 必须为 {lo}–{hi} 的整数')
    return value

def text(value, name, limit, required=True):
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()): raise Invalid(f'{name} 无效或过长')
    return value.strip()

def settings(body):
    brief=text(body.get('brief'),'故事描述',5000)
    style=text(body.get('style','电影感'),'风格',300,False)
    duration=integer(body.get('duration'),1,120,'总时长')
    count=integer(body.get('shot_count'),1,12,'镜头数')
    if not count<=duration<=count*10: raise Invalid('每镜头需 1–10 秒，请调整总时长或镜头数')
    return dict(brief=brief,style=style,duration=duration,shot_count=count)

def shots_valid(shots,p,*,match_total=True):
    if not isinstance(shots,list) or len(shots)!=p['shot_count']: raise Invalid('镜头数量不符')
    output=[]; ids=set()
    for i,s in enumerate(shots):
        if not isinstance(s,dict): raise Invalid('镜头格式错误')
        sid=s.get('id',f'shot-{i+1}')
        if not isinstance(sid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',sid) or sid in ids: raise Invalid('镜头 ID 无效或重复')
        ids.add(sid)
        o={'id':sid,'duration':integer(s.get('duration'),1,10,'镜头时长'),'seed':integer(s.get('seed',20261013+i),0,2**53-1,'种子')}
        for k,limit in [('title',200),('description',2000),('camera',500),('prompt',6000),('negative',2000)]: o[k]=text(s.get(k,''),k,limit,k!='negative')
        output.append(o)
    if match_total and sum(s['duration'] for s in output)!=p['duration']: raise Invalid('分镜时长之和必须等于总时长')
    return output

def allocate_duration(shots,total):
    """Fit integer durations to the target while preserving the model's pacing."""
    weights=[shot['duration'] for shot in shots]
    if sum(weights)==total: return shots
    targets=[value*total/sum(weights) for value in weights]
    durations=[1]*len(shots)
    for _ in range(total-len(shots)):
        index=max((i for i,d in enumerate(durations) if d<10),key=lambda i:targets[i]-durations[i])
        durations[index]+=1
    return [dict(shot,duration=duration) for shot,duration in zip(shots,durations)]

def guard(p,body):
    if p['status'] in BUSY: raise Conflict('任务正在运行，先取消再编辑')
    if body.get('revision')!=p['revision']: raise Conflict('项目已更新，请刷新后重试')

def signature(s):
    return hashlib.sha256(json.dumps({'pipeline_version':2,**{k:s[k] for k in ['description','camera','prompt','negative','duration','seed']}},sort_keys=True).encode()).hexdigest()[:16]

def update(pid,**fields):
    with LOCK:
        p=load(pid); p.update(fields); save(p); return p

def check_cancel(pid):
    if CANCEL.get(pid,threading.Event()).is_set(): raise Cancelled()

def launch(pid,fn):
    CANCEL[pid]=threading.Event()
    def run():
        try:
            while not GPU.acquire(timeout=.5): check_cancel(pid)
            wake = None
            try:
                check_cancel(pid)
                if Path('/usr/bin/caffeinate').exists():
                    wake = subprocess.Popen(['/usr/bin/caffeinate','-i'])
                fn(pid)
            finally:
                if wake is not None:
                    wake.terminate()
                    try: wake.wait(timeout=3)
                    except subprocess.TimeoutExpired: wake.kill()
                GPU.release()
        except Cancelled: update(pid,status='cancelled',error=None,progress={'message':'已取消','shot_index':0,'shot_total':0})
        except Exception as e: update(pid,status='failed',error=str(e),progress={'message':'任务失败','shot_index':0,'shot_total':0})
    threading.Thread(target=run,daemon=True).start()

def plan(pid):
    p=load(pid)
    try:
        q=request(COMFY+'/queue',timeout=2)
        if not q.get('queue_running') and not q.get('queue_pending'): request(COMFY+'/free',{'unload_models':True,'free_memory':True})
    except Exception: pass
    update(pid,progress={'message':'正在用本地模型编写文字分镜','shot_index':0,'shot_total':p['shot_count']})
    schema={'type':'object','properties':{'title':{'type':'string'},'shots':{'type':'array','minItems':p['shot_count'],'maxItems':p['shot_count'],'items':{'type':'object','properties':{k:{'type':'integer' if k=='duration' else 'string'} for k in ['title','description','camera','duration','prompt','negative']},'required':['title','description','camera','duration','prompt','negative']}}},'required':['title','shots']}
    system='你是专业分镜导演。返回严格 JSON。标题、画面描述、镜头运动用中文；prompt 和 negative 用英文。每个 prompt 必须独立包含人物外观、环境、明确可见的主体和动作，重复同一人物的外观以保持一致。保留用户要求，不要将明确的鬼怪或主体改为空镜。根据每个镜头的叙事作用、动作复杂度和情绪节奏自由分配时长：交代或过渡镜头短一些，关键动作与情绪镜头长一些。不要默认平均分配，不要求总时长能被镜头数整除。每个镜头1到10秒整数，时长之和等于总时长，镜头数量必须精确。只输出分镜，不输出思考。面向 Wan2.2 视频模型，画幅为横向16:9。英文提示词只写自然画面描述，禁止 Midjourney 参数（--ar、--v 等）、Markdown、权重语法或用户未指定的其他比例。'
    try:
        result=request(OLLAMA+'/api/chat',{'model':MODEL,'stream':False,'think':False,'options':{'num_ctx':8192,'num_predict':3500},'format':schema,'keep_alive':'5m','messages':[{'role':'system','content':system},{'role':'user','content':json.dumps({k:p[k] for k in ['brief','style','duration','shot_count']},ensure_ascii=False)}]},timeout=600)
        check_cancel(pid)
        raw=json.loads(result['message']['content'])
        shots=allocate_duration(shots_valid(raw['shots'],p,match_total=False),p['duration'])
        shots=shots_valid(shots,p)
        update(pid,title=text(raw['title'],'标题',200),shots=shots,status='draft',error=None,progress={'message':'分镜已完成，请编辑并确认','shot_index':0,'shot_total':len(shots)})
    finally:
        try: request(OLLAMA+'/api/generate',{'model':MODEL,'keep_alive':0},timeout=30)
        except Exception: pass

def ensure_comfy(pid):
    try: request(COMFY+'/system_stats'); return
    except Exception: pass
    log= open(DATA/'comfy.log','a')
    env=dict(os.environ,PYTORCH_ENABLE_MPS_FALLBACK='1',PYTHONUNBUFFERED='1')
    subprocess.Popen([str(WORKSPACE/'work/comfy-env/bin/python'),'main.py','--listen','127.0.0.1','--port','8188','--fp32-vae','--disable-auto-launch'],cwd=WORKSPACE/'work/ComfyUI',env=env,stdout=log,stderr=log,start_new_session=True)
    log.close()
    for _ in range(120):
        check_cancel(pid)
        try: request(COMFY+'/system_stats'); return
        except Exception: time.sleep(1)
    raise RuntimeError('ComfyUI 未能启动，请查看 comfy.log')

def cancel_prompt(prompt_id):
    # Never interrupt another client's running prompt. Delete only our queued ID.
    request(COMFY+'/queue',{'delete':[prompt_id]})
    # ComfyUI versions with targeted interruption accept prompt_id; older ones may
    # ignore it, so do NOT call /interrupt. Running owned work is allowed to drain.

def await_prompt(pid,prompt_id,index,total):
    stop=threading.Event()
    def watch():
        import asyncio
        async def listen():
            import aiohttp
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(COMFY.replace('http:','ws:')+'/ws?clientId=studio-'+pid) as ws:
                        while not stop.is_set():
                            try: msg=await ws.receive(timeout=1)
                            except asyncio.TimeoutError: continue
                            if CANCEL[pid].is_set(): break
                            if msg.type != aiohttp.WSMsgType.TEXT: continue
                            event=json.loads(msg.data); d=event.get('data',{})
                            if d.get('prompt_id',prompt_id)!=prompt_id: continue
                            if event.get('type')=='progress':
                                update(pid,progress={'message':'正在采样','shot_index':index,'shot_total':total,'step':d.get('value'),'steps':d.get('max')})
                            elif event.get('type')=='executing':
                                label={'38':'加载文字模型','6':'编码画面描述','7':'编码负向提示','37':'加载视频模型','3':'正在采样','8':'正在解码（可能需要数分钟）','57':'正在封装视频','58':'正在保存镜头'}.get(str(d.get('node')))
                                if label: update(pid,progress={'message':label,'shot_index':index,'shot_total':total,'step':None,'steps':20})
            except Exception: pass # history polling remains authoritative
        asyncio.run(listen())
    threading.Thread(target=watch,daemon=True).start()
    try:
        return poll_prompt(pid,prompt_id,index,total)
    finally: stop.set()

def poll_prompt(pid,prompt_id,index,total):
    while True:
        if CANCEL[pid].is_set():
            cancel_prompt(prompt_id)
            # Keep GPU reservation until our active prompt finishes to avoid overlap.
            while True:
                q=request(COMFY+'/queue')
                if not any(x[1]==prompt_id for x in q.get('queue_running',[])): break
                time.sleep(2)
            raise Cancelled()
        h=request(COMFY+'/history/'+prompt_id)
        if prompt_id in h:
            h=h[prompt_id]
            if h.get('status',{}).get('status_str')=='error': raise RuntimeError('ComfyUI 生成失败：'+json.dumps(h['status'].get('messages',[]),ensure_ascii=False)[-1800:])
            if h.get('status',{}).get('completed'): return h
        time.sleep(2)

def render(pid):
    try:
        render_job(pid)
    finally:
        try:
            q=request(COMFY+'/queue',timeout=3)
            if not q.get('queue_running') and not q.get('queue_pending'): request(COMFY+'/free',{'unload_models':True,'free_memory':True})
        except Exception: pass

def compile_prompts(pid,p):
    cached=dict(p.get('render_prompts',{}))
    missing=[shot for shot in p['shots'] if signature(shot) not in cached]
    if not missing: return cached
    check_cancel(pid)
    update(pid,progress={'message':'正在整理已确认分镜的视频提示词','shot_index':0,'shot_total':len(p['shots'])})
    try:
        q=request(COMFY+'/queue',timeout=3)
        if not q.get('queue_running') and not q.get('queue_pending'): request(COMFY+'/free',{'unload_models':True,'free_memory':True})
    except Exception: pass
    schema={'type':'object','properties':{'prompts':{'type':'array','minItems':len(missing),'maxItems':len(missing),'items':{'type':'object','properties':{'id':{'type':'string'},'prompt':{'type':'string'}},'required':['id','prompt']}}},'required':['prompts']}
    system=('Translate the confirmed storyboard into clean English video descriptions. Chinese description and camera fields are the source of truth; the English prompt is supplementary detail only when consistent. '
            'Return one prompt for each requested ID, preserving exact IDs. Each prompt must be natural visual prose only, describing the visible subjects, actions, environment, lighting and camera motion. '
            'Never include instructions, priority labels, headings, commentary or Chinese. Do not mention translation or fields. Preserve requested visibly present characters, ghosts and creatures. '
            'Repeat consistent character appearance across shots. Do not add or remove story events. This is Wan2.2 landscape 16:9 video. Never output Midjourney flags, aspect-ratio parameters, markdown, weighting syntax or other aspect ratios. Return only the required JSON.')
    try:
        response=request(OLLAMA+'/api/chat',{'model':MODEL,'stream':False,'think':False,'options':{'num_ctx':8192,'num_predict':4000},'format':schema,'keep_alive':'5m','messages':[{'role':'system','content':system},{'role':'user','content':json.dumps({'style':p.get('style',''),'shots':[{k:shot[k] for k in ['id','description','camera','prompt']} for shot in missing]},ensure_ascii=False)}]},timeout=600)
        check_cancel(pid)
        result=json.loads(response['message']['content']).get('prompts')
        if not isinstance(result,list) or len(result)!=len(missing): raise Invalid('视频提示词整理失败：镜头数量不符')
        expected={shot['id']:shot for shot in missing}; compiled={}
        for entry in result:
            if not isinstance(entry,dict) or entry.get('id') not in expected or entry['id'] in compiled: raise Invalid('视频提示词整理失败：镜头 ID 不符')
            prompt=text(entry.get('prompt'),'视频提示词',6000)
            prompt=re.sub(r'--(?:ar|aspect|v|version|q|quality|s|stylize|seed|chaos|style)\s+[^\s,;]+', '', prompt, flags=re.I).strip()
            prompt=text(prompt,'视频提示词',6000)
            if re.search(r'[\u4e00-\u9fff]',prompt): raise Invalid('视频提示词整理失败：需要英文画面描述')
            if any(label in prompt.lower() for label in ['highest priority','primary visual description','follow only when','source of truth']): raise Invalid('视频提示词整理失败：包含说明性指令')
            compiled[entry['id']]=prompt
        for sid,prompt in compiled.items(): cached[signature(expected[sid])]=prompt
        update(pid,render_prompts=cached)
        return cached
    finally:
        try: request(OLLAMA+'/api/generate',{'model':MODEL,'keep_alive':0},timeout=30)
        except Exception: pass

def build_graph(s,pid,compiled_prompt=None):
    graph=json.loads((Path(__file__).parent/'base_workflow.json').read_text())
    graph['6']['inputs']['text']=compiled_prompt if compiled_prompt is not None else s['prompt']
    graph['7']['inputs']['text']=s['negative']
    graph['3']['inputs'].update(seed=s['seed'],steps=20,cfg=5.,sampler_name='euler')
    graph['55']['inputs'].update(width=512,height=288,length=max(49,math.ceil((s['duration']*12-1)/4)*4+1))
    graph['57']['inputs']['fps']=12
    graph['58']['inputs']['filename_prefix']=f'studio_{pid}_{s["id"]}'
    return graph

def render_job(pid):
    p=load(pid); compiled=compile_prompts(pid,p); check_cancel(pid); ensure_comfy(pid)
    folder=directory(pid); paths=[]
    for index,s in enumerate(p['shots']):
        check_cancel(pid)
        filename=f"{s['id']}-{signature(s)}.mp4"; dest=folder/filename
        if not dest.exists():
            update(pid,progress={'message':'正在生成镜头（含采样和解码，可能需要数分钟）','shot_index':index+1,'shot_total':len(p['shots']),'step':None,'steps':20})
            graph=build_graph(s,pid,compiled[signature(s)])
            queued=request(COMFY+'/prompt',{'prompt':graph,'client_id':'studio-'+pid},timeout=30)
            if queued.get('node_errors'): raise RuntimeError(str(queued['node_errors']))
            prompt_id=queued['prompt_id']; update(pid,active_prompt_id=prompt_id)
            h=await_prompt(pid,prompt_id,index+1,len(p['shots']))
            candidates=[v for out in h.get('outputs',{}).values() for key in ['images','videos','gifs'] for v in out.get(key,[]) if v.get('filename','').endswith('.mp4')]
            if not candidates: raise RuntimeError('ComfyUI 未返回视频文件')
            from urllib.parse import urlencode
            src=folder/'raw.mp4'
            with urlopen(COMFY+'/view?'+urlencode(candidates[0]),timeout=120) as r,src.open('wb') as f:
                import shutil; shutil.copyfileobj(r,f)
            check_cancel(pid)
            tmp=folder/'encoding.mp4'
            subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-y','-i',str(src),'-t',str(s['duration']),'-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(tmp)],check=True,capture_output=True)
            os.replace(tmp,dest); src.unlink(missing_ok=True)
        s['video_url']=f'/media/{pid}/{filename}'
        update(pid,shots=p['shots'],active_prompt_id=None)
        paths.append(dest)
    check_cancel(pid)
    update(pid,progress={'message':'正在合并视频','shot_index':len(paths),'shot_total':len(paths)})
    listing=folder/'concat.txt'; listing.write_text('\n'.join("file '"+str(path).replace("'","'\\''")+"'" for path in paths))
    final=folder/'final.mp4'; temporary=folder/'final.tmp.mp4'
    subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(temporary)],check=True,capture_output=True)
    check_cancel(pid); os.replace(temporary,final)
    update(pid,status='completed',video_url=f'/media/{pid}/final.mp4?v={p["revision"]}',error=None,progress={'message':'视频已完成','shot_index':len(paths),'shot_total':len(paths)})

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_json(self,data,status=200):
        b=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def origin_ok(self):
        host=self.headers.get('Host','')
        if host not in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']: return False
        origin=self.headers.get('Origin')
        return not origin or origin in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']
    def do_GET(self):
        try:
            if not self.origin_ok(): return self.send_json({'error':'来源无效'},403)
            path=unquote(urlparse(self.path).path)
            if path=='/api/bootstrap': return self.send_json({'app':'jingxu-studio','token':TOKEN,'projects':projects(),'settings':{'model':MODEL,'data_dir':str(DATA),'resolution':'512×288','fps':12,'max_shot_duration':10}})
            if path=='/api/projects': return self.send_json(projects())
            if path=='/api/health':
                health={'model':MODEL,'details':{},'ffmpeg':Path('/opt/homebrew/bin/ffmpeg').is_file(),'models':all((WORKSPACE/'work/ComfyUI/models'/x).is_file() for x in ['diffusion_models/wan2.2_ti2v_5B_fp16.safetensors','text_encoders/umt5_xxl_fp16.safetensors','vae/wan2.2_vae.safetensors'])}
                for name,url in [('ollama',OLLAMA+'/api/tags'),('comfy',COMFY+'/system_stats')]:
                    try:
                        result=request(url,timeout=2); health[name]=True
                        if name=='ollama': health['model_available']=any(x.get('name')==MODEL for x in result.get('models',[]))
                    except Exception as e: health[name]=False; health['details'][name]=str(e)
                return self.send_json(health)
            if path.startswith('/api/projects/'): return self.send_json(load(path.split('/')[-1]))
            if path.startswith('/media/'):
                parts=path.split('/')
                if len(parts)!=4: raise Invalid('路径无效')
                folder=directory(parts[2]).resolve(); target=(folder/parts[3]).resolve()
                if target.parent!=folder or target.suffix!='.mp4': raise Invalid('路径无效')
                return self.serve_file(target,'video/mp4')
            target=(ROOT/'frontend'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not target.is_relative_to((ROOT/'frontend').resolve()): raise Invalid('路径无效')
            import mimetypes
            return self.serve_file(target,mimetypes.guess_type(target)[0] or 'application/octet-stream')
        except (Invalid,FileNotFoundError): self.send_json({'error':'资源不存在'},404)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as e: self.send_json({'error':str(e)},500)
    def serve_file(self,path,ctype):
        size=path.stat().st_size; start=0; end=size-1; status=200
        value=self.headers.get('Range')
        if value:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
            if not match or not any(match.groups()): return self.send_json({'error':'无效 Range'},416)
            a,b=match.groups()
            if a: start=int(a); end=min(int(b) if b else end,end)
            else: start=max(0,size-int(b))
            if start>=size or start>end: return self.send_json({'error':'Range 超出文件'},416)
            status=206
        self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Accept-Ranges','bytes'); self.send_header('Content-Length',str(end-start+1)); self.send_header('X-Content-Type-Options','nosniff')
        if status==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start); remaining=end-start+1
            while remaining:
                chunk=f.read(min(1024*1024,remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining-=len(chunk)
    def do_POST(self): self.mutate()
    def do_PUT(self): self.mutate()
    def mutate(self):
        try:
            if not self.origin_ok() or not secrets.compare_digest(self.headers.get('X-Studio-Token',''),TOKEN): return self.send_json({'error':'请求未授权'},403)
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=200000: raise Invalid('请求大小无效')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise Invalid('请求格式无效')
            parts=urlparse(self.path).path.strip('/').split('/')
            with LOCK:
                if parts==['api','projects'] and self.command=='POST':
                    opts=settings(body); pid=uuid.uuid4().hex
                    p=dict(id=pid,title='新的故事',revision=1,approved_revision=None,status='planning',shots=[],error=None,video_url=None,progress={'message':'等待本地模型','shot_index':0,'shot_total':opts['shot_count']},**opts)
                    save(p); launch(pid,plan); return self.send_json(p,201)
                if len(parts) not in [3,4] or parts[:2]!=['api','projects']: raise Invalid('接口不存在')
                pid=parts[2]; p=load(pid); action=parts[3] if len(parts)==4 else 'edit'
                if action=='cancel':
                    if p['status'] in BUSY:
                        CANCEL.setdefault(pid,threading.Event()).set(); p['progress']['message']='正在停止：当前镜头或分镜请求完成后停止'; save(p)
                    return self.send_json(p)
                guard(p,body)
                if action=='edit' and self.command=='PUT':
                    edited_shots=shots_valid(body.get('shots'),p,match_total=False); edited_title=text(body.get('title',p['title']),'标题',200)
                    p.update(shots=edited_shots,title=edited_title,duration=sum(shot['duration'] for shot in edited_shots)); p['revision']+=1; p.update(approved_revision=None,status='draft',video_url=None,error=None)
                elif action=='confirm':
                    p['shots']=shots_valid(p['shots'],p); p.update(approved_revision=p['revision'],status='approved',error=None)
                elif action=='render':
                    if p['approved_revision']!=p['revision']: raise Conflict('请先确认当前版本的分镜')
                    p['shots']=shots_valid(p['shots'],p); p.update(status='rendering',error=None,progress={'message':'等待视频引擎','shot_index':0,'shot_total':len(p['shots'])}); save(p); launch(pid,render); return self.send_json(p)
                elif action=='replan':
                    p.update(settings(body)); p.update(revision=p['revision']+1,approved_revision=None,status='planning',shots=[],video_url=None,error=None,progress={'message':'等待本地模型','shot_index':0,'shot_total':p['shot_count']}); save(p); launch(pid,plan); return self.send_json(p)
                else: raise Invalid('请求方法或操作无效')
                save(p); return self.send_json(p)
        except Conflict as e: self.send_json({'error':str(e)},409)
        except (Invalid,ValueError,KeyError) as e: self.send_json({'error':str(e)},400)
        except Exception as e: self.send_json({'error':str(e)},500)

if __name__=='__main__':
    recover()
    print(f'镜序 http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
