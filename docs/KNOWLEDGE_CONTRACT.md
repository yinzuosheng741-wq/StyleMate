# 知识与推荐结果契约

本契约对应 2026-10-22 的实际代码。未实现的后续索引版本发布、审核界面和专家审批不在此声明完成。

## 规范知识记录

`stylemate/rag/models.py` 的 KnowledgeRecord 保留原有 ID、标题、正文、来源、主题和获取日期，新增：

| 字段 | 含义 |
| --- | --- |
| content_kind | source_summary 来源摘要；heuristic 项目启发 |
| review_status | pending_review、reviewed、quarantined、project_rule |
| source_locator | 原文章节/段落等定位，不使用浏览工具临时 ID |
| review_note / reviewer / reviewed_at | 处理理由、审核主体与日期；Codex 审查不等于专家认证 |
| applicability / limitations | 适用对象、条件和不能泛化的范围 |

新记录默认 pending_review。reviewed 需要来源、定位、审核依据、主体、日期和适用范围。项目启发不能标为 reviewed。当前没有自动语义真实性认证；字段齐全只是入库结构条件。

`load_builtin_records` 读取全部规范记录，用于保留审计历史；HybridRetriever 在构造时仅接收 reviewed 的 source_summary 进入默认内置事实检索。未审核条目不会参与关键词候选或当前内置向量同步；旧向量即使暂时残留，也必须通过当前规范候选 ID 映射才能返回。

`records` 视为构造后的知识快照。切换规范版本应重新建立 retriever，不在会话中绕过审核直接修改其列表。正式不可变版本与原子发布仍是后续工作。

用户上传资料继续走 owner/conversation 隔离通道，其结果标为 user_provided。该标记不等于内容权威或真实。

2026-10-26 增量：内置候选再执行明确材质/主题适用性过滤，最终向量命中也必须在此候选映射中。该过滤只覆盖有限语法；用户文档不使用内置主题分类。空召回改写保留原有任务，不添加新的洗护意图；通用冲锋衣不被自动等同于特定品牌技术。

## 检索与引用

RetrievalHit 以及 KnowledgeQASkill 的 results 传递 source_locator、review_status、applicability 和 limitations。2026-10-28 增量将 validation_scope 更新为 `source_format_and_finite_scope_not_answer_entailment`：URL 格式加有限材质/主题范围检查，仍不能当成“最终结论得到原文支持”的证明。此前版本为 source_format_only_not_answer_entailment。

洗护工具对未明确材质/洗标的类别问题返回 needs_clarification、missing_conditions 和空引用；通用洗标、分类等问题可检索一般规则。毛衣不再改写成羊毛，通用冲锋衣不借用 GORE-TEX 专属资料；最终 Skill 使用原问题复核，用户上传资料继续由 owner/conversation 通道管理。有限规则不等于任意语言表述的材质识别或语义认证。

无模型回答也显示首条结果的适用范围与限制。当前仍需后续完善主题相关性、跨条目冲突和逐项回答支持评测；有限规则和提示不能保证任意回答语义正确。

## 通用搭配与购买建议

通用搭配、购买建议属于 `recommendation_basis=project_heuristic`，返回规则解释和真实缺失条件；`sources=[]`。不会为固定规则附加未使用的检索链接。

- 通用搭配 `conditions.temperature_c=null` 表示未知，`missing_conditions` 提示补充；此时不根据虚构温度选择厚薄。
- 购买建议缺少季节与温度时，返回空 priorities 和 `season_or_temperature`；季节明确时不伪造温度。
- 品类齐全时不再兜底输出任意购买项；品类缺口也仅为候选，不等于用户必须购买。

这些字段是现有工具结果的增量约定，权限、工具执行状态和写入确认仍由既有工具执行器负责。
