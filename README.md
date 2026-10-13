# 镜序 · Ollama Video

**从故事到文字分镜、主角参考图与分镜画面，确认后再生成视频。**

镜序（Storyboard Studio）是一款面向 Apple Silicon Mac 的本地视频创作工具。0.3 版通过 Ollama 生成可编辑的文字分镜，建立单主角参考卡，逐张确认分镜图片，再选择本地 ComfyUI + Wan2.2 TI2V-5B 或火山方舟 Seedance 逐镜头生成视频，再自动合成为成片。

```text
输入故事 → 文字分镜 → 主角卡与参考图 → 分镜图逐张确认 → 确认版本 → 图生视频 → 预览 / 导出
```

## 项目文档

🌐 **[在线文档网站](https://joker311223.github.io/ollama-video/)**

[文档首页](docs/README.md) · [安装与构建](docs/installation.md) · [使用手册](docs/user-guide.md) · [Seedance 云端配置](docs/seedance.md) · [配置参考](docs/configuration.md) · [常见问题](docs/troubleshooting.md) · [开发与接口](docs/development.md)

## 功能

- **文字分镜**：输入故事、风格、总时长和镜头数，生成结构化分镜。
- **主角与分镜图片**：上传已有图片，或明确点击 Seedream 云端生成（计费）；每张分镜图需人工确认。
- **先确认再生成**：编辑画面、镜头运动、时长及提示词；任何修改都会撤销此前确认。
- **中文创作**：确认的中文画面和镜头运动会由本地模型整理为英文渲染描述，英文提示词作为补充。
- **逐镜头进度**：查看生成状态、停止后续镜头、复用未修改且已完成的片段。
- **预览与导出**：自动拼接视频，在应用中播放或保存到指定位置。
- **本地项目**：项目保存在 `~/Movies/镜序`，关闭窗口后已开始的任务继续运行。

## 当前规格

| 项目 | 配置 |
| --- | --- |
| 桌面外壳 | Swift / AppKit / WKWebView |
| 分镜模型 | Ollama `qwen3.5:9b` |
| 图片模型 | 方舟 Seedream 5.0 Pro，或上传已有图片；本机未配置图片生成模型 |
| 视频模型 | 本地 Wan2.2 TI2V-5B / 火山方舟 Seedance |
| 输出 | 本地 512 × 288 / 12 fps；云端 720p 或 1080p / 24 fps，均为无声 MP4 |
| 时长 | 总时长 1–120 秒，1–12 个镜头，每镜头 1–10 秒 |
| 本地服务 | 应用 8765 / Ollama 11434 / ComfyUI 8188 |

建议每镜头 3–5 秒。模型效果存在随机性，跨镜头人物身份、复杂动作和长镜头稳定性不保证。单镜头可能需要数分钟，具体取决于硬件及参数。

## 环境准备

当前版本面向 **Apple Silicon / macOS 14 或更高版本**，已在 M5 Pro、48 GB 统一内存的 Mac 上验证短片流程；其他配置尚未验证。源码不包含模型权重，也不是安装即用的独立发行包。

需要 Xcode Command Line Tools（提供 Swift 编译器）、Python 3.11、[Ollama](https://github.com/ollama/ollama)、[ComfyUI](https://github.com/Comfy-Org/ComfyUI) 和 ffmpeg。当前 ffmpeg 固定使用 Apple Silicon Homebrew 路径 `/opt/homebrew/bin/ffmpeg`。

```sh
git clone git@github.com:Joker311223/ollama-video.git
cd ollama-video
xcode-select --install  # 已安装可跳过
brew install python@3.11 ffmpeg ollama
```

指定一个运行环境目录；下面以源码目录作为运行环境，也可以复用已有环境：

```sh
export STUDIO_WORKSPACE="$PWD"
mkdir -p "$STUDIO_WORKSPACE/work"
git clone https://github.com/Comfy-Org/ComfyUI.git "$STUDIO_WORKSPACE/work/ComfyUI"
python3.11 -m venv "$STUDIO_WORKSPACE/work/comfy-env"
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" -m pip install -r "$STUDIO_WORKSPACE/work/ComfyUI/requirements.txt" -r requirements.txt
```

按 [ComfyUI 官方 Wan2.2 示例](https://comfyanonymous.github.io/ComfyUI_examples/wan22/) 获取模型，并保持下列文件名和目录：

```text
运行环境目录/
└── work/
    ├── comfy-env/bin/python
    └── ComfyUI/
        └── models/
            ├── diffusion_models/wan2.2_ti2v_5B_fp16.safetensors
            ├── text_encoders/umt5_xxl_fp16.safetensors
            └── vae/wan2.2_vae.safetensors
```

模型需单独下载，占用较大磁盘空间，并遵守各自许可。先启动 Ollama（`ollama serve` 或打开 Ollama 应用），再运行：

```sh
ollama pull qwen3.5:9b
```

ComfyUI 未运行时，应用会尝试通过上述虚拟环境自动启动，并使用 `--fp32-vae`。请确保安装版本支持工作流里的 Wan2.2 和视频节点。

## 构建与打开

在源码目录运行：

```sh
python3 build.py --workspace "$STUDIO_WORKSPACE"
open dist/镜序.app
```

默认产物为 `dist/镜序.app`，可用 `--output /目标目录` 修改输出位置。构建会记录运行环境的绝对路径；可将 app 移到“应用程序”，但运行环境目录需要保留。移到其他电脑后，需要重新准备依赖并构建。

应用使用本地临时签名，未经过 Apple 公证。

## 使用方式

1. 输入故事、风格、总时长及镜头数量，点击生成分镜。
2. 编辑画面、镜头运动和时长；总时长自动随分镜更新，中英文描述有冲突时一起调整。
3. 保存主角姓名与外观，上传或用 Seedream 生成主角参考图。
4. 为每个镜头上传或生成分镜图，逐张确认画面；全部确认后再确认分镜版本并生成视频。
5. 完成后预览或导出；通过“文件 → 在 Finder 中查看项目”找到原始项目。

上传支持不超过 8 MB 的 JPEG / PNG / WebP，应用会规范化为本地 JPEG。所有图片都可直接上传，无需调用图片 API；本地视频由 Wan2.2 生成，Ollama 只负责文字。详情见[角色与分镜图片](docs/character-images.md)。

“停止”会删除本应用的排队任务；正在生成的 ComfyUI 镜头会先完成，然后停止后续镜头。请保持供电、不要合上屏幕。应用仅在任务运行期间阻止闲置睡眠。

## 开发与验证

```text
backend/         Python 本地 API、任务管理、ComfyUI 工作流与单元测试
frontend/        HTML / CSS / JavaScript，无前端构建依赖
native/          Swift 桌面窗口、菜单、导出及图标源文件
build.py         macOS 应用打包脚本
verify_concat.py 使用合成测试素材验证真实 ffmpeg 拼接
```

```sh
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" -m unittest discover -s backend/tests -v
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" verify_concat.py
node --check frontend/app.js  # 可选，需要 Node.js
```

也可以直接运行 `backend/server.py`，浏览器访问 `http://127.0.0.1:8765`。配置项见 [后端说明](backend/README.md)。若本机已有应用服务，不要同时启动第二个实例。

## 数据与排障

- 项目与视频：`~/Movies/镜序`
- 应用日志：`~/Library/Logs/镜序.log`
- Seedream 默认使用 `doubao-seedream-5-0-pro-260628`，与 Seedance 共用方舟 API Key，但需分别开通模型权限。只有明确点击相应生成按钮才会提交云端计费请求；选择引擎、保存设置不生成图片或视频。
- 默认使用本地引擎；切换 Seedance 并开始生成后，分镜内容发送到火山方舟并按账户账单计费。API Key 存放在 macOS 钥匙串。
- Ollama 未连接：检查本地服务以及 `qwen3.5:9b` 是否已下载。
- ComfyUI 启动失败：检查运行环境路径、Python 依赖、模型文件名和日志。
- 退出窗口不会终止后台任务；后台进程意外中断后，重启会标记中断项目，可重新开始生成。

本仓库仅包含应用源码与文档，不包含模型、生成视频、个人项目或虚拟环境。
