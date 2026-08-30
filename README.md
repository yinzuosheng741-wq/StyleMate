# StyleMate 个人衣橱助手

StyleMate 是一个本地优先的个人衣橱应用。它使用 Streamlit 提供衣橱管理和穿搭界面，使用有边界的 LangGraph Agent 编排天气、库存、知识检索和写操作；库存真实性、穿搭约束与数据写入由确定性代码控制。

项目面向单用户本地使用和面试展示，不包含账号系统，也不作为多用户 SaaS 部署。

## 主要功能

- **本地衣橱**：衣物元数据保存到 SQLite，图片保存到本地目录，支持筛选、编辑和删除。
- **演示数据**：首次使用 local 模式时初始化 128 件演示单品，覆盖上装、下装、外套、连衣裙、鞋履、包袋和配饰。
- **图片入库**：校验图片格式与大小，多模态模型先判断主体是否属于服装、鞋履、包袋或配饰，再生成可人工修改的结构化草稿。
- **穿搭推荐**：只从当前衣橱选择衣物，并结合天气、季节、场景和用户明确提出的限制进行过滤与评分。
- **衣橱助手**：支持连续对话、历史会话、天气穿搭、购买建议、洗护问答和旅行行李规划。
- **知识检索**：对内置知识和当前会话文档执行 BM25 与向量召回，通过 RRF 融合结果并返回来源。
- **写操作保护**：Agent 的新增、修改和删除请求先生成待确认操作，用户确认后才写入本地数据库。
- **服务降级**：文本模型、Embedding、Chroma 或天气接口不可用时，保留确定性规则和 BM25 能力；多模态模型不可用时不会接受图片入库。

## 快速开始

推荐使用 Python 3.11。以下命令以 PowerShell 为例：

```powershell
git clone https://github.com/yinzuosheng741-wq/StyleMate.git
cd StyleMate
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m streamlit run app.py --server.port 8511
```

启动后在浏览器访问 `http://localhost:8511`。

仓库没有部署公开在线演示地址。GitHub 访客需要克隆项目后在本地运行。

### 首次启动

`.env.example` 默认使用 `APP_MODE=local`。当 `data/stylemate.db` 不存在时，应用会从 `assets/demo/wardrobe.json` 初始化 128 件演示衣物，并把对应图片复制到本地图片存储。

local 模式下的编辑和删除会永久保存。用户删除的演示衣物不会在下次启动时被迁移逻辑恢复。

## 模型与外部服务配置

不填写 API Key 也可以查看本地衣橱、运行确定性穿搭规则和使用 BM25 检索。图片识别、模型对话、在线 Embedding 和实时天气需要配置对应服务。

| 变量 | 用途 |
| --- | --- |
| `APP_MODE` | `local` 或 `demo`，默认 `local` |
| `LLM_PROVIDER` | 文本模型提供方标识 |
| `LLM_API_KEY` / `LLM_BASE_URL` | OpenAI-compatible 文本模型配置 |
| `TEXT_MODEL_NAME` | 文本模型名称 |
| `VISION_API_KEY` / `VISION_BASE_URL` | 多模态衣物识别配置 |
| `VISION_MODEL_NAME` | 多模态模型名称 |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` | 在线向量模型配置 |
| `EMBEDDING_MODEL_NAME` | Embedding 模型名称 |
| `AMAP_API_KEY` | 高德定位与天气配置 |

密钥只应写入本地 `.env` 或部署平台的 Secret 配置，不能提交到 Git。

## 实现边界

- LangGraph 只负责模型调用与结构化工具编排，单轮设置模型调用和工具调用上限。
- 推荐算法先执行库存、季节、温度和显式排除条件等硬约束，再计算场景、风格、配色和完整度评分。
- 会话上下文保留最近消息，并把主题、场景、地点、衣物编号和临时限制保存为有界的结构化事实。
- 长期偏好必须经用户确认后保存；衣橱写操作使用带有效期的 PendingAction 快照。
- RAG 检索结果必须具有可验证来源；有限改写后仍没有有效引用时明确返回未找到。
- 这是单 Agent 应用，不宣称多 Agent 协同、模型训练或面向生产环境的多用户能力。

## 数据与素材

以下内容会提交到 GitHub：

- 源码、测试、知识库和离线评测脚本；
- 128 张 768 x 768 WebP 演示图片；
- 演示衣物 manifest、素材作者、原图地址、尺寸和授权信息；
- 固定测试集生成的离线评测结果。

以下内容只保留在本地，并已通过 `.gitignore` 排除：

- `.env` 和真实 API Key；
- `data/stylemate.db`；
- `data/uploads/`、`data/chroma/` 和用户上传文档；
- `.venv/`、测试缓存和运行日志。

演示图片来自 Auckland Museum，通过 Wikimedia Commons 核验为 `CC BY 4.0`。完整来源与处理方式见 [assets/demo/SOURCE.md](assets/demo/SOURCE.md)，逐条元数据位于 [assets/demo/wardrobe.json](assets/demo/wardrobe.json)。

## 项目结构

```text
StyleMate/
├─ app.py                 # Streamlit 入口
├─ stylemate/             # 正式运行时代码
│  ├─ agent/              # LangGraph、工具、中间件、记忆与 AgentService
│  ├─ config/             # 环境配置
│  ├─ demo/               # 会话级样例数据
│  ├─ domain/             # Pydantic 领域模型
│  ├─ gateways/           # 多模态服务网关
│  ├─ model/              # 文本模型工厂
│  ├─ rag/                # 语料、文档切分与混合检索
│  ├─ repositories/       # Session 与 SQLite 仓储
│  ├─ rules/              # 确定性穿搭规则
│  ├─ services/           # 衣橱、初始化与画像服务
│  ├─ skills/             # 入库、穿搭、知识问答三个领域 Skill
│  ├─ storage/            # 本地与会话图片存储
│  └─ ui/                 # Streamlit 状态和组件
├─ assets/demo/           # 128 件演示衣物、manifest 和授权说明
├─ data/knowledge/        # 内置知识记录与来源
├─ evaluation/            # 固定离线评测
├─ artifacts/             # 已生成的评测结果
├─ scripts/               # 素材与知识库维护脚本
└─ tests/                 # 自动化测试
```

## 验证

安装开发依赖后运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python scripts/audit_demo_sources.py
python -m evaluation.run_eval --output artifacts/evaluation.json
python -m evaluation.run_agent_eval --output artifacts/agent_evaluation.json
```

当前仓库的最近一次验证结果：

| 检查项 | 结果 |
| --- | ---: |
| 自动化测试 | 202 passed |
| 演示衣物审计 | 128 件，7 个类别，全部 CC BY 4.0 |
| 穿搭规则离线用例 | 10 条 |
| Agent / RAG 离线用例 | 101 条 |
| 工具选择准确率 | 1.0000 |
| 写操作待确认保护率 | 1.0000 |
| RAG Recall@5 | 0.9500 |
| RAG MRR@5 | 0.9806 |
| RAG nDCG@5 | 0.9498 |

RAG 指标来自仓库内 60 条固定用例和可复现的本地 Hash Embedding，只用于验证检索、排序和融合链路，不代表某个在线 Embedding 模型的实际效果。延迟会受运行环境影响，因此不在项目介绍中承诺固定数值。在线模型需要单独配置并重新评测。
