# 食疗汤模板落地说明（数据层）

> 日期：2026-10-13（Asia/Shanghai）　状态：**数据已落地，UI/API 接线另开**  
> 文件：`core/data/soup_templates.json`　加载：`core/app/services/soup_templates.py`

## 已入库模板

| id | 显示名 | 组成（herb_id） | kind |
|---|---|---|---|
| `sishen_tang` | 四神汤 | fuling, yiyiren, qianshi, shanyao | food_therapy |
| `jiangzao_cha` | 姜枣茶 | shengjiang, hongzao | food_therapy |

全部 `review_status=pending`。用量仅为 `kitchen_amount_hint` 家庭约量文案，沿用单味 `max_daily_g` 作封顶参考，**不是**处方剂量。

## 刻意未做

- **未**修改 `agent2_system.md`（继续禁止自由方剂名 / 君臣佐使）。
- **未**把模板接进 `fallback_recommend` / Agent2 候选拼方。
- **未**新增对外 HTTP API（若日后接线，建议只读列表，与 medication-reference 同隔离哲学）。

## 组成口径备注

广东省中医药局科普中「四神」常写茯苓+淮山+莲子+芡实（或薏仁）。本项目边界文档已定模板组成为**茯苓+薏苡仁+芡实+山药**；与含莲子的通行版并存时，产品文案应标明「本站白名单版」。

## 验收

- `core/tests/test_soup_templates.py`：文件存在、kind 约束、组件 id ∈ herbs.json、加载器可读。
