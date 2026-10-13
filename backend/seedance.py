"""Volcengine Ark adapter. Key material is confined to Keychain and request memory."""
import json, os, re, subprocess, threading
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

BASE = 'https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks'
CONFIG_DIR = Path(os.getenv('STUDIO_CONFIG_DIR', str(Path.home()/'Library/Application Support/镜序'))).expanduser()
DEFAULTS = {'provider':'local', 'seedance_model':'doubao-seedance-2-5-260628', 'resolution':'720p'}
LOCK = threading.RLock()

class CloudError(Exception): pass
class Rejected(CloudError): pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def keychain(operation, value=None):
    root = Path(__file__).resolve().parent.parent
    helper = Path(os.getenv('STUDIO_KEYCHAIN_HELPER', str(root.parent/'MacOS/JingXuKeychain')))
    if not helper.is_file():
        helper = root/'dist/镜序.app/Contents/MacOS/JingXuKeychain'
    if not helper.is_file():
        if operation == 'status': return {'configured':False}
        raise CloudError('钥匙串组件未安装，请先重新构建并打开镜序。')
    payload = {'operation':operation}
    if value is not None: payload['value']=value
    try:
        result = subprocess.run([str(helper)], input=json.dumps(payload), capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise CloudError('无法访问 macOS 钥匙串，请解锁钥匙串并允许镜序访问。') from None
    if not data.get('ok'):
        raise CloudError('钥匙串访问失败，请解锁钥匙串并允许镜序访问。')
    return data

def preferences():
    with LOCK:
        config = dict(DEFAULTS)
        path = CONFIG_DIR/'settings.json'
        if path.exists():
            saved = json.loads(path.read_text())
            config.update({k:saved[k] for k in DEFAULTS if k in saved})
        return config

def public_preferences():
    config = preferences()
    try: config['key_configured']=keychain('status').get('configured',False)
    except CloudError: config['key_configured']=False
    return config

def save_preferences(body):
    with LOCK:
        config = preferences()
        config.update({k:body[k] for k in DEFAULTS if k in body})
        if config['provider'] not in ('local','seedance'): raise CloudError('请选择有效的视频引擎。')
        if not isinstance(config['seedance_model'],str) or not re.fullmatch(r'(?:doubao-seedance-|ep-)[A-Za-z0-9-]{1,100}',config['seedance_model']):
            raise CloudError('请填写方舟 Seedance Model ID 或推理接入点 ID。')
        if config['resolution'] not in ('720p','1080p'): raise CloudError('分辨率请选择 720p 或 1080p。')
        key = body.get('api_key','')
        if not isinstance(key,str) or len(key)>4096 or any(ord(c)<32 for c in key): raise CloudError('API Key 格式无效。')
        key=key.strip()
        if key and (not key.isascii() or any(c.isspace() for c in key)): raise CloudError('API Key 不应包含空白或非 ASCII 字符。')
        if key and body.get('clear_key'): raise CloudError('不能同时保存和删除 API Key。')
        # Write only the explicit non-secret allowlist to the settings file.
        CONFIG_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
        tmp=CONFIG_DIR/'settings.tmp'
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f: json.dump(config,f,ensure_ascii=False)
        try:
            if body.get('clear_key'): keychain('delete')
            elif key: keychain('set',key)
            os.replace(tmp,CONFIG_DIR/'settings.json')
        finally: tmp.unlink(missing_ok=True)
        return public_preferences()

def api_key():
    value=keychain('get').get('value','')
    if not value: raise CloudError('请先在右上角 API 设置中保存火山方舟 API Key。')
    return value

def task_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',value): raise CloudError('方舟返回了无效的任务 ID。')
    return value

def call(key, method='GET', suffix='', body=None):
    req=Request(BASE+suffix, data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),
                method=method, headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    try:
        with build_opener(NoRedirect()).open(req,timeout=60) as response:
            data=response.read()
            return json.loads(data) if data else {}
    except HTTPError as error:
        # Do not surface raw response bodies or signed URLs / echoed request secrets.
        messages={401:'API Key 无效或已过期',403:'当前 API Key 无权使用该服务或模型，请检查方舟授权',404:'模型、接入点或任务不存在',429:'请求额度或频率受限，请检查方舟账户余额和限额'}
        message=messages.get(error.code,'方舟请求失败，请在控制台检查模型权限与请求参数')
        if method=='POST' and (error.code>=500 or error.code==408):
            raise CloudError('方舟服务异常，创建结果不确定，请在控制台核对任务后再操作。') from None
        raise Rejected(f'{message}（HTTP {error.code}）。') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise CloudError('方舟连接异常，已记录的任务可重试查询；创建结果不确定时请先到控制台核对。') from None

def test_connection():
    call(api_key(),suffix='?page_size=1')
    return {'ok':True,'message':'API 鉴权通过；未创建视频任务。模型开通权限仍以实际生成为准。'}

def payload(shot,config,style=''):
    prompt=f"画面：{shot['description']}\n镜头运动：{shot['camera']}\n补充细节：{shot['prompt']}"
    if style: prompt+='\n风格：'+style
    if shot.get('negative'): prompt+='\n避免：'+shot['negative']
    body={'model':config['seedance_model'],'content':[{'type':'text','text':prompt}],
          'duration':max(4,shot['duration']),'ratio':'16:9','resolution':config['resolution'],
          'seed':shot['seed']%(2**32), 'watermark':False}
    # 1.0 has no audio parameter; all output is normalized to silent video locally.
    if not config['seedance_model'].startswith('doubao-seedance-1-0-'):body['generate_audio']=False
    return body
