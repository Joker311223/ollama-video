# 常见问题

[文档首页](README.md)

## Ollama 未连接或缺少模型

确认 Ollama 应用或 `ollama serve` 已启动。在终端执行 `ollama list`，检查 `qwen3.5:9b`；缺失时执行 `ollama pull qwen3.5:9b`。下载失败与分镜生成失败应分别查看错误。

## ComfyUI 无法启动

检查构建时的运行环境目录是否仍存在，`work/comfy-env/bin/python` 是否可执行，以及 `work/ComfyUI/main.py` 是否存在。检查日志中是否有 Python 依赖缺失、端口占用或节点错误。

也可以在单独终端手动启动来查看完整报错：

```sh
cd "$STUDIO_WORKSPACE/work/ComfyUI"
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" main.py --listen 127.0.0.1 --port 8188 --fp32-vae --disable-auto-launch
```

确保没有重复启动另一个 ComfyUI 实例。

## 找不到模型或节点

按照[安装指南](installation.md)逐项核对文件名和目录。模型文件存在不代表完整下载，请核对文件大小。内置工作流需要 Wan2.2 和视频相关节点；ComfyUI 版本不兼容时查看具体缺失节点信息。

## 无法开始生成或提示版本冲突

先保存分镜并确认当前版本。任何编辑都会撤销之前的确认。提示“项目已更新”时重新载入项目；任务仍在运行时，应等待完成或取消后再修改。

## 进度不动、停止没有立即生效

模型加载、解码和编码阶段可能没有采样步数。先看项目状态和日志，不要反复点击生成。停止需要等待当前推理结束，尤其是已运行的 ComfyUI 镜头。

## 视频生成很慢或内存不足

先缩短到 3 秒、1 个镜头进行验证，关闭其他高内存应用，避免同时运行其他本地推理任务。当前实现固定使用 FP32 VAE；硬件适配及速度并不在所有 Mac 上得到验证。

## 视频无声、人物变形或跨镜头不一致

当前版本不生成音频。减少镜头中的主体与动作，保持各镜头对人物服装和外观的描述一致，缩短镜头后重试；文字提示不能保证身份一致性。

## app 移到其他电脑后打不开

app 依赖构建时记录的 Python 和 ComfyUI 路径，不含模型和运行环境。应在目标电脑重新准备环境并构建，不要只复制 app。

## 如何报告问题

到 [GitHub Issues](https://github.com/Joker311223/ollama-video/issues) 提供 macOS 版本、芯片与内存、复现步骤、错误信息及必要日志片段。提交前移除个人故事、路径、令牌等不希望公开的内容。
