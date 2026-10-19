# 用户画像层（personas）— 来自样本表，不是 RAG

## 背景

用户提供一份约 **3 万行** 的画像样本 CSV（字段：`user_id`, `persona_primary`, `persona_secondary`, `brief_note`）。茶顾问知识库是**结构化 JSON 查表**（饮片 / 食材 / 体质 / 饮食信号 / 食疗模板），正式版方案里提到「从用户画像读」，但此前画像层未落地。

本次按现有框架新增 `core/data/personas.json` + `core/app/services/personas.py`，**不引入向量检索或 embedding**。

## 11 类主画像

| display_name | sample_primary_count | safety_gate |
|---|---:|---|
| 熬夜大学生 | 3000 | none |
| 爱喝酒中年人 | 3000 | none |
| 规律上班族 | 3000 | none |
| 外卖党 | 3000 | none |
| 健身人群 | 3000 | none |
| 素食者 | 3000 | none |
| 孕期女性 | 3000 | **high_risk** |
| 减肥年轻人 | 3000 | none |
| 退休老人 | 3000 | none |
| 慢性病糖尿病 | 1500 | **high_risk** |
| 慢性病高血压 | 1500 | **high_risk** |

`brief_note` 与样本表一致；`secondary_compatible` 来自样本中该 primary 与 secondary 的共现中文名（非医学组合权威）。

## 高风险三条如何挂闸

1. 画像自身：`safety_gate=high_risk`，并带 `high_risk_keywords`（孕期/孕妇、糖尿病、高血压）。
2. 全局关键词：`safety.HIGH_RISK_KEYWORDS` 已含糖尿病/高血压，并补入 **「孕期」**，使 `detect_high_risk("孕期…")` 仍命中。
3. 纯函数钩子：`persona_is_high_risk` / `persona_id_is_high_risk` / `text_hits_high_risk_persona` / `high_risk_block_reasons`。
4. **已接入主流程（2026-10-16）**：`AnalyzeRequest.persona_id`（可选）；`orchestrator.analyze` 与 `/api/analyze-offline` 在凭据校验前合并关键词 + 高风险画像 id + 文本命中画像，命中则与原高风险分支相同（空 recommendations、就医引导）。未知 `persona_id` → `UNKNOWN_PERSONA`（422）。低风险画像只把 `persona:` / `persona_review:` 挂到 `basis.rule_hits`，**不**改推荐内容。

高风险画像**不写**「推荐某茶/某汤」类字段，只保留闸门与 `care_direction` 就医提醒方向。

## 对照纪律

- `constitution_hints` / `diet_signal_tendencies` 均为样本语境软推断，`review_status=pending`。
- `sources` 只登记 `distribution_sample`，不伪造药典或文献 URL。
- SPEC：不开方、不写君臣佐使、不输出处方剂量。

## 相关文件

- `core/data/personas.json`
- `core/app/services/personas.py`
- `core/tests/test_personas.py`
- `core/app/agents/tool_registry_stub.py`（只读 `list_personas` / `get_persona`）
