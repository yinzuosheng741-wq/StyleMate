# StyleMate 内置知识审查台账

日期：2026-10-22。原始 64 条完整保存在 data/knowledge/archive/records_before_review_20261022.jsonl。

2026-10-28 增量：另有 7 条完成指定章节对照，当前为 17 条 reviewed、21 条项目启发、26 条待审核。见[增量记录](KNOWLEDGE_EXPANSION_20261028.md)。以下数字和逐条表保留 2026-10-22 当时状态。

- 10 条经 Codex 对照官方指定章节后改写；不代表人工专家认证。
- 21 条转为项目启发，移除外部权威引用关联，不进入默认事实检索。
- 33 条保留为待审核。来源可访问不等于完整摘要得到支持；未核验不等于内容必然错误。
- 默认事实检索的覆盖目前收窄到面料、洗护、收纳与一条功能外套维护事实；其余主题的可信知识仍需补齐。
- 历史 60 条题目中，10 条的标注证据完整可用、2 条部分可用、48 条不可用。完整标注覆盖 16.67%；原始混合 Recall@5 为 18.06%。这不是检索算法退化的对照实验。
- 10 条完整覆盖题上的条件 Recall@5 为 100%，仅为 offline_hash 小样本结果，不能宣称真实语义召回达到 100%。

## 逐条处理

| ID | 标题 | 处理 | 原文定位 |
| --- | --- | --- | --- |
| fabric-wool-label | 羊毛先看洗标 | 原文对照后改写 | Can you dry clean Merino wool? |
| fabric-wool-heat | 羊毛避免高温 | 原文对照后改写 | Dry away from direct sunlight or heat |
| fabric-wool-shape | 羊毛保持版型 | 原文对照后改写 | Hang wovens, fold knits; How to dry a wool sweater |
| fabric-repair-first | 耐穿先查可修 | 待逐项核验，事实检索隔离 | 未完成 |
| care-label-complete | 洗护标签优先 | 待逐项核验，事实检索隔离 | 未完成 |
| care-symbol-sequence | 五类洗护符号 | 待逐项核验，事实检索隔离 | 未完成 |
| care-sort-before-wash | 清洗前分类 | 待逐项核验，事实检索隔离 | 未完成 |
| care-stain-before-dry | 污渍未除别烘 | 待逐项核验，事实检索隔离 | 未完成 |
| size-brand-chart | 尺码表优先原则 | 项目启发，解除外部背书 | 未完成 |
| size-product-measure | 成衣尺寸核对 | 项目启发，解除外部背书 | 未完成 |
| size-layering-ease | 叠穿预留余量 | 项目启发，解除外部背书 | 未完成 |
| size-fit-recheck | 换款重新核尺 | 项目启发，解除外部背书 | 未完成 |
| color-wheel-balance | 色轮辅助配色 | 项目启发，解除外部背书 | 未完成 |
| color-neutral-anchor | 中性色作锚点 | 项目启发，解除外部背书 | 未完成 |
| color-test-light | 不同光线复看 | 项目启发，解除外部背书 | 未完成 |
| color-small-accent | 小面积点缀色 | 项目启发，解除外部背书 | 未完成 |
| weather-layer-system | 分层应对温差 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-avoid-cotton-cold | 寒冷潮湿重干爽 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-wind-shell | 有风考虑外层 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-carry-layer | 通勤备可增减层 | 项目启发，解除外部背书 | 未完成 |
| scenario-outdoor-layer | 户外活动可调层 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-rain-plan | 雨天关注外层 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-repair-before-trip | 出行前检查破损 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-dress-care-label | 正式场合先防污 | 待逐项核验，事实检索隔离 | 未完成 |
| wardrobe-core-categories | 衣橱先补基础类别 | 项目启发，解除外部背书 | 未完成 |
| wardrobe-inventory-first | 搭配从现有衣橱起 | 项目启发，解除外部背书 | 未完成 |
| wardrobe-fit-before-keep | 留存前复核合身 | 项目启发，解除外部背书 | 未完成 |
| wardrobe-repair-value | 修理纳入衣橱决策 | 项目启发，解除外部背书 | 未完成 |
| style-analogous-colors | 邻近色风格启发 | 项目启发，解除外部背书 | 未完成 |
| style-contrast-colors | 对比色风格启发 | 项目启发，解除外部背书 | 未完成 |
| style-one-focus | 一套一个视觉重点 | 项目启发，解除外部背书 | 未完成 |
| style-compare-photo | 拍照复看整体 | 项目启发，解除外部背书 | 未完成 |
| storage-dry-before-fold | 完全干燥再收纳 | 待逐项核验，事实检索隔离 | 未完成 |
| storage-fold-promptly | 洗后及时整理 | 待逐项核验，事实检索隔离 | 未完成 |
| storage-wool-clean | 羊毛收纳前清洁 | 原文对照后改写 | Long-term storage |
| storage-repair-record | 收纳时记录待修 | 项目启发，解除外部背书 | 未完成 |
| weather-heat-light-clothing | 高温优先轻薄浅色 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-heat-adjust-activity | 高温活动减少暴露 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-cold-loose-layers | 寒冷采用宽松分层 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-cold-change-wet | 寒冷受潮及时换干衣 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-cold-protect-extremities | 严寒保护头手等末端 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-uv-cover-skin | 强紫外线增加覆盖 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-uv-index-plan | 户外计划参考 UV 指数 | 待逐项核验，事实检索隔离 | 未完成 |
| care-shell-close-zips | 功能外套洗前闭合拉链 | 原文对照后改写 | GORE-TEX Outerwear / Wash / Step 1 |
| care-shell-liquid-detergent | 功能外套慎选洗涤剂 | 原文对照后改写 | GORE-TEX Outerwear / Wash / Step 2 |
| fabric-shell-dwr-beading | 泼水表现先做水珠检查 | 原文对照后改写 | Re-apply the DWR / Step 1; Special Care |
| care-shell-reactivate-dwr | 按产品说明恢复拒水 | 原文对照后改写 | DRY / Step 2; Special Care |
| wardrobe-maintain-shell-first | 功能外套先维护再替换 | 原文对照后改写 | Re-apply the DWR; Special Care |
| weather-heat-hydration-clothing | 高温穿着配合补水 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-cold-dry-layer | 寒冷雨雪后更换干衣 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-uv-clothing-factor | 防晒衣物看覆盖度 | 待逐项核验，事实检索隔离 | 未完成 |
| weather-uv-hat-glasses | 强日照覆盖头脸 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-trip-ten-essentials | 户外行程带基础装备 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-trip-route-weather | 行程按路线和天气调整 | 待逐项核验，事实检索隔离 | 未完成 |
| scenario-trip-emergency-layer | 远行预留应急保暖层 | 待逐项核验，事实检索隔离 | 未完成 |
| care-wash-symbol-temperature | 洗护符号限制温度 | 待逐项核验，事实检索隔离 | 未完成 |
| care-wash-detergent-dose | 洗涤剂按说明用量 | 待逐项核验，事实检索隔离 | 未完成 |
| care-repair-before-replace | 小损坏先评估维修 | 待逐项核验，事实检索隔离 | 未完成 |
| fabric-cotton-shrink-risk | 棉制品留意缩水 | 待逐项核验，事实检索隔离 | 未完成 |
| fabric-wool-moisture | 羊毛受潮先干燥 | 原文对照后改写 | Dry away from direct sunlight or heat; How to dry a wool sweater |
| wardrobe-purchase-cost-per-wear | 购买前估算使用频率 | 项目启发，解除外部背书 | 未完成 |
| wardrobe-purchase-care-cost | 购买前看洗护成本 | 项目启发，解除外部背书 | 未完成 |
| size-measure-same-garment | 测量时保持口径一致 | 待逐项核验，事实检索隔离 | 未完成 |
| style-material-changes-formality | 正式度不只由颜色决定 | 项目启发，解除外部背书 | 未完成 |

