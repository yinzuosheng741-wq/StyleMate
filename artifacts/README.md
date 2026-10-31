# 评测证据与本地输出

| 位置 | 用途 |
| --- | --- |
| `evaluation_manifest.json` | 当前离线质量门槛使用的报告指针 |
| `agent_evaluation_knowledge_20261030.json` | 指针绑定的基线，保留原路径和原始内容 |
| `evaluation.json`、`agent_evaluation.json`、`agent_evaluation_20261022_round2.json` | 源码快照兼容报告；属于历史记录，不作为最新效果声明 |
| `reports/agent/` | 历次 Agent 固定评测 |
| `reports/benchmarks/` | 扩展测评、对照与题集审计 |
| `reports/knowledge/` | 知识来源审核与结构检查 |
| `reports/rag/` | RAG 前后对照、来源健康、回答样本及关键点诊断 |
| `reports/releases/` | 已完成发布检查的证据清单 |
| `local/` | 本地验证、历史日志压缩归档与整理记录，Git 忽略 |
| `validation/` | `scripts/validate.py` 默认输出，Git 忽略；CI 单独上传，保留 14 天 |

最近 RAG 诊断：[2026-10-31 结果](reports/rag/rag-critical-review-20261031.json)，解释与限制见[对应报告](../docs/reports/RAG_CRITICAL_REVIEW_20261031.md)。其中仍有 9 个待改进契约问题。

历史 JSON 的测量值、指纹及其内部原始路径不重写；移动只改变文件存放位置。复现实验应使用报告对应的代码、语料与题集版本。新实验另取文件名，不覆盖旧基线；仅将确认可公开的结果放入 `reports/`。密钥、数据库、用户照片与真实会话不得放入本目录的公开区域。
