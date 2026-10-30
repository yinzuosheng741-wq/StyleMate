# 出行衣橱助手 客户端指南

2026-10-30 更新：新增配置向导、模型连接测试、天气服务选择和完整便携状态。方案和实测见 [便携版说明](PORTABLE_20261030.md)。

项目仅维护 PySide6 / Qt Widgets 原生客户端，运行不依赖浏览器、HTTP 服务或 WebView。旧 `app.py`、网页启动器、Streamlit 配置和网页组件已移除。

## 启动与升级

源码环境安装 `requirements.txt` 后，运行 `python desktop.py`。双击 `Start.vbs` 隐藏控制台启动，`Start.cmd` 显示诊断输出。

独立分发目录为 `dist/native/出行衣橱助手/`，启动其中的 `出行衣橱助手.exe`。分发包包含 Python、Qt 和应用依赖，接收者无需安装 Python。移动时保留整个目录，放在可写位置。

源码运行继续使用原来的 `data/stylemate.db`、`data/uploads/` 和 `.env`；升级界面不迁移或清空用户数据。独立分发包默认从新衣橱开始。需要迁移时：

1. 退出旧客户端并备份整个 `data/` 目录。
2. 将完整的 `data/` 复制到新客户端目录。
3. 将已保存的 `data/config/` 和 `data/desktop/ui.ini` 一同迁移。旧 `.env` 可在首次启动向导导入，原文件无需删除。

首次启动会创建 128 件演示衣物；已有数据库不会被覆盖，用户已删除的样例不会在重启时恢复。

## 界面与操作

浅色侧栏包含“我的衣橱、今日搭配、衣橱助手、搭配收藏”，设置放在底部。设计参考 [LocalSend](https://github.com/localsend/localsend) 与 [Files](https://github.com/files-community/Files) 的操作组织方式，图标为项目自行绘制。

- **我的衣橱**：搜索名称、颜色、材质或风格；按类别、季节筛选，按时间或名称排序。每页 12 件，窗口宽度改变时自动排为 2–4 列。自定义类别与“四季”衣物也支持筛选。
- **添加衣物**：在右上角选择“上传照片识别”或“手动录入”。照片必须为有效 JPG/PNG/WEBP，最大 8 MB。识别后可编辑草稿，确认才保存。无视觉服务时仍可手动录入。
- **衣物详情**：查看大图与完整信息，编辑或删除。删除需要二次确认，并清理关联照片。
- **今日搭配**：选择场景、季节、城市和排除条件。搭配仅使用真实库存，支持收藏与取消收藏；规则分数只用于候选排序。
- **衣橱助手**：连续对话、历史会话、洗护、旅行与购买建议，来源链接可打开。快捷问题先填入输入框，可编辑后再发送。衣橱写操作显示中文字段的修改前后内容，确认才执行。
- **对话管理**：导入或移除 PDF/TXT/Markdown 会话资料、导出当前对话、确认后清空会话。入口位于会话列表下方。
- **设置**：分为“穿衣偏好、服务状态、数据与关于”三个页签。支持保存偏好、查看服务配置、打开数据目录、JSON 衣橱导出、完整备份及查看项目源码。

快捷键：`Ctrl+F` 搜索衣橱、`Ctrl+N` 新建对话、`Ctrl+Enter` 发送。草稿按会话自动保存，重启恢复上次会话；窗口位置也会恢复。这部分界面状态保存在应用目录 `data/desktop/ui.ini`，不再依赖系统注册表；衣橱数据备份不包含界面状态和服务密钥。

识别、搭配、对话和资料索引在后台运行。任务期间暂停业务操作，完成后恢复，以防重复提交或中断写入；失败时可重试，未发送草稿保留。

## 配置与备份

在“设置 → 服务状态 → 配置模型、天气与定位”中分别配置模型、视觉、Embedding 与天气服务，支持导入 `.env`、逐项测试连接、保存并即时应用。“服务状态”只表示配置情况；未配置时仍可使用手动衣橱、规则搭配和本地 BM25 检索。

在“设置 → 数据与关于 → 创建完整备份”生成 ZIP，包含 SQLite 在线快照、关联衣物照片、偏好、会话和资料，以及 SHA-256 文件清单。缺少关联图片时中止，不覆盖先前备份。密钥、日志、向量缓存与 Qt 界面状态不进入备份。

恢复时退出客户端，另存当前 `data/` 后，将备份中的 `data/stylemate.db` 和 `data/uploads/` 放回应用目录。密钥使用 `data/config/services.env` 中自己保存的配置。JSON 衣橱清单不包含照片与会话，不能代替完整备份。

## 验证与打包

```powershell
.venv\Scripts\python.exe desktop.py --check
.venv\Scripts\python.exe scripts/validate.py
.venv\Scripts\python.exe scripts/lock_runtime.py
.venv\Scripts\python.exe -m pip install pyinstaller==6.11.1
.venv\Scripts\python.exe scripts/build_desktop.py
```

`--check` 检查原生依赖，不启动业务。`--no-ui` 验证服务和存储初始化，`--shutdown-after 2` 验证窗口启动退出；后两者会在所在应用目录创建或使用真实本地数据，分发测试应使用独立目录。

打包脚本排除个人数据、密钥和网页运行时；如旧分发目录已有数据库，会拒绝覆盖。`scripts/build_portable.py` 可额外生成原生源码 ZIP，预备 runtime 必须包含 PySide6。`portable-lock.txt` 是 Windows / Python 3.12.4 验证环境快照，不是跨平台锁文件。

本地仓库 origin 关联 [yinzuosheng741-wq/travel-wardrobe-assistant](https://github.com/yinzuosheng741-wq/travel-wardrobe-assistant)。代码推送后，可在 Actions 手动运行 `Build Windows Desktop` 并下载产物；工作流不会自动发布 Release。离线验证不替代真实模型、视觉、Embedding 和天气的联调。

## 本次本地验证

2026-10-29，Windows / Python 3.12.4：统一验证全部通过，389 项测试通过，Agent 语句覆盖率 92.10%；10 条规则用例与 101 条 Agent/RAG/图用例的离线质量门槛通过。网页专属测试随入口移除，纯业务测试保留，补充原生窗口布局、图片入库确认、详情操作、快捷草稿、设置和写操作预览回归。

已检查常规和紧凑窗口截图。重新构建的独立 EXE 完成存储初始化（128 件演示衣物）及窗口启动退出验证，两项退出码均为 0。验证产物位于 `artifacts/client-only-validation/`，记录源码指纹；分发测试生成的临时衣橱在打包前清理，源码目录原有用户数据不受影响。本次未进行真实在线服务联调或推送 GitHub。
