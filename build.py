#!/usr/bin/env python3
import pathlib,plistlib,subprocess,shutil,json,argparse,os
root=pathlib.Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description='Build the local JingXu macOS app')
parser.add_argument('--workspace', default=os.getenv('STUDIO_WORKSPACE',str(root)), help='Runtime directory containing work/ComfyUI and work/comfy-env')
parser.add_argument('--output', default=str(root/'dist'), help='Build output directory')
args=parser.parse_args()
workspace=pathlib.Path(args.workspace).expanduser().resolve()
out=pathlib.Path(args.output).expanduser().resolve();app=out/'镜序.app';contents=app/'Contents';resources=contents/'Resources'
(contents/'MacOS').mkdir(parents=True,exist_ok=True);resources.mkdir(exist_ok=True)
subprocess.run(['swiftc','-swift-version','5',str(root/'native/App.swift'),'-o',str(contents/'MacOS/JingXu'),'-framework','AppKit','-framework','WebKit'],check=True)
subprocess.run(['swiftc','-swift-version','5',str(root/'native/Keychain.swift'),'-o',str(contents/'MacOS/JingXuKeychain'),'-framework','Security'],check=True)
for name in ['backend','frontend']:
 target=resources/name
 if target.exists():shutil.rmtree(target)
 shutil.copytree(root/name,target,ignore=shutil.ignore_patterns('__pycache__','tests','*.pyc'))
(resources/'config.json').write_text(json.dumps({'workspace':str(workspace)},indent=2))
iconset=root/'native/AppIcon.iconset';iconset.mkdir(exist_ok=True)
if not (root/'native/icon.png').exists():subprocess.run(['swift',str(root/'native/Icon.swift'),str(root/'native/icon.png')],check=True)
for size in [16,32,128,256,512]:
 for scale in [1,2]:
  name=f'icon_{size}x{size}'+('@2x' if scale==2 else '')+'.png'
  subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(root/'native/icon.png'),'--out',str(iconset/name)],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(resources/'AppIcon.icns')],check=True)
info={'CFBundleName':'镜序','CFBundleDisplayName':'镜序','CFBundleIdentifier':'local.jingxu.storyboardstudio','CFBundleVersion':'3','CFBundleShortVersionString':'0.3.0','CFBundleExecutable':'JingXu','CFBundlePackageType':'APPL','CFBundleIconFile':'AppIcon','LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True,'NSAllowsArbitraryLoadsInWebContent':True}}
with open(contents/'Info.plist','wb') as f:plistlib.dump(info,f)
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
print(app)
