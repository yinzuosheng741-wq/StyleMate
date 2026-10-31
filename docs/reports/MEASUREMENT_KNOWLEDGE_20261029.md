# 测量知识与来源增量

日期：2026-10-29。审核主体为 Codex；不代表人工专家认证。

## 业务问题和变化

原库几乎没有已审核的尺码测量知识。即使增加记录，“商品尺寸与人体尺寸有什么区别”等对话也可能无法进入知识工具：原路由偏向穿搭和身高体重参考，没有为测量说明开放知识能力。

本批统一测量知识意图词，由 Skill 路由授权 `rag_search`，公开聊天服务直接调用确定性知识链路。正常定义问题无需文本模型；身高体重参考和测量知识分别保留原有用途。没有扩大写操作权限或对具体尺码作合身保证。

## 核对的来源与记录

| 记录 | 处理 | 原文定位 |
| --- | --- | --- |
| care-label-complete | 重写原待审核条目，发布 | FTC / FAQs / Label Content / components such as linings, trim, buttons or zippers |
| size-measure-same-garment | 重写原待审核条目，发布 | UNIQLO HK / How to Measure Product Size / introductory notes |
| size-body-versus-product | 新增 | UNIQLO HK / Difference Between Product Measurements and Body Measurements |
| size-flat-body-width | 新增 | UNIQLO HK / Tops / B. Body Width |

来源：[FTC 护理说明问答](https://www.ftc.gov/business-guidance/resources/clothes-captioning-complying-care-labeling-rule)、[UNIQLO 香港及澳门测量说明](https://faq-hk.uniqlo.com/pkb_Home_UQ_HK?c=category_uq_tw:UQHK_C2&fs=Search&id=kA0Ie000000TOgx&l=en_US&pn=1)。新加坡原链接本次读取失败，因此没有用其搜索摘要完成审核，改用实际打开并核对的香港及澳门页面。FTC 仅用于部件护理说明，不据该旧页面提供现行法律判断。只发布中文摘要与定位，不复制网页正文和测量图。

总量由 64 增至 66：21 条已审核来源摘要、21 条项目启发、24 条待审核。测量摘要都声明 UNIQLO 适用范围，不把品牌指南当成跨品牌统一标准；无法核验的棉缩水条目继续隔离。逐条前后内容及来源保存在 `artifacts/reports/knowledge/knowledge_review_20261029.json`。

## 当前离线结果与取舍

原 60 条历史检索题与其全部分母不变，使用相同 offline_hash；更新当前展示 manifest，同时保留旧报告。

| 指标 | 前一版 | 当前 |
| --- | ---: | ---: |
| 历史 gold ID 完整可用覆盖 | 15/60 | 17/60 |
| 完整覆盖中兼容有限范围规则的题数 | 12 | 13 |
| 混合 Recall@5 | 21.39% | 23.89% |
| 混合 MRR@5 | 19.72% | 21.81% |
| 混合 nDCG@5 | 19.57% | 21.67% |

当前报告：`artifacts/reports/agent/agent_evaluation_measurement_20261029.json`。4 条范围冲突题仍保留：3 条未知冲锋衣与 GORE-TEX 专属资料冲突，1 条羊毛题包含通用部件护理 gold，不能作为羊毛专项护理证据。没有通过删除低分题提高成绩。

这些变化反映审核知识覆盖与业务路由的改变；不证明在线 embedding、回答准确率或独立用户问题的改善。新增检索与聊天回归是开发用例，不是新的留出集。有限范围过滤也不等于语义蕴含验证。

## 验证和剩余工作

新增 8 项回归验证四个来源章节的实际 BM25 首位命中、三种测量对话不调用模型、知识工具权限与品牌范围；现有身高体重参考继续由原测试保护。来源结构、当前报告指纹、源码包包含当前报告也一并核验。

全量 345 项通过，Ruff 全量、知识结构、健康及编译检查通过，保留既有 DashScope 弃用提示。新增最终报告加入明确发布白名单，源码包可携带当前 manifest 指定的报告。

仍需补充材质与品牌的可信护理知识、真实用户问题和独立标注。没有执行付费模型、真实 embedding 评测，未重建完整便携运行环境。
