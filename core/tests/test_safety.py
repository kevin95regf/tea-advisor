"""安全护栏测试。这是全项目最不能松的一层。

任何一个用例失败都意味着可能有不合规的推荐被返回给用户。
"""

from __future__ import annotations

import pytest

from app.domain.safety import (
    HARD_DOSE_CEILING_G,
    MAX_HERBS_PER_BLEND,
    check_blend,
    check_constitution_fit,
    contains_forbidden_phrase,
    detect_high_risk,
    filter_by_constitution,
    herb_whitelist_names,
    load_herb_catalog,
    scan_free_text,
)


# ============================================================
# 白名单
# ============================================================
def test_catalog_loads() -> None:
    catalog = load_herb_catalog()
    assert len(catalog) >= 15, "饮片库太小，demo 也需要至少 15 味"


def test_every_herb_has_required_fields() -> None:
    for herb_id, item in load_herb_catalog().items():
        assert item.get("name"), f"{herb_id} 缺 name"
        assert item.get("nature"), f"{herb_id} 缺 nature"
        assert item.get("max_daily_g"), f"{herb_id} 缺 max_daily_g"
        assert isinstance(item.get("cautions"), list), f"{herb_id} 缺 cautions"


def test_no_duplicate_names() -> None:
    names = [item["name"] for item in load_herb_catalog().values()]
    assert len(names) == len(set(names)), "饮片名重复"


def test_non_whitelisted_herb_is_blocked() -> None:
    # 附子等不在药食同源目录内的药材必须被拦
    result = check_blend([{"name": "附子", "amount_g": 3}])
    assert result.ok is False
    assert any("附子" in item for item in result.blocked)


def test_all_whitelisted_herbs_pass() -> None:
    herbs = [{"name": name, "amount_g": 3} for name in list(herb_whitelist_names())[:3]]
    result = check_blend(herbs)
    assert result.ok is True


# ============================================================
# 剂量
# ============================================================
def test_overdose_is_trimmed_with_warning() -> None:
    result = check_blend([{"name": "甘草", "amount_g": 100}])
    assert any("甘草" in w for w in result.warnings)
    assert "甘草" in result.adjusted


def test_hard_ceiling_is_respected() -> None:
    """即使目录限量写错，硬上限也必须兜住。"""
    result = check_blend([{"name": "茯苓", "amount_g": HARD_DOSE_CEILING_G + 50}])
    assert any("茯苓" in w for w in result.warnings)


def test_total_dose_ceiling() -> None:
    """总量上限要在逐味裁剪之后仍然生效。

    这组用例每一味都不超各自上限，但合计偏多——正是"看起来都合规、
    加起来像方剂"的典型情况。
    """
    herbs = [
        {"name": "茯苓", "amount_g": 15},
        {"name": "薏苡仁", "amount_g": 20},
        {"name": "陈皮", "amount_g": 10},
        {"name": "荷叶", "amount_g": 10},
    ]
    result = check_blend(herbs)
    assert any("合计用量" in w for w in result.warnings), result.warnings
    assert "总量" in result.adjusted


def test_per_herb_trimming_can_keep_total_legal() -> None:
    """逐味裁剪后合计刚好达标时，不应再报总量问题（避免误报）。"""
    herbs = [
        {"name": "茯苓", "amount_g": 20},   # 超限，裁到 15
        {"name": "薏苡仁", "amount_g": 20},  # 上限 20，不裁
        {"name": "陈皮", "amount_g": 10},    # 上限 10，不裁
    ]
    result = check_blend(herbs)
    assert not any("合计用量" in w for w in result.warnings), result.warnings


def test_too_many_herbs_is_blocked() -> None:
    names = list(herb_whitelist_names())[: MAX_HERBS_PER_BLEND + 1]
    result = check_blend([{"name": n, "amount_g": 3} for n in names])
    assert result.ok is False
    assert any("味" in item for item in result.blocked)


# ============================================================
# 用户排除
# ============================================================
def test_user_exclusion_is_blocked() -> None:
    result = check_blend([{"name": "陈皮", "amount_g": 5}], exclude_herbs=["陈皮"])
    assert result.ok is False
    assert any("用户已排除" in item for item in result.blocked)


# ============================================================
# 禁用表述
# ============================================================
@pytest.mark.parametrize(
    "text",
    [
        "这个可以治疗失眠",
        "能根治你的问题",
        "按疗程喝一个月",
        "这是处方",
        "可以停药了",
        "有很好的疗效",
    ],
)
def test_forbidden_phrases_detected(text: str) -> None:
    assert contains_forbidden_phrase(text), f"未检出禁用表述：{text}"
    assert scan_free_text(text).ok is False


@pytest.mark.parametrize(
    "text",
    [
        "这杯茶偏于健脾消食，餐后温饮较合适",
        "有助于缓解油腻后的饱胀感",
        "适合痰湿体质日常饮用",
    ],
)
def test_compliant_wording_passes(text: str) -> None:
    assert scan_free_text(text).ok is True, f"合规措辞被误判：{text}"


# ============================================================
# 高风险人群
# ============================================================
@pytest.mark.parametrize(
    "text",
    [
        "我怀孕了能喝吗",
        "正在哺乳期",
        "今天来月经了",
        "给孩子喝的",
        "我有高血压在吃药",
        "刚做完手术",
    ],
)
def test_high_risk_detected(text: str) -> None:
    assert detect_high_risk(text), f"未识别高风险人群：{text}"


def test_normal_text_not_flagged_high_risk() -> None:
    assert detect_high_risk("中午吃了碗牛肉面") == []


# ============================================================
# 体质筛选
# ============================================================
def test_filter_by_constitution_returns_candidates() -> None:
    for constitution in ("balanced", "qi_deficiency", "yang_deficiency", "phlegm_damp", "damp_heat"):
        candidates = filter_by_constitution(constitution)
        assert candidates, f"{constitution} 没有候选饮片"


def test_yang_deficiency_excludes_cold_herbs() -> None:
    """阳虚质不应拿到标注为不适宜的寒凉饮片。"""
    candidates = {item["name"] for item in filter_by_constitution("yang_deficiency")}
    assert "菊花" not in candidates
    assert "决明子" not in candidates


def test_damp_heat_excludes_warm_tonics() -> None:
    candidates = {item["name"] for item in filter_by_constitution("damp_heat")}
    assert "龙眼肉" not in candidates
    assert "红枣" not in candidates


def test_constitution_fit_warns_on_conflict() -> None:
    result = check_constitution_fit([{"name": "龙眼肉", "amount_g": 5}], "damp_heat")
    assert result.warnings, "体质冲突未给出警告"
