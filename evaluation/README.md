# 评测程序与数据

| 程序 | 对应数据 | 用途 |
| --- | --- | --- |
| `run_eval.py` | `cases.json` | 确定性搭配与库存约束 |
| `run_agent_eval.py` | `agent_cases.json`、`graph_cases.json`、`rag_cases.json` | 历史固定路由、图、记忆、安全及检索回归 |
| `quality_gate.py` | 上述数据 + `artifacts/evaluation_manifest.json` 指向的基线 | 固定门槛，与普通扩展测评区分 |
| `benchmark.py` | `benchmark_cases.json`、`benchmark_validation_cases.json` | 任务、检索与可选真实 API 测量 |
| `rag_audit.py` | `rag_audit_cases.json` | 证据切块、摘录、上下文及知识覆盖诊断 |
| `rag_critical.py` | `rag_critical_cases.json` | 23 个关键契约、生产 @4/@5 对照及 8 个待审读挑战 |

例：`python -m evaluation.rag_critical --output artifacts/local/rag-critical-next.json`。新增输出使用新文件名，避免覆盖历史证据；该诊断默认离线，失败项写入报告，`--require-pass` 才要求契约全过。

可见开发题与固定回归不得称为独立保留集；检索召回、工具调用、证据支持和最终回答质量分别计量。扩库后核验标签对应的语料版本，禁止删除失败题或下调门槛制造进步。详见[题集政策](../docs/development/DATASET_POLICY.md)、[关键点检查](../docs/reports/RAG_CRITICAL_REVIEW_20261031.md)。
