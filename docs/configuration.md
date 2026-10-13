---
title: 配置参考
---

# 配置参考

[文档首页](README.md)

## 构建参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--workspace` | `STUDIO_WORKSPACE`，未设置时为源码根目录 | 包含 `work/ComfyUI` 和 `work/comfy-env` 的目录 |
| `--output` | 源码根目录下的 `dist` | app 输出目录 |

构建将运行环境路径写入 app 的 `Contents/Resources/config.json`。更换路径后，推荐重新构建。

## 后端环境变量

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STUDIO_WORKSPACE` | 后端所在项目根目录 | ComfyUI 与虚拟环境的上层运行环境 |
| `STUDIO_DATA_DIR` | `~/Movies/镜序` | 项目数据目录 |
| `STUDIO_PORT` | `8765` | 后端 HTTP 端口 |
| `STUDIO_TOKEN` | 每次启动随机生成 | 写接口令牌 |

以上变量适用于直接启动后端。桌面外壳会将端口设为 8765、数据目录设为 `~/Movies/镜序`，并使用构建时记录的运行环境；不能仅通过修改终端变量来改变桌面外壳的这些设置。

直接启动示例（不要与已有桌面服务同时占用同一端口）：

```sh
export STUDIO_WORKSPACE="/你的运行环境目录"
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" backend/server.py
```

## 视频引擎与 API Key

右上角可选择本地 Wan2.2 或 Seedance 云端；“引擎设置”支持 API Key、Model ID 和云端分辨率。详细步骤见 [Seedance 文档](seedance.md)。生成中禁止更改配置，每次生成保存一份不含密钥的配置快照。

## 当前本地固定配置

| 项目 | 当前值 |
| --- | --- |
| Ollama 地址 | `http://127.0.0.1:11434` |
| 分镜模型 | `qwen3.5:9b` |
| ComfyUI 地址 | `http://127.0.0.1:8188` |
| ffmpeg 可执行文件 | `/opt/homebrew/bin/ffmpeg` |
| 视频参数 | 512×288、12 fps、Euler、20 steps、CFG 5 |

上表本地参数尚未提供设置界面。修改模型需要同时核对输出格式、模型文件、工作流节点和硬件适配，不能只替换名称就保证兼容。

## 数据与日志

项目数据独立于 app，重建 app 不会自动删除项目。桌面启动的后端日志写入 `~/Library/Logs/镜序.log`；直接在终端启动则查看终端输出。

服务仅监听 `127.0.0.1`。写接口校验 Host、Origin 和 `X-Studio-Token`，这是本机单用户应用，不是面向公网的多用户服务。
