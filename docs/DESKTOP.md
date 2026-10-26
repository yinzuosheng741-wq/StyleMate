# StyleMate 桌面便携版

2026-10-22。本地个人应用，Windows x64；模型、视觉和天气仍按需连接配置的服务。

## 启动

解压完整便携包到可写目录，双击 `Start.cmd`。完整包的 `runtime/` 含 Python 和依赖，无需激活虚拟环境或预装 Python。请保留整个目录结构。

安装有 WebView2 时，启动器以 pywebview 打开独立窗口；关闭窗口后结束本次本地服务。`Start.cmd --browser` 改用系统浏览器，在启动器按 Ctrl+C 停止服务。

源码目录也可以使用 `.venv/Scripts/python.exe desktop.py`，但源码和仅含源码的 ZIP 不等于完整便携包。

默认打开 AI 对话，可在侧栏切换衣橱工作台；保留新建会话、历史、当前会话资料、衣橱和确认写入。

## 配置与数据

首次使用从 `.env.example` 复制为 `.env` 并配置服务。不配置模型时仍可使用规则和本地知识；图片识别需要视觉服务。所有原有确认写入流程继续生效。

数据位于应用目录 `data/`：SQLite 衣橱、上传图片、会话资料与向量索引。移动完整文件夹可同时移动数据；首次分发包不包含开发者的 `.env`、数据库、上传内容、运行日志或私人资料。停止应用后再备份整个 data 目录。

Windows 默认使用标准库 SQLite 精确向量检索，适合个人小型语料，避免当前机器原生 HNSW 写入崩溃。它仍使用配置的 Embedding，执行余弦相似度搜索；它不是近似索引。可设置 `STYLEMATE_VECTOR_BACKEND=chroma` 显式使用原 Chroma 后端，旧索引保留不覆盖。两个后端各自重建缓存，业务原文仍是权威来源。

## 工具和路由

对话入口新增多标签任务路由，合并知识、搭配、旅行、库存和购买相关只读工具。未识别意图保留只读兜底；只有当前用户消息明确提出对应增删改时开放相应提案工具。执行节点再次检查，模型绕过工具列表也无法执行未开放工具。

路由限制不等于身份认证。用户、会话、库存归属与 PendingAction 快照／TTL 仍由后端原有检查负责。

## 开发验证

```powershell
python -m pytest -q
python desktop.py --check
python desktop.py --no-ui --shutdown-after 1
python scripts/build_portable.py --output dist/StyleMate-portable.zip --runtime PATH_TO_PREPARED_EMBEDDED_PYTHON
```

`--check` 检查依赖与入口；HTTP 健康检查确认本地服务器启动，不等于在线模型联调。服务仅监听 127.0.0.1，启动器只清理自己创建的子进程。

## 后续迭代

近期工作为真实用户查询评测、参考图检索衣橱、穿着反馈与排序；保持显式偏好确认。历史 Hash Embedding 报告继续作为历史结果，不能据此宣称本轮真实模型召回率提升。
