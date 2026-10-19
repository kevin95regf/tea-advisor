"""只读加载用户主画像（personas.json）。

结构化查表，不是向量 RAG。与 soup_templates 同哲学：
数据落地供策展/只读查询与安全闸门对照；**默认不**把画像当开方依据。
高风险画像（孕期、糖尿病、高血压）命中时不得自动茶饮推荐。
可供将来 tool-calling 注册的纯函数见 ``list_personas`` / ``get_persona``
（亦见 ``app.agents.tool_registry_stub``）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import get_settings

DATA_FILENAME = "personas.json"
ALLOWED_SAFETY_GATE = frozenset({"none", "high_risk"})
ALLOWED_REVIEW = frozenset({"pending", "approved", "rejected"})
ALLOWED_CONSTITUTION_TENDENCY = frozenset({"likely", "possible", "avoid_claim"})
ALLOWED_SIGNAL_TENDENCY = frozenset({"elevated", "reduced", "neutral"})
EXPECTED_COUNT = 11


class PersonasError(RuntimeError):
    """``personas.json`` 缺失或结构不合法。"""


class PersonaNotFound(LookupError):
    """未知的画像 id。"""


def _constitution_ids() -> set[str]:
    path = get_settings().data_dir / "constitution.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("constitutions") or raw.get("items") or []
    return {c["id"] for c in items if isinstance(c, dict) and c.get("id")}


def _diet_signal_ids() -> set[str]:
    path = get_settings().data_dir / "diet_signals.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("signals") or raw.get("items") or []
    return {s["id"] for s in items if isinstance(s, dict) and s.get("id")}


def validate_personas_payload(data: dict[str, Any]) -> None:
    """校验整份 payload；失败抛 ``PersonasError``。"""
    if not isinstance(data, dict) or "personas" not in data:
        raise PersonasError(f"{DATA_FILENAME} 缺少 personas 数组")
    if not isinstance(data["personas"], list):
        raise PersonasError("personas 必须是数组")
    personas = data["personas"]
    if len(personas) != EXPECTED_COUNT:
        raise PersonasError(
            f"personas 须恰好 {EXPECTED_COUNT} 条，实际 {len(personas)}"
        )

    constitution_ids = _constitution_ids()
    signal_ids = _diet_signal_ids()
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    for p in personas:
        if not isinstance(p, dict):
            raise PersonasError("persona 必须是对象")
        pid = p.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise PersonasError("persona 缺少 id")
        if pid in seen_ids:
            raise PersonasError(f"重复 persona id: {pid}")
        seen_ids.add(pid)

        name = p.get("display_name")
        if not isinstance(name, str) or not name.strip():
            raise PersonasError(f"{pid}: 缺少 display_name")
        if name in seen_names:
            raise PersonasError(f"重复 display_name: {name}")
        seen_names.add(name)

        if p.get("safety_gate") not in ALLOWED_SAFETY_GATE:
            raise PersonasError(f"{pid}: safety_gate 非法")
        if p.get("review_status") not in ALLOWED_REVIEW:
            raise PersonasError(f"{pid}: review_status 非法")

        kws = p.get("high_risk_keywords")
        if kws is None:
            kws = []
        if not isinstance(kws, list):
            raise PersonasError(f"{pid}: high_risk_keywords 必须是数组")
        if p.get("safety_gate") == "high_risk":
            cleaned = [k for k in kws if isinstance(k, str) and k.strip()]
            if not cleaned:
                raise PersonasError(f"{pid}: high_risk 必须有 high_risk_keywords")

        hints = p.get("constitution_hints") or []
        if not isinstance(hints, list):
            raise PersonasError(f"{pid}: constitution_hints 必须是数组")
        for h in hints:
            if not isinstance(h, dict):
                raise PersonasError(f"{pid}: constitution_hints 项必须是对象")
            cid = h.get("constitution_id")
            if cid not in constitution_ids:
                raise PersonasError(
                    f"{pid}: constitution_id={cid!r} 不在 constitution.json"
                )
            if h.get("tendency") not in ALLOWED_CONSTITUTION_TENDENCY:
                raise PersonasError(f"{pid}: constitution tendency 非法")

        signals = p.get("diet_signal_tendencies") or []
        if not isinstance(signals, list):
            raise PersonasError(f"{pid}: diet_signal_tendencies 必须是数组")
        for s in signals:
            if not isinstance(s, dict):
                raise PersonasError(f"{pid}: diet_signal_tendencies 项必须是对象")
            sid = s.get("signal_id")
            if sid not in signal_ids:
                raise PersonasError(
                    f"{pid}: signal_id={sid!r} 不在 diet_signals.json"
                )
            if s.get("tendency") not in ALLOWED_SIGNAL_TENDENCY:
                raise PersonasError(f"{pid}: diet signal tendency 非法")

        sec = p.get("secondary_compatible")
        if sec is None:
            sec = []
        if not isinstance(sec, list):
            raise PersonasError(f"{pid}: secondary_compatible 必须是数组")


@lru_cache(maxsize=1)
def load_personas() -> dict:
    path = get_settings().data_dir / DATA_FILENAME
    if not path.is_file():
        raise PersonasError(f"缺少 {DATA_FILENAME}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PersonasError(f"{DATA_FILENAME} 不是合法 JSON：{exc}") from exc
    validate_personas_payload(data)
    return data


def list_personas(*, include_pending: bool = True) -> list[dict]:
    """只读工具：列出主画像（结构化 dict 浅拷贝）。

    ``include_pending=False`` 时只返回 ``review_status==approved``。
    当前库内均为 pending → 默认仍可查，但调用方须展示免责声明，
    **不得**把 pending 画像当作开方或自动推荐依据。
    """
    data = load_personas()
    out: list[dict] = []
    for p in data["personas"]:
        if not isinstance(p, dict):
            continue
        status = p.get("review_status")
        if not include_pending and status != "approved":
            continue
        out.append(dict(p))
    return out


def get_persona(persona_id: str) -> dict:
    """只读工具：按 id 取一条画像；未知 id 明确失败。"""
    if not isinstance(persona_id, str) or not persona_id.strip():
        raise PersonaNotFound("画像 id 不能为空")
    pid = persona_id.strip()
    for p in list_personas(include_pending=True):
        if p.get("id") == pid:
            payload = dict(p)
            status = payload.get("review_status")
            gate = payload.get("safety_gate")
            payload["_query_meta"] = {
                "auto_recommend_allowed": status == "approved" and gate != "high_risk",
                "disclaimer": (
                    "本条为用户画像样本分布查询结果，不是体质辨证或医疗建议。"
                    + (
                        "当前为高风险画像：不得自动写入茶饮/汤饮推荐，应引导就医咨询。"
                        if gate == "high_risk"
                        else (
                            "当前 review_status=pending，仅供对照查阅，不得当开方依据。"
                            if status == "pending"
                            else "引用时仅可使用 display_name / brief_note，不得编造处方。"
                        )
                    )
                ),
            }
            return payload
    raise PersonaNotFound(f"未知或不允许的画像 id: {pid}")


def persona_is_high_risk(persona_id: str) -> bool:
    """给定 persona_id，是否为 high_risk 闸门画像。未知 id → False。"""
    if not isinstance(persona_id, str) or not persona_id.strip():
        return False
    try:
        p = get_persona(persona_id.strip())
    except PersonaNotFound:
        return False
    return p.get("safety_gate") == "high_risk"


def match_persona_keywords(text: str) -> list[str]:
    """用 display_name 与 high_risk_keywords 子串匹配文本，返回命中的 persona id 列表。

    顺序与 personas.json 一致；同一画像只出现一次。
    """
    if not isinstance(text, str) or not text:
        return []
    hits: list[str] = []
    for p in list_personas(include_pending=True):
        pid = p.get("id")
        if not isinstance(pid, str):
            continue
        name = p.get("display_name") or ""
        kws = list(p.get("high_risk_keywords") or [])
        needles = [name] + [k for k in kws if isinstance(k, str) and k.strip()]
        if any(n and n in text for n in needles):
            hits.append(pid)
    return hits


def personas_disclaimer() -> str:
    return (
        "以下为用户画像样本分布条目，仅供产品对照与安全闸门，"
        "不构成体质辨证、医疗建议或处方依据；"
        "safety_gate=high_risk 的画像不得进入自动茶饮推荐。"
        "review_status=pending 的条目默认仅供查阅。"
    )


def clear_personas_cache() -> None:
    load_personas.cache_clear()
