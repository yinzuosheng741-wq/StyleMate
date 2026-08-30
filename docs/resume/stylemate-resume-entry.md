# StyleMate 个人衣橱助手｜项目经历

- 负责搭建基于 Streamlit + LangGraph 的本地优先衣橱助手，LLM 负责意图识别、参数补全和工具编排，业务规则负责库存、天气约束和写入安全；通过 Pydantic 契约、owner/conversation 隔离及模型/工具调用上限控制 Agent 行为，并覆盖 20 条图路由用例。
- 针对中文服饰知识构建 BM25 + Chroma 向量召回 + RRF 混合检索，支持内置知识库和 TXT/Markdown/PDF 用户文档，并加入来源校验、会话隔离和 BM25 降级；60 条固定检索用例 Recall@5 95.00%、MRR@5 98.06%、nDCG@5 94.98%。
- 将穿搭推荐和衣橱写操作下沉为确定性流程：先校验真实库存、季节、温度和用户限制，再进行场景评分；图片入库增加服饰主体和低置信度拦截，新增/修改/删除通过带快照与 TTL 的 PendingAction 确认后写入 SQLite；202 条自动化测试通过。

注：RAG 指标使用可复现的离线 Hash Embedding，仅用于验证检索链路，不代表在线 Embedding 模型效果。
