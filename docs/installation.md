---
title: 安装与构建
---

# 安装与构建

[文档首页](README.md) · [使用手册](user-guide.md)

## 运行条件

- Apple Silicon Mac，macOS 14 或更高版本。
- 已验证环境：M5 Pro、48 GB 统一内存；这不是最低配置承诺。
- Xcode Command Line Tools、Python 3.11、Ollama、ffmpeg 和支持 Wan2.2 视频节点的 ComfyUI。
- 足够的模型与视频存储空间；下载前检查各模型文件大小。

## 1. 获取源码和工具

在终端运行。已安装的工具可跳过对应命令：

```sh
git clone git@github.com:Joker311223/ollama-video.git
cd ollama-video
xcode-select --install
brew install python@3.11 ffmpeg ollama
```

SSH 未配置时，可使用 `git clone https://github.com/Joker311223/ollama-video.git`。

## 2. 准备运行环境

下列命令应在源码根目录执行。`STUDIO_WORKSPACE` 指向包含 `work` 目录的运行环境根目录。

```sh
export STUDIO_WORKSPACE="$PWD"
mkdir -p "$STUDIO_WORKSPACE/work"
git clone https://github.com/Comfy-Org/ComfyUI.git "$STUDIO_WORKSPACE/work/ComfyUI"
python3.11 -m venv "$STUDIO_WORKSPACE/work/comfy-env"
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" -m pip install -r "$STUDIO_WORKSPACE/work/ComfyUI/requirements.txt" -r requirements.txt
```

复用已有环境时，将变量设置为已有目录，跳过克隆与创建环境，检查依赖即可。不要用新环境覆盖正在运行的环境。

## 3. 放置模型

ComfyUI 模型路径必须匹配内置工作流：

```text
$STUDIO_WORKSPACE/work/ComfyUI/models/
├── diffusion_models/wan2.2_ti2v_5B_fp16.safetensors
├── text_encoders/umt5_xxl_fp16.safetensors
└── vae/wan2.2_vae.safetensors
```

模型来源入口见[仓库首页的模型准备说明](../README.md#环境准备)。权重不包含在仓库或 app 中，使用时遵守对应模型许可。

启动 Ollama 应用，或在单独终端运行 `ollama serve`，然后下载分镜模型：

```sh
ollama pull qwen3.5:9b
```

## 4. 构建应用

```sh
python3 build.py --workspace "$STUDIO_WORKSPACE"
open dist/镜序.app
```

输出目录可通过 `--output /目标目录` 指定。构建产物使用本地临时签名，未经过 Apple 公证。

可以移动 app，但必须保留构建时记录的运行环境目录。换电脑或移动运行环境后，需要重新构建。

## 5. 首次验证

输入一个简单场景，例如“男孩躺在草坪上，抬头看蓝天白云”，选择 3 秒、1 个镜头。检查分镜，确认后生成视频并预览。ComfyUI 未启动时，应用会尝试自动启动。

生成速度与硬件有关；先验证短片，不要把长片任务当作安装检查。