## 来源访问与核验边界

| 来源 | 访问/核验状态 |
| --- | --- |
| [美国联邦贸易委员会 FTC](https://www.ftc.gov/business-guidance/resources/clothes-captioning-complying-care-labeling-rule) | page_accessible_record_support_pending |
| [GINETEX](https://www.ginetex.net/userfiles/files/gin_bro_gb_rz_brochure_web.pdf) | page_accessible_record_support_pending |
| [Woolmark](https://www.woolmark.com/care/care-for-wool/) | sections_compared |
| [American Cleaning Institute](https://www.cleaninginstitute.org/cleaning-tips/clothes/laundry-basics) | fetch_failed_403 |
| [American Cleaning Institute](https://www.cleaninginstitute.org/cleaning-tips/clothes/stain-removal-guide) | page_accessible_record_support_pending |
| [REI Expert Advice](https://www.rei.com/learn/expert-advice/layering-basics.html) | page_accessible_record_support_pending |
| [Patagonia](https://www.patagonia.com/repairs/) | page_accessible_record_support_pending |
| [Canva Color Wheel](https://www.canva.com/colors/color-wheel/) | scope_checked |
| [Nike Size & Fit](https://www.nike.com/help/a/size-charts) | minimal_extracted_content_record_support_pending |
| [UNIQLO Customer Service](https://faq-sg.uniqlo.com/articles/en_US/FAQ/Product-Measurement-Guidelines-SG) | page_accessible_record_support_pending |
| [NOAA National Weather Service](https://www.weather.gov/safety/heat-during) | page_accessible_record_support_pending |
| [NOAA National Weather Service](https://www.weather.gov/safety/cold-during) | page_accessible_record_support_pending |
| [美国环境保护署 EPA](https://www.epa.gov/sunsafety/sun-safety-tips) | page_accessible_record_support_pending |
| [GORE-TEX Brand](https://www.gore-tex.com/support/care/outerwear) | sections_compared |
| [美国国家公园管理局 NPS](https://www.nps.gov/articles/10essentials.htm) | page_accessible_record_support_pending |
| [美国皮肤病学会 AAD](https://www.aad.org/public/everyday-care/sun-protection/shade-clothing-sunscreen) | page_accessible_record_support_pending |

## 复现

```powershell
.venv/Scripts/python.exe scripts/build_knowledge.py --check --report artifacts/knowledge_structure_new.json
.venv/Scripts/python.exe -m evaluation.run_agent_eval --output artifacts/agent_evaluation_review_new.json
./scripts/test.ps1
```

build_knowledge 仅执行结构和已记录来源字段检查，不联网核验原文。生成报告使用新路径，避免覆盖既有报告。历史评测集尚未按修订后的陈述重新人工标注，新建任务草案也没有金标准标签。
