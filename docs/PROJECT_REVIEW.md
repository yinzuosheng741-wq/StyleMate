# 两个项目的技术面试复核

## 结论

`cloth_ai` 已具备可展示的 Agent 产品骨架：LangGraph 有界编排、结构化会话记忆、BM25 + 向量 + RRF、工具超时/重试、库存归属校验、写操作二次确认和离线评测。主要问题不是“缺少 Agent 概念”，而是首次安装环境、运行入口和线上可观测性需要更清晰。

`6sv` 体现了遥感算法落地能力，但当前更像历史脚本集合。关键改进方向是配置化、可复现、输入安全、结构化输出和最小 CI fixture；本次已在 `../6sv` 落地第一批安全与参数校验改动。

## 大厂面试官可能追问

- Agent 为什么不会越权修改衣橱？答：工具参数使用 Pydantic 校验，写操作生成带 TTL 的 PendingAction，确认时重验 owner、会话、快照和当前库存。
- RAG 如何避免“看似相关但无来源”？答：BM25 与向量召回通过 RRF 融合，结果保留 `source_url` / 文档 ID；Embedding 不可用时降级 BM25。
- 记忆如何防止无限增长或错误持久化？答：只保存有界结构化事实；临时约束 24 小时过期；长期画像需显式确认。
- 6SV 如何保证结果可复现？答：固定 AOD fallback、显式记录 job 参数和 result.json；下一步将把输入元数据摘要、版本和质量统计写入结果。

## 回归清单

```powershell
python -m compileall -q cloth_ai/stylemate 6sv/6sv
python 6sv/6sv/verge/test_safety.py
cd cloth_ai
python -m pytest -q
python -m ruff check .
```

当前工作机缺少 `cloth_ai` 开发依赖（`langchain_core`、`chromadb`、`pypdf` 等），因此完整 pytest 需要先按 `requirements-dev.txt` 安装；静态编译和 6SV 安全回归已通过。
