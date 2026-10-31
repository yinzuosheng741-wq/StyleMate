# 可信知识增量与当前离线基线

日期：2026-10-28。审核主体为 Codex，逐项对照所列官方章节，不代表人工专家认证。没有用模型随机生成记录充数。

本页保留知识增量批次的快照。随后同日的洗护范围规则、当前报告和指标取舍见[洗护范围与验证](CARE_SCOPE_20261028.md)。

## 1. 本批实际变化

64 条原始知识总数保持不变；将 7 条 pending_review 改写为有来源定位、适用范围和限制的 reviewed。当前 17 条已审核来源摘要、21 条项目启发、26 条待审核。默认事实检索仍隔离后两类。

| ID | 处理主题 | 本次核对位置 |
| --- | --- | --- |
| care-sort-before-wash | 清洗前分类 | ACI / Step 1: Sort Your Laundry; Pro Tips |
| care-stain-before-dry | 污渍与干燥的先后 | ACI / Step 2 / Stain Removal Process |
| storage-dry-before-fold | 收纳前的干燥条件 | ACI / Step 6 |
| storage-fold-promptly | 整理与褶皱 | ACI / Step 6 |
| care-wash-detergent-dose | 洗涤剂用量依据 | ACI / Pro Tips |
| care-symbol-sequence | 洗护符号类别 | GINETEX / Care symbols overview |
| care-wash-symbol-temperature | 水洗温度与程序标记 | GINETEX / Washing introductory instructions |

官方来源：[ACI Laundry Basics](https://www.cleaninginstitute.org/cleaning-tips/clothes/laundry-basics)、[GINETEX Care symbols](https://www.ginetex.net/GB/labelling/care-symbols.asp)。历史 ACI 页面读取失败，本批已能读取并对照相应章节；访问状态变化不等于所有旧摘要自动得到支持。

记录改写时删除了未在指定章节核对的扩展结论，如通用防霉承诺、固定毫升数和对所有衣物的悬挂规则；符号解释不推导某件未提供洗标的衣物可以机洗或烘干。没有复制 GINETEX 图形。

逐条旧记录与本批定位保存在 `artifacts/reports/knowledge/knowledge_review_20261028.json`。GINETEX 改用实际核对的官方网页，新登记来源；ACI 的访问日期与所有链接该页面的记录保持一致。保留其余待审核条目的隔离状态。

## 2. 重新计算历史基线

三组历史题集未更改，召回算法未更改，Embedding 使用 offline_hash；只比较当前知识增加后的同一离线链路。

| 指标 | 上一版语料 | 本版语料 |
| --- | ---: | ---: |
| 已审核事实数 | 10 | 17 |
| 历史 60 题完整标注覆盖 | 10/60（16.67%） | 15/60（25.00%） |
| 部分覆盖 / 无覆盖 | 2 / 48 | 3 / 42 |
| 混合 Recall@5，保留全部 60 题 | 18.06% | 27.22% |
| 混合 MRR@5 | 16.11% | 25.14% |
| 混合 nDCG@5 | 16.02% | 24.64% |

报告：`artifacts/reports/agent/agent_evaluation_source_review_20261028.json`。`evaluation_manifest.json` 已切换到本报告；关于页面验证当前语料与三组题集指纹后才显示指标。

这些数值说明已发布知识覆盖增加后的历史标签命中情况，不代表算法提升、真实语义 embedding 效果或独立用户问题正确率。历史标签没有因此完成独立专家复标；15 个完整覆盖题的条件召回不能代替全部 60 题分母。新增 7 个正向检索回归是开发回归样例，不是独立评测集。

## 3. 验证与复现

- 检查官方来源定位、知识结构、审核隔离和访问日期。
- 新增 7 条真实 BM25 路径的来源检索回归，以及当前报告与题集分母绑定检查。
- 修正旧 UI 测试与源码包测试对历史报告文件名、历史百分比的固定断言；现在读取有效 manifest/report 验证展示和打包，仍能拦截写死旧指标。
- 将上一批真实线程测试中的截止时刻改为由线程启动事件确定，避免 Windows 亚秒等待精度影响错误分类断言；不放宽“失败、只调用一次、迟到结果不进入输出”的验证。
- 未配置或调用真实天气、付费文本模型、在线 embedding；未重建完整便携运行环境。

```powershell
python scripts/build_knowledge.py --check
python -m evaluation.run_agent_eval --output artifacts/agent_evaluation_local.json
python -m pytest -q
```

新建报告不会自动变成展示版本。只有复核其指纹、题集、分母和模型类型后，再更新 manifest。

本地全量 317 项通过，Ruff 全量、知识结构和健康检查通过；保留一条既有 DashScope 弃用提示。

## 4. 剩余缺口

26 条待审核知识仍需逐项核验。尺码、配色等主题的项目启发没有转成权威事实。真实检索器的后排结果仍可能不相关，当前有限适用性过滤不等于语义支持判断。下一阶段继续按任务补来源，并为用户实际问题建立有来源分组的独立标注，不以增加记录数量替代质量。
