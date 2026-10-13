---
title: 开发与接口
---

# 开发与接口

[文档首页](README.md) · [贡献指南](../CONTRIBUTING.md)

## 组件

| 目录或文件 | 职责 |
| --- | --- |
| `native/App.swift` | AppKit 窗口、WKWebView、后端启动、菜单与导出 |
| `frontend/` | 本地页面、分镜编辑、状态展示及播放 |
| `backend/server.py` | HTTP API、项目持久化、Ollama / ComfyUI 任务协调 |
| `backend/seedance.py` | 火山方舟请求、普通设置与钥匙串访问 |
| `native/Keychain.swift` | 使用 Security.framework 存取 API Key |
| `backend/base_workflow.json` | 提交到 ComfyUI 前被填充的工作流模板 |
| `build.py` | Swift 编译、资源打包、图标与临时签名 |

后端使用进程内锁管理项目更新，并串行协调本应用的推理任务；项目 JSON 原子写入磁盘。只启动一个后端实例管理同一数据目录。

## 验证

在源码根目录、已设置 `STUDIO_WORKSPACE` 的终端运行：

```sh
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" -m unittest discover -s backend/tests -v
"$STUDIO_WORKSPACE/work/comfy-env/bin/python" verify_concat.py
node --check frontend/app.js
python3 build.py --workspace "$STUDIO_WORKSPACE"
```

单元测试包含版本确认、任务冲突、取消范围、恢复、路径校验和视频 Range 请求。拼接验证使用自动生成的素材及真实 ffmpeg，模拟 ComfyUI 通信，不代表真实模型推理验证。涉及工作流的改动还需单独验证真实短片。

## HTTP 接口

默认地址 `http://127.0.0.1:8765`。写操作发送 JSON 和 `X-Studio-Token` 请求头；令牌从 `/api/bootstrap` 获取。非创建、非取消的项目写操作携带当前 `revision`。不要将令牌提交到代码仓库。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/bootstrap` | 应用标识、令牌、项目和设置 |
| GET | `/api/preferences` | 读取引擎配置，仅返回密钥是否配置 |
| POST | `/api/preferences` | 保存 provider、seedance_model、seedream_model、resolution；可选 api_key 或 clear_key |
| POST | `/api/preferences/test` | 测试已保存密钥的 API 鉴权，不创建视频任务 |
| GET | `/api/health` | Ollama、ComfyUI、模型和 ffmpeg 状态 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{id}` | 单个项目及进度 |
| POST | `/api/projects` | 创建项目并开始生成分镜 |
| PUT | `/api/projects/{id}` | 保存标题与完整镜头列表 |
| POST | `/api/projects/{id}/character` | 保存单主角 name、appearance，携带 revision |
| POST | `/api/projects/{id}/image-upload` | 上传 data_url，target 为 character 或镜头 ID，携带 revision |
| POST | `/api/projects/{id}/image-generate` | 显式启动 Seedream 计费图片任务，携带 revision、target、seedream_model |
| POST | `/api/projects/{id}/image-confirm` | 确认现有分镜图适配当前文字，携带 revision、shot_id |
| POST | `/api/projects/{id}/confirm` | 确认当前分镜版本 |
| POST | `/api/projects/{id}/render` | 开始异步视频生成 |
| POST | `/api/projects/{id}/cancel` | 请求停止 |
| POST | `/api/projects/{id}/replan` | 使用新设置重新生成分镜 |
| GET | `/media/{id}/{filename}` | 项目媒体；视频支持单段 Range 请求 |

创建与重新规划字段示例（重新规划还需 `revision`）：

```json
{"brief":"男孩躺在草坪上，看着蓝天白云","style":"自然纪录片","duration":10,"shot_count":2}
```

编辑传入 `revision`、`title` 和完整 `shots` 数组。镜头包含 `id`、`title`、`description`、`camera`、`prompt`、`negative`、`duration`、`seed`。镜头 ID 不重复，镜头数必须匹配项目设置；保存编辑时，总时长由后端按镜头时长自动求和，不要求匹配初始总时长。

Seedance 渲染请求除了 `revision`，还需传入与当前设置一致的 `provider`、`seedance_model`、`resolution`，避免旧客户端意外选择付费引擎。bootstrap 包含 `api_version` 和 `preferences`；以实际后端返回版本为准。

创建返回 201；异步请求的成功响应只表示任务已启动，不表示视频已完成。轮询项目状态确认结果。常见错误码为 400（参数）、403（来源或令牌）、404（读取资源不存在）、409（忙碌或版本冲突）、500（内部错误），响应体包含 `error`。

## 状态与确认

| 状态 | 含义 |
| --- | --- |
| `planning` | 正在生成文字分镜 |
| `imaging` | 正在生成 Seedream 图片，锁定编辑与配置 |
| `draft` | 分镜待编辑或确认 |
| `approved` | 当前版本已确认 |
| `rendering` | 正在生成并合成视频 |
| `completed` | 成片完成 |
| `cancelled` | 任务已停止 |
| `failed` | 任务失败，查看 error |
| `interrupted` | 后端重启时发现未完成任务 |

只有 `approved_revision == revision` 才可渲染；编辑后递增版本并清除确认。客户端应展示服务器返回的状态，不能仅根据 HTTP 请求成功显示“生成完成”。


## 图片绑定与版本

新项目 `visual_mode: true`，旧项目默认 `false`。保存角色卡或上传图片会开启图片流程。项目包含 `character`（`name`、`appearance`、可选 `image_url` / `image_asset`），镜头包含 `image_url`、`image_asset`、`image_fingerprint` 和 `image_current`。`images_ready` 由服务端派生；仅供展示图片准备状态，不作为确认或渲染门槛。按镜头使用有效的已确认图片，其余镜头文生视频；不删除未使用图片。

上传 `data_url` 仅接受 JPEG / PNG / WebP，文件最大 8 MB，服务端验证并规范化为本地 JPEG。上传或生成后的分镜图需要显式 `/image-confirm`。角色或画面变化使相关确认失效；单纯时长改变保留图片确认，但更新视频版本。保存镜头时服务端保留图片绑定，不接受客户端伪造 `image_asset`。

图片生成使用已保存的 Seedream 配置，与视频 provider 独立，不能在测试中自动调用真实计费 API。`render` 请求仍只携带视频配置字段；图片 Model ID 不属于视频配置快照参数。
