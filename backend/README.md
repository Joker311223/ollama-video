# 镜序后端

使用现有 `work/comfy-env/bin/python server.py`，仅绑定 127.0.0.1。静态前端位于同级 frontend。

环境变量：STUDIO_PORT（8765）、STUDIO_DATA_DIR（~/Movies/镜序）、STUDIO_WORKSPACE（已有 ComfyUI 工作目录）、STUDIO_TOKEN（不设则随机生成）。bootstrap 返回同源 token，写操作要求 X-Studio-Token 且校验 Host/Origin。

文字分镜由本地 Ollama qwen3.5:9b 实际生成，失败不会用假分镜替代。确认版本后才可生成；编辑会撤销确认。单个镜头 1–10 秒，总时长 1–120 秒，1–12 镜头。视频采用 Wan2.2 5B / Euler20 / 512×288 / 12fps，MPS FP32 VAE。单镜头可耗时数分钟，长镜头更慢。模型之间没有人物身份锁定保证。

任务状态落盘并原子更新；应用重启将正在运行的任务标记 interrupted。重试可复用未变更且已完成的镜头。关闭窗口不终止后台进程。取消不打断其他用户的 ComfyUI：删除自身排队任务，已运行的任务安全结束后停止后续镜头。Ollama 请求取消也要等待当前响应。

运行测试：`python -m unittest discover -s tests -v`。
