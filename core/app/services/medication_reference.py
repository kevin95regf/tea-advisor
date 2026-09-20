"""体质药物调理参考资料（只读）。

数据来源：《成年人中医体质治未病干预指南》T/CACM 1460—2023
（中华中医药学会，2023-03-23 发布并实施）。

**本模块刻意游离于推荐链路之外。**

为什么必须隔离
--------------
本项目其余部分的安全设计建立在一个结构性前提上：**让模型无方可开**。
Agent2 只能从 ``herbs.json`` 的逐味药食同源饮片里挑，候选集再由
``safety.filter_by_constitution()`` 按体质收敛，因此模型即使想自由发挥也无药可用。

而本模块收录的是**处方**——补中益气汤、六味地黄丸、血府逐瘀汤、逍遥散等，
以及附子、黄芪、黄连、桃仁等非药食同源药材。这些内容一旦进入提示词或候选集，
上述结构性约束立刻失效，模型就会「有方可开」。

所以本模块的契约是：

* 只被本文件与只读展示层使用；
  ``app/domain/safety.py``、``app/services/food_lookup.py``、``app/services/matcher.py``、
  ``app/services/orchestrator.py``、``app/agents/prompts/*.md`` **一律不得** import 或读取它。
  （``tests/test_medication_reference.py`` 里有一条守卫测试把这件事钉死。）
* 只做来源登记与结构化摘要查询：**不收录标准正文、不计算剂量、不做体质匹配推荐、不生成搭配**。
* ``constitution_medication.json`` **不是** ``herbs.json`` 的来源，
  两者也不可互相同步。体质食养候选的唯一真源仍是
  ``constitution_recommendations.json``。

免责声明随数据一起返回，调用方必须原样展示，不得裁剪。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.enums import Constitution

DATA_FILENAME = "constitution_medication.json"

#: 数据文件缺失时返回空结果，不抛异常（与 load_herb_catalog 的降级策略一致）。
_REQUIRED_PROFILE_KEYS = (
    "id",
    "label",
    "clause",
    "principle",
    "common_drugs",
    "recommended_formulas",
    "adjustment_points",
    "referral_note",
)
_REQUIRED_CONCURRENT_KEYS = (
    "id",
    "label",
    "clause",
    "principle",
    "notes",
    "common_drugs",
)


class MedicationReferenceError(ValueError):
    """``constitution_medication.json`` 存在但结构不合法。

    这里**必须显式失败**，不能静默降级成空结果：一份被改坏的数据表
    如果只表现为「查不到」，问题会一直潜伏到对外展示时才暴露；
    而这个模块展示的是处方相关内容，错漏的代价比报错高得多。
    """


def _data_path() -> Path:
    return get_settings().data_dir / DATA_FILENAME


@lru_cache(maxsize=1)
def load_medication_reference() -> dict[str, Any]:
    """加载药物调理资料。文件不存在时返回空字典。"""
    path = _data_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate(raw)
    return raw


def reload_medication_reference() -> dict[str, Any]:
    """清缓存后重新加载（改了数据文件之后调用）。"""
    load_medication_reference.cache_clear()
    return load_medication_reference()


def _validate(raw: dict[str, Any]) -> None:
    meta = raw.get("_meta") or {}
    if not meta.get("disclaimer"):
        raise MedicationReferenceError("_meta.disclaimer 缺失或为空：展示层必须有免责声明可原样呈现")

    sources = {item.get("id") for item in meta.get("sources", [])}
    if not sources:
        raise MedicationReferenceError("_meta.sources 为空：药物调理资料必须可溯源")

    profiles = raw.get("constitutions") or []
    expected_ids = {item.value for item in Constitution}
    actual_ids = {item.get("id") for item in profiles}
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise MedicationReferenceError(
            f"constitutions 与 Constitution 枚举不一致：缺少 {missing}，多出 {extra}"
        )

    for profile in profiles:
        absent = [key for key in _REQUIRED_PROFILE_KEYS if key not in profile]
        if absent:
            raise MedicationReferenceError(
                f"体质「{profile.get('id')}」缺少字段：{absent}"
            )
        for formula in profile["recommended_formulas"]:
            if not formula.get("name"):
                raise MedicationReferenceError(
                    f"体质「{profile['id']}」有未命名的方剂条目"
                )

    concurrent = raw.get("concurrent_constitutions") or []
    seen: set[str] = set()
    for item in concurrent:
        absent = [key for key in _REQUIRED_CONCURRENT_KEYS if key not in item]
        if absent:
            raise MedicationReferenceError(
                f"兼夹体质「{item.get('id')}」缺少字段：{absent}"
            )
        if item["id"] in seen:
            raise MedicationReferenceError(f"兼夹体质 id 重复：{item['id']}")
        seen.add(item["id"])


# ============================================================
# 只读查询
# ============================================================
def medication_meta() -> dict[str, Any]:
    """返回元数据（来源、分级说明、使用边界）。"""
    return dict(load_medication_reference().get("_meta") or {})


def medication_disclaimer() -> list[str]:
    """返回必须原样展示的免责声明。"""
    return list(medication_meta().get("disclaimer") or [])


def medication_sources() -> list[dict[str, Any]]:
    """返回资料来源清单。"""
    return list(medication_meta().get("sources") or [])


def list_profiles() -> list[dict[str, Any]]:
    """按来源章节顺序返回 9 种体质的结构化摘要。"""
    return list(load_medication_reference().get("constitutions") or [])


def get_profile(constitution: str) -> dict[str, Any] | None:
    """按体质 id 取药物调理条目，未收录时返回 ``None``。"""
    for profile in list_profiles():
        if profile.get("id") == constitution:
            return profile
    return None


def concurrent_principles() -> dict[str, Any]:
    """返回 4.2.1 兼夹体质调理总则。"""
    return dict(load_medication_reference().get("concurrent_principles") or {})


def list_concurrent_constitutions() -> list[dict[str, Any]]:
    """返回 4.2 收录的兼夹体质调理原则。"""
    return list(load_medication_reference().get("concurrent_constitutions") or [])


def get_concurrent_constitution(concurrent_id: str) -> dict[str, Any] | None:
    """按 id 取某一组兼夹体质的调理原则。"""
    for item in list_concurrent_constitutions():
        if item.get("id") == concurrent_id:
            return item
    return None


def describe_profile(constitution: str) -> str:
    """把一条药物调理条目渲染为可读文本（仅供展示，不做任何判断）。

    刻意不含剂量字段：本系统的药物调理资料不提供用量，
    以免被误当作可执行的用药方案。
    """
    profile = get_profile(constitution)
    if profile is None:
        return f"未收录体质「{constitution}」的药物调理资料。"

    lines = [f"{profile['label']} · 调体原则：{profile['principle']}"]
    if profile["common_drugs"]:
        lines.append("常用药物：" + "、".join(profile["common_drugs"]))
    if profile.get("additional_drugs"):
        lines.append("加减药物：" + "、".join(profile["additional_drugs"]))
    if profile.get("drug_notes"):
        lines.append("资料说明：" + profile["drug_notes"])

    for formula in profile["recommended_formulas"]:
        grade = "、".join(
            str(part)
            for part in (formula.get("recommendation_class"), formula.get("evidence_level"))
            if part
        )
        lines.append(f"方剂索引：{formula['name']}" + (f"（{grade}）" if grade else "（资料未登记等级）"))
    if not profile["recommended_formulas"]:
        lines.append("方剂索引：无")

    if profile["adjustment_points"]:
        lines.append("调体要点：" + "；".join(profile["adjustment_points"]))
    if profile.get("referral_note"):
        lines.append("提示：" + profile["referral_note"])
    return "\n".join(lines)
