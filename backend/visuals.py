"""Validated immutable image assets and Seedream request shaping; no credentials."""
import base64
import binascii
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
ASSET = re.compile(r'img-[0-9a-f]{64}\.jpg\Z')
MIMES = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}

class VisualError(Exception):
    pass

def _decode(data_url):
    if not isinstance(data_url, str) or len(data_url) > MAX_BYTES * 4 // 3 + 128:
        raise VisualError('图片不能超过 8 MB。')
    header, sep, encoded = data_url.partition(',')
    if not sep or header not in {f'data:{mime};base64' for mime in MIMES}:
        raise VisualError('只支持 JPEG、PNG 或 WebP 图片。')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise VisualError('图片编码无效，请重新选择图片。') from None
    if not data or len(data) > MAX_BYTES:
        raise VisualError('图片为空或超过 8 MB。')
    return header[5:-7], data

def store_image(folder, data_url):
    mime, data = _decode(data_url)
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format != MIMES[mime]:
                raise VisualError('图片格式与文件类型不一致。')
            if min(source.size) < 16:
                raise VisualError('图片宽高均需至少 16 像素。')
            if source.width * source.height > MAX_PIXELS:
                raise VisualError('图片不能超过 2000 万像素。')
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            normalized = ImageOps.exif_transpose(source)
            # Flatten transparency onto white rather than introducing black areas.
            if normalized.mode in ('RGBA', 'LA') or 'transparency' in normalized.info:
                rgba = normalized.convert('RGBA')
                rgb = Image.new('RGB', rgba.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
            else:
                rgb = normalized.convert('RGB')
            rgb.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            if min(rgb.size) < 16:
                raise VisualError('图片长宽比例过大，请裁剪后重试。')
            output = io.BytesIO()
            rgb.save(output, 'JPEG', quality=92, optimize=True)
            clean = output.getvalue()
    except VisualError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise VisualError('无法读取图片，请上传有效的 JPEG、PNG 或 WebP。') from None
    if len(clean) > MAX_BYTES:
        raise VisualError('处理后的图片超过 8 MB，请缩小后重试。')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    asset = 'img-' + hashlib.sha256(clean).hexdigest() + '.jpg'
    target = folder / asset
    if target.is_symlink():
        raise VisualError('图片路径无效。')
    if not target.exists():
        fd, name = tempfile.mkstemp(prefix='.image-', dir=folder)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(clean)
                f.flush()
                os.fsync(f.fileno())
            # Link is atomic and cannot overwrite an existing immutable asset.
            try:
                os.link(name, target)
            except FileExistsError:
                if target.is_symlink(): raise VisualError('图片路径无效。')
        finally:
            Path(name).unlink(missing_ok=True)
    return {'image_asset': asset}

def asset_path(folder, asset):
    if not isinstance(asset, str) or not ASSET.fullmatch(asset):
        raise VisualError('图片路径无效。')
    root = Path(folder).resolve()
    path = root / asset
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        raise VisualError('图片不存在，请重新上传或生成。')
    return path

def image_data_url(folder, asset):
    path = asset_path(folder, asset)
    if path.stat().st_size > MAX_BYTES:
        raise VisualError('图片超过 8 MB。')
    return 'data:image/jpeg;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')

def fingerprint(project, shot):
    character = project.get('character') or {}
    content = {'character': {k: character.get(k, '') for k in ('name', 'appearance', 'image_asset')},
               'shot': {k: shot.get(k, '') for k in ('description', 'camera', 'prompt', 'negative')}}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def decorate(project):
    project.setdefault('visual_mode', False)
    pid = project.get('id', '')
    character = project.get('character')
    if isinstance(character, dict):
        asset = character.get('image_asset')
        character['image_url'] = f'/media/{pid}/{asset}' if isinstance(asset, str) and ASSET.fullmatch(asset) else None
    shots = project.get('shots', [])
    for shot in shots:
        asset = shot.get('image_asset')
        valid = isinstance(asset, str) and bool(ASSET.fullmatch(asset))
        shot['image_url'] = f'/media/{pid}/{asset}' if valid else None
        shot['image_current'] = bool(valid and shot.get('image_fingerprint') == fingerprint(project, shot))
    project['images_ready'] = bool(shots) and all(shot['image_current'] for shot in shots)
    return project

def seedream_payload(project, shot_or_None, model, folder):
    character = project.get('character') or {}
    identity = f"角色姓名：{character.get('name', '')}。外貌设定：{character.get('appearance', '')}。"
    payload = {'model': model, 'size': '2K', 'response_format': 'b64_json', 'watermark': False}
    if shot_or_None is None:
        payload['prompt'] = '制作单个人物角色定妆照，单主体，非拼贴，横向16:9构图，人物清楚可辨，无文字无水印。' + identity + '清楚呈现脸型、发型、服装和道具，适合作为后续镜头的统一角色参考。'
    else:
        shot = shot_or_None
        asset = character.get('image_asset')
        if not asset:
            raise VisualError('请先上传或生成角色参考图。')
        payload['image'] = [image_data_url(folder, asset)]
        payload['prompt'] = ('生成电影分镜画面，横向16:9，无文字无水印。以参考图为人物身份依据，保持同一角色的脸型、发型、服装、道具一致。'
                             + identity + f"画面：{shot.get('description', '')}。镜头：{shot.get('camera', '')}。补充：{shot.get('prompt', '')}。避免：{shot.get('negative', '')}。")
    return payload

def response_image(result):
    try:
        encoded = result['data'][0]['b64_json']
        if not isinstance(encoded, str): raise ValueError()
        # Providers may return PNG or WebP bytes even for b64_json; inspect safely.
        _, data = _decode('data:image/jpeg;base64,' + encoded)
        with Image.open(io.BytesIO(data)) as image:
            mime = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}.get(image.format)
            if not mime: raise ValueError()
        return f'data:{mime};base64,{encoded}'
    except (KeyError, IndexError, TypeError, ValueError, OSError, VisualError, Image.DecompressionBombError):
        raise VisualError('图片服务未返回有效图片，请稍后重试。') from None
