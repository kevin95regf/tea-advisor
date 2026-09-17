"""安全护栏测试。这是全项目最不能松的一层。

任何一个用例失败都意味着可能有不合规的推荐被返回给用户。
"""

from __future__ import annotations

import pytest

from app.domain import safety
from app.domain.enums import Constitution, Nature
from app.domain.safety import (
    HARD_DOSE_CEILING_G,
    MAX_HERBS_PER_BLEND,
    MissingConstitutionDataError,
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
    """每种体质都必须能筛出候选饮片。

    列表**从枚举派生**，不写死：这样以后加体质时这条测试会自动跟上。
    写死列表会留下隐形缺口 —— 看起来全绿，其实新体质一条都没测。
    """
    for constitution in Constitution:
        candidates = filter_by_constitution(constitution.value)
        assert candidates, f"{constitution.value} 没有候选饮片"


def test_filter_by_constitution_rejects_constitution_without_data() -> None:
    """herbs.json 里没有该体质数据时，必须显式报错，不能静默返回未筛选清单。

    这是「枚举加了新体质、数据没跟上」的防线：静默降级会让模型拿到一份
    未经筛选的候选集去配，可能开出方向完全相反的搭配（阴虚质拿到温补辛温之品），
    而这种错误从输出表面**看不出来**。宁可失败，也不要"看起来能用"。
    """
    with pytest.raises(MissingConstitutionDataError) as ei:
        filter_by_constitution("yin_deficiency")

    message = str(ei.value)
    assert "yin_deficiency" in message
    assert "suitable_constitutions" in message, "报错要指明去补哪个字段"


def test_filter_by_constitution_still_tolerates_missing_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整个 herbs.json 缺失时保持原行为（返回空列表）。

    load_herb_catalog 的契约是"文件不存在时返回空字典、不抛异常"，
    这条路径不能被新加的"该体质无数据"检查误伤成报错。
    """
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: {})
    assert filter_by_constitution("balanced") == []


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


def test_matcher_does_not_crash_when_constitution_default_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """体质默认搭配缺失时，规则兜底不能抛 KeyError。

    这条兜底路径的契约是"永远给出合法且安全的搭配"；抛异常会顺着 orchestrator
    冒出去变成 500，用户什么都拿不到 —— 而这时他本来至少能拿到一份安全的通用搭配。
    所以缺数据时退到平和质通用搭配，并在理由里说明"这不是为你体质配的"。

    为什么要 monkeypatch `_pick_rule`：实测 `_pick_rule` 对全部合法寒热取值都会
    命中规则（五条规则的 match_natures 并集覆盖了 Nature 的所有取值），
    所以 CONSTITUTION_DEFAULT 这条分支在正常流程里**走不到**。
    这里强制走它，把"将来它变成可达时"的行为先锁住。
    """
    from app.domain.models import ParsedFood, ParsedMeal
    from app.services import matcher

    monkeypatch.setattr(matcher, "_pick_rule", lambda parsed: None)
    # 删掉湿热质（保留 balanced —— 它是通用兜底目标，删了就会走"兜底也缺失"那条）
    monkeypatch.delitem(matcher.CONSTITUTION_DEFAULT, "damp_heat")

    meal = ParsedMeal(
        foods=[ParsedFood(name="米饭", amount_desc="一碗")],
        overall_nature=Nature.NEUTRAL,
    )
    recs, _, hits = matcher.fallback_recommend(meal, Constitution.DAMP_HEAT)

    assert recs, "缺数据时也应给出通用搭配，而不是什么都不给"
    assert recs[0].herbs
    assert "尚未收录" in recs[0].fit_reason, "必须说明这不是为他体质配的"
    assert hits[0] == "constitution_default_missing"
    # 确认真的退到了平和质的搭配，而不是随手编一组
    balanced_blend = {name for name, _ in matcher.CONSTITUTION_DEFAULT["balanced"][0]}
    assert {h.name for h in recs[0].herbs} == balanced_blend
