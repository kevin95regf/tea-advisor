# Agent 思考路径：食疗汤模板（最小落地）

> 2026-10-13（Asia/Shanghai）  
> 对照：`/workspace/tea-advisor-agent-proposal.md`；数据：`core/data/soup_templates.json`  
> **未**实现完整 tool-calling 主循环；仅数据 + 只读工具函数 + 注册点桩 + 提示词硬边界。

## 与茶饮推荐的分工

| 通道 | 做什么 | 不做什么 |
|---|---|---|
| Agent2 / `/api/analyze` | 白名单饮片日常茶饮 1–3 条 | 不开方剂名；不自动塞 pending 食疗汤 |
| 食疗模板查询 | `list_soup_templates` / `get_soup_template`；可选 `GET /api/soup-templates` | 不自由加减；不抄汤剂剂量 |

安全是**结构护栏**（校验 id、kind、herb/food 二选一、pending 元数据），不是靠模型自觉。隔离方式对齐 medication-reference：只读、不进 recommend。

## 何时可考虑「查食疗模板」

在将来的 tool-calling 循环里，**仅当**：

1. 用户明确问家常汤 / 药膳 / 某汤名；或  
2. 口述明显匹配某条模板的 `display_name`（如「四神汤」「清补凉」）；  

才调用 `list_soup_templates` 或 `get_soup_template`。

日常「吃了火锅推荐茶饮」→ **不**走模板工具，仍走原茶饮候选。

## pending 与自动推荐

- 当前全部 `review_status=pending`。  
- **默认不**把模板自动写入 Agent2 `recommendations`。  
- 查询路径可以返回全文，但必须带 `_query_meta.disclaimer`（pending 免责）。  
- `approved` 之后若要窄口引用，仍只能用 `display_name` + `kitchen_amount_hint`，禁止加减组成。

## 工具接口（已实现函数 / 未实现循环）

| 工具名 | 实现 | 注册点 |
|---|---|---|
| `list_soup_templates` | `app.services.soup_templates.list_soup_templates` | `app.agents.tool_registry_stub` |
| `get_soup_template` | `app.services.soup_templates.get_soup_template` | 同上 |

桩文件注明：**非可选安全闸在循环外**（白名单、pending、剂量封顶、高风险空推荐）。完整循环见 agent proposal，本仓库此步不停。

## Agent2 提示词

`agent2_system.md` 硬性边界第 9 条：禁未经批准方剂名；若提及食疗组合仅可引用模板 `display_name`；pending 不进本通道 recommendations。

## HTTP（可选薄封装）

- `GET /api/soup-templates`  
- `GET /api/soup-templates/{template_id}`  

与 medication-reference 同 tag `reference`，**不**挂到 analyze。
