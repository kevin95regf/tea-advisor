"""安全护栏测试。这是全项目最不能松的一层。

任何一个用例失败都意味着可能有不合规的推荐被返回给用户。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain import safety
from app.domain.enums import Constitution, Nature
from app.domain.safety import (
    HARD_DOSE_CEILING_G,
    MAX_HERBS_PER_BLEND,
    MissingConstitutionDataError,
    check_blend,
    check_brew_adequacy,
    check_constitution_fit,
    contains_forbidden_phrase,
    cook_required_without_basis,
    detect_high_risk,
    filter_by_constitution,
    herb_requires_cooking,
    herb_whitelist_names,
    load_herb_catalog,
    ready_constitutions,
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
    """每种**已就绪**的体质都必须能筛出候选饮片。

    列表**从枚举派生**，不写死：这样以后加体质时这条测试会自动跟上。
    写死列表会留下隐形缺口 —— 看起来全绿，其实新体质一条都没测。

    ⚠️ 2026-09-17（5→9）：枚举加成员 ≠ 数据已备齐。四型刚进枚举时 herbs.json
    里一条标注都没有，`filter_by_constitution` 会如实抛 `MissingConstitutionDataError`。
    所以这里的守卫改成**就绪 ⟺ 有候选**这条双向不变式：
    就绪的必须有候选（本条），未就绪的必须抛错（下一条 `..._without_data`）。
    这样「扩了枚举忘了补数据」仍然会被抓到——只是抓它的是下一条。
    """
    for constitution in Constitution:
        if constitution.value not in ready_constitutions():
            continue
        candidates = filter_by_constitution(constitution.value)
        assert candidates, f"{constitution.value} 已就绪却没有候选饮片"


def test_legacy_five_constitutions_are_ready() -> None:
    """现有 5 型的数据是齐的，闸门写反也不能把它们关掉。

    单独一条是因为上面那条改成「跳过未就绪」之后就有了盲区：
    万一 `ready_constitutions()` 哪天返回空集，上面那条会一条都不测却依然全绿。
    """
    legacy = {
        "balanced", "qi_deficiency", "yang_deficiency", "phlegm_damp", "damp_heat",
    }
    missing = legacy - ready_constitutions()
    assert not missing, f"这几种原有体质不应变成未就绪：{sorted(missing)}"


def test_filter_by_constitution_rejects_constitution_without_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """herbs.json 里没有该体质数据时，必须显式报错，不能静默返回未筛选清单。

    这是「枚举加了新体质、数据没跟上」的防线：静默降级会让模型拿到一份
    未经筛选的候选集去配，可能开出方向完全相反的搭配（阴虚质拿到温补辛温之品），
    而这种错误从输出表面**看不出来**。宁可失败，也不要"看起来能用"。

    ⚠️ 2026-09-17：`yin_deficiency` 补上数据后已就绪，所以未就绪样本改为**现场造**
    —— 把某体质的 suitable 标注全部抹掉。原先直接拿 `yin_deficiency` 当样本的写法
    会随数据补齐**静默失效**（测试仍绿，但已经测不到这条防线了）。
    """
    catalog = {k: {**v} for k, v in safety.load_herb_catalog().items()}
    for entry in catalog.values():
        entry["suitable_constitutions"] = [
            c for c in (entry.get("suitable_constitutions") or []) if c != "yin_deficiency"
        ]
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: catalog)

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


# ============================================================
# cautions → unsuitable_for 的一致性（阴虚方向）
# ============================================================
# 阴虚方向的关键词。刻意只取这 5 个明确指向阴虚的词，不含宽泛的「燥」——
# 宽词会把「性质平和、不燥」这类正面描述也命中。
YINXU_CAUTION_KEYWORDS = ("阴虚", "津液", "口干", "上火", "内热")

# 2026-09-17 落地的批次（docs/herbs-cautions-yinxu-batch.md）
CAUTIONS_BATCH_YINXU = frozenset(
    {
        "fuling", "chenpi", "longyanrou", "shengjiang", "yiyiren",
        "molihua", "juhong", "huoxiang", "zisu", "foshou",
    }
)

# ---- 软约束豁免登记（cautions-only）----
# 登记表的**唯一事实源**是 herbs.json 的 _meta.constitution_extension.rulings.cells。
# 刻意不在测试里另存一份名单：两处名单必然漂移，而漂移的方向总是「测试放过、数据漏了」。
ROLLING_SOFT_FIELDS = ("cautions", "suitable_constitutions")

CORE_DIR = Path(__file__).resolve().parent.parent
HERBS_JSON = CORE_DIR / "data" / "herbs.json"


def load_rulings() -> dict:
    """读 `_meta.constitution_extension.rulings`（没有则返回空 dict）。"""
    data = json.loads(HERBS_JSON.read_text(encoding="utf-8"))
    ext = ((data.get("_meta") or {}).get("constitution_extension") or {})
    return ext.get("rulings") or {}


def load_rulings_cells() -> list[dict]:
    """展开 rulings.cells（供豁免判定与批次块格式检查共用）。"""
    return list(load_rulings().get("cells") or [])


def _cautions_soft_gap(catalog: dict, cells: list[dict]) -> dict:
    """算出『cautions 命中阴虚方向关键词』与『软通道登记』之间的三类缺口。

    纯函数：不读文件、不依赖真实数据 —— 正向测试与负控制共用同一份逻辑
    （否则负控制只是把判定又写了一遍，属假保证）。每个 key 为空列表即代表该类问题不存在。
    """
    hit = {
        herb_id
        for herb_id, item in catalog.items()
        if any(k in c for c in (item.get("cautions") or []) for k in YINXU_CAUTION_KEYWORDS)
    }
    yin = [c for c in cells if c.get("constitution") == "yin_deficiency"]
    exempt = {c.get("herb") for c in yin}
    soft = [c for c in yin if c.get("field") != "unsuitable_for"]
    return {
        "hit": hit,
        # 规则①：豁免项必须 ∈ 命中集（登记表不能当垃圾桶/后门）
        "stray": sorted(h for h in exempt - hit if h),
        # 规则③：走软通道的登记项，依据等级不得为 evidence（明确忌必须硬屏蔽）
        "soft_evidence": sorted(
            c["herb"] for c in soft if c.get("level") == "evidence" and c.get("herb")
        ),
        # 规则②：命中集里未登记的仍必须硬屏蔽
        "escaped": sorted(
            h for h in hit - exempt
            if "yin_deficiency" not in (catalog[h].get("unsuitable_for") or [])
        ),
    }


def test_cautions_naming_yinxu_must_be_blocked() -> None:
    """凡 cautions 明写阴虚方向的饮片，都必须被 `yin_deficiency` 挡在候选集外 ——
    除非它在 `_meta.constitution_extension.rulings` 里**登记**为「有意只走 cautions」。

    这是一条**派生不变式**，不是数据快照：它不写死「哪几味被屏蔽」，
    而是从 cautions 与 unsuitable_for 的关系推出来，所以数据怎么变都仍然有效。

    守的是软硬约束的脱节：`cautions` 只进提示词与护栏文案（模型可以不听），
    `unsuitable_for` 才是硬过滤。二者脱节就会出现「项目自己已认定阴虚不宜，
    却照样推给阴虚用户」—— 而这种错误从输出表面**看不出来**。

    豁免出口是 2026-09-17 落地的（`docs/herbs-9types-batch2.md`）。它有三条强制约束，
    都在 `_cautions_soft_gap` 里，缺一条闸门就漏：
      ① 豁免项必须 ∈ 命中集 —— 登记表不能变成绕过检查的后门；
      ② 命中集里**未登记**的仍必须硬屏蔽 —— 防线不松；
      ③ **走软通道的登记项，依据等级不得为 `evidence`** —— 「明确忌 → 硬屏蔽」由代码强制，
         不靠人记得（香薷 2026-09-20 由 evidence 降为 inference，但仍落 unsuitable_for：规则③只约束**软通道**，降级本身不会让本条报红）。
    """
    gap = _cautions_soft_gap(load_herb_catalog(), load_rulings_cells())

    assert gap["hit"], "阴虚方向关键词一条都没命中，本测试已失去覆盖面，需同步更新关键词或 cautions"
    assert not gap["stray"], (
        f"这些饮片登记为『只走 cautions』，但 cautions 并不命中阴虚方向关键词：{gap['stray']}。"
        "登记表必须只收录真实命中的格子，否则它就成了绕过检查的后门"
    )
    assert not gap["soft_evidence"], (
        f"这些登记项的依据等级是 evidence，却想走 cautions 软通道：{gap['soft_evidence']}。"
        "evidence 级（明确忌）必须写进 unsuitable_for —— 依据等级决定写哪个字段"
    )
    assert not gap["escaped"], (
        f"这些饮片的 cautions 已明写阴虚方向，却既没被 yin_deficiency 屏蔽、也没登记豁免：{gap['escaped']}。"
        "要么补 unsuitable_for，要么在 `_meta` 的 rulings 块里登记为 cautions-only（等级不得为 evidence）"
    )


def test_cautions_soft_gap_negative_controls() -> None:
    """人造数据必须让三类缺口各自报出来 —— 否则上一条测试可能根本没在检查。"""
    catalog = {
        "a": {"cautions": ["阴虚者不宜"], "unsuitable_for": ["yin_deficiency"]},
        "b": {"cautions": ["阴虚者慎用"], "unsuitable_for": []},
        "c": {"cautions": ["孕妇不宜"], "unsuitable_for": []},  # 不命中关键词
    }
    good = [{"herb": "b", "constitution": "yin_deficiency", "level": "inference", "field": "cautions"}]

    g = _cautions_soft_gap(catalog, good)
    assert g["hit"] == {"a", "b"} and not (g["stray"] or g["soft_evidence"] or g["escaped"])

    # ① 登记了一个并不命中的饮片
    g = _cautions_soft_gap(
        catalog,
        good + [{"herb": "c", "constitution": "yin_deficiency", "level": "inference", "field": "cautions"}],
    )
    assert g["stray"] == ["c"], "规则①失效：登记表可以收录没命中的格子"

    # ③ 把登记项改成 evidence
    g = _cautions_soft_gap(catalog, [{**good[0], "level": "evidence"}])
    assert g["soft_evidence"] == ["b"], "规则③失效：明确忌可以走软通道"

    # ② 抹掉一个未登记项的屏蔽
    broken = {**catalog, "a": {"cautions": ["阴虚者不宜"], "unsuitable_for": []}}
    g = _cautions_soft_gap(broken, good)
    assert g["escaped"] == ["a"], "规则②失效：未登记的条目可以逃脱硬屏蔽"


def test_rulings_cells_are_well_formed() -> None:
    """批次块每一格都要齐备，且 level 与 field 的搭配合法：`evidence` 只能写 `unsuitable_for`。

    规则③ 在阴虚方向上由 `_cautions_soft_gap` 强制；这条把它推广到**所有格子**
    —— 因为「明确忌必须硬屏蔽」与方向无关。反向不成立：`inference` 也允许写
    `unsuitable_for`（保守方向，cautions 批次 10 味就是这么做的）。
    """
    cells = load_rulings_cells()
    assert cells, "rulings.cells 为空 —— 要么本批没落地，要么登记被误删"
    for c in cells:
        for k in ("herb", "constitution", "verdict", "level", "field", "basis"):
            assert c.get(k), f"{c.get('herb')} 的登记缺字段 {k}"
        assert c["field"] in ("unsuitable_for",) + ROLLING_SOFT_FIELDS, f"未知 field：{c['field']}"
        if c["level"] == "evidence":
            assert c["field"] == "unsuitable_for", (
                f"{c['herb']}×{c['constitution']} 是 evidence 级却写了 {c['field']}："
                "明确忌必须落 unsuitable_for"
            )


def test_yinxu_cautions_batch_is_blocked_at_runtime() -> None:
    """批次的 10 味必须在**运行时**真的进不了阴虚候选集——不只是数据里有标注。

    用大 `limit` 取全池，避免被 `filter_by_constitution` 默认的 `limit=12` 截断掩盖：
    被截断的条目本来就不在 top12 里，「没出现」说明不了它被屏蔽了。
    本批的实际效果正是**换个位置**——茯苓/陈皮/龙眼肉被挤出 top12，
    而池子本身被硬屏蔽砍掉 11 味（本批 10 味 + 香薷），其余多味（生姜/藿香/紫苏/佛手/橘红/薏苡仁/茉莉花等）
    本来排在截断线之外，只靠 top12 是**完全看不出来**的。
    """
    pool = {item["id"] for item in filter_by_constitution("yin_deficiency", limit=999)}
    leaked = sorted(CAUTIONS_BATCH_YINXU & pool)
    assert not leaked, f"这些不该出现在阴虚候选集里：{leaked}"
    assert "sangshen" in pool, "桑椹是阴虚唯一的『宜』，不该被挡住"



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


# ============================================================
# 须煎煮 / 焖泡（2026-09-18，见 docs/agent2-9types-brew-plan.md）
# ============================================================
# 人裁定登记表：这 12 味是「质地坚实、保温杯焖泡出不了味」的品种，
# 依据是各自 herbs.json 的 brewing 原文（下面逐条断言依据真的在数据里）。
# ⚠️ 这是**人裁定快照**，允许因为数据治理而变红 —— 与上面的派生不变式不同，
# 它记录的是「人做过的决定」，漂移时应当有人看一眼，而不是自动跟随。
EXPECTED_COOK_REQUIRED = {
    "茯苓": "需先煎或久煮 10 分钟以上才易出味，直接冲泡效果差",
    "百合": "需煮 8–10 分钟，冲泡难以出味",
    "莲子": "需煮 10 分钟以上",
    "薏苡仁": "质地坚硬，建议先煮 15 分钟或直接用炒制打碎款",
    "山药": "需煮 10 分钟以上，冲泡难出味",
    "白扁豆": "质地坚硬，务必先煮 15 分钟",
    # 阶段 3 批二（2026-09-20）：种仁／豆类，与上面 6 味同口径
    "芡实": "质地坚实，需煮 15 分钟以上",
    "赤小豆": "豆类质地坚硬，务必先煮 20 分钟以上",
    # 阶段 3 批三a（2026-09-20）：根茎／蒸制块状，与上面 8 味同口径
    "玉竹": "质地柔润，需煮 10 分钟以上出味更佳",
    "黄精": "蒸制饮片质地坚实，需煮 15 分钟以上，久煮更易出味",
    # 阶段 3 批三b（2026-09-20）：根／块根，与上面 10 味同口径
    "葛根": "质硬，需煮 15 分钟以上才易出味",
    "天冬": "质地柔韧，需煮 10 分钟以上",
}


def _brewing_text(entry: dict) -> str:
    brewing = entry.get("brewing") or {}
    return "".join(str(brewing.get(k) or "") for k in ("form", "note", "prep"))


def test_cook_required_list_is_registered() -> None:
    """须煎煮清单是人裁定的，逐条登记依据，漂移即报出来。"""
    catalog = load_herb_catalog()
    by_name = {item["name"]: item for item in catalog.values()}

    for name, basis in EXPECTED_COOK_REQUIRED.items():
        assert name in by_name, f"{name} 不在饮片库里"
        entry = by_name[name]
        assert herb_requires_cooking(entry), f"{name} 的 requires_cooking 标记丢了"
        assert basis in _brewing_text(entry), (
            f"{name} 的登记依据在数据里找不到：{basis!r} —— 改了 note/prep 请同步登记表"
        )

    actual = {item["name"] for item in catalog.values() if herb_requires_cooking(item)}
    assert actual == set(EXPECTED_COOK_REQUIRED), (
        f"须煎煮清单漂移：新增 {sorted(actual - set(EXPECTED_COOK_REQUIRED))}、"
        f"减少 {sorted(set(EXPECTED_COOK_REQUIRED) - actual)}"
    )


def test_cook_required_flag_has_textual_basis() -> None:
    """标了 `requires_cooking` 的，必须在自己的 brewing 文本里读得到「煮/煎/炖」依据。

    派生不变式，不写死名单：标记不能凭空出现，否则「为什么要煮」只剩一个布尔值，
    后来者无从复核。关键词刻意不含「熬」—— 它会命中麦冬、桑椹的「适合熬夜后口干」。
    """
    bad = cook_required_without_basis(load_herb_catalog())
    assert not bad, f"这些饮片标了须煎煮，但 brewing 文本里找不到依据：{bad}"

    flagged = [i["id"] for i in load_herb_catalog().values() if herb_requires_cooking(i)]
    assert flagged, "一条 requires_cooking 都没有 —— 上面那条检查已失去覆盖面"


def test_cook_required_basis_check_negative_control() -> None:
    """人造一条「标了须煎煮、文本里却没依据」的数据，断言被报出来。"""
    catalog = {
        "x": {"brewing": {"note": "香气易挥发，加盖焖 3 分钟即可", "requires_cooking": True}},
        "y": {"brewing": {"note": "需煮 10 分钟以上", "requires_cooking": True}},
        "z": {"brewing": {"note": "需煮 5 分钟"}},  # 没标，不该被算进来
    }
    assert cook_required_without_basis(catalog) == ["x"]


def test_check_brew_adequacy_negative_control() -> None:
    """护栏必须「该报的报、不该报的不报」——只测一边等于没测。"""
    from app.domain.models import BrewGuide

    warm = BrewGuide(
        vessel="保温杯", water_ml=400, water_temp_c=95, steps=["a"], steep_min=8, refill_times=1
    )
    cook = BrewGuide(
        vessel="养生壶", water_ml=600, water_temp_c=100, steps=["a"], steep_min=30, refill_times=0
    )
    long_in_cup = BrewGuide(
        vessel="保温杯", water_ml=400, water_temp_c=100, steps=["a"], steep_min=30, refill_times=0
    )

    # ① 须煎煮 + 焖泡 → 报（且是「改写」不是「拦截」，ok 仍为 True）
    result = check_brew_adequacy([{"name": "茯苓", "amount_g": 8}], warm)
    assert result.ok is True
    assert result.warnings and "茯苓" in result.warnings[0]

    # ② 须煎煮 + 已煎煮 → 不报
    assert not check_brew_adequacy([{"name": "茯苓", "amount_g": 8}], cook).warnings

    # ③ 不必煎煮 + 焖泡 → 不报（防过报）
    assert not check_brew_adequacy([{"name": "陈皮", "amount_g": 5}], warm).warnings

    # ④ 只看时长不看器具会漏判：保温杯焖 30 分钟依然是焖泡
    assert check_brew_adequacy([{"name": "茯苓", "amount_g": 8}], long_in_cup).warnings


def test_fallback_uses_cook_brew_for_cook_required_blend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """兜底搭配含须煎煮的饮片时，必须换成煎煮方式并把原因记进 rule_hits。

    用特禀质默认（山药 10 + 红枣 8）—— 它是「没有非煎煮等价物」的保留项，
    所以真的会走到煎煮路径；痰湿质默认已在 2026-09-18 换成不必煎煮的陈皮荷叶。
    """
    from app.domain.models import ParsedMeal
    from app.services import matcher

    monkeypatch.setattr(matcher, "_pick_rule", lambda parsed: None)
    meal = ParsedMeal(foods=[], overall_nature=Nature.NEUTRAL)

    recs, _, hits = matcher.fallback_recommend(meal, Constitution.SPECIAL_DIATHESIS)
    assert recs, "特禀质默认搭配应当有推荐"
    brew = recs[0].brew
    assert brew.steep_min >= safety.COOK_BREW_MIN_STEEP_MIN, brew
    assert brew.water_temp_c >= 100, brew
    assert "保温杯" not in brew.vessel, brew
    assert "brew_cook_required" in hits, hits


def test_fallback_keeps_default_brew_when_no_cook_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """搭配里没有须煎煮的饮片时，兜底必须保持焖泡、且不留下换法记录。"""
    from app.domain.models import ParsedMeal
    from app.services import matcher

    monkeypatch.setattr(matcher, "_pick_rule", lambda parsed: None)
    meal = ParsedMeal(foods=[], overall_nature=Nature.NEUTRAL)

    recs, _, hits = matcher.fallback_recommend(meal, Constitution.QI_STAGNATION)
    assert recs[0].brew.vessel == matcher.DEFAULT_BREW.vessel
    assert recs[0].brew.steep_min == matcher.DEFAULT_BREW.steep_min
    assert "brew_cook_required" not in hits, hits


def test_phlegm_damp_default_avoids_cook_required() -> None:
    """痰湿质默认搭配必须是「不必煎煮」的 —— 2026-09-18 落地的默认搭配选择纪律。

    原值「茯苓 8 + 陈皮 5」里的茯苓须煮透才出味，而默认搭配走保温杯焖泡。
    改成陈皮 + 荷叶后，主路径不再要求用户备一口养生壶。
    **要改回去之前，请先读 `app/services/matcher.py` 末尾的「默认搭配选择纪律」。**
    """
    from app.services import matcher

    blend, title, _ = matcher.CONSTITUTION_DEFAULT[Constitution.PHLEGM_DAMP.value]
    names = [name for name, _ in blend]
    assert not safety.blend_needs_cooking(names), (
        f"痰湿质默认搭配又含了须煎煮的饮片：{names}"
    )
    assert "荷叶" in names, names
    assert title == "陈皮荷叶化湿饮", title


# ============================================================
# 兼体质屏蔽集 avoid（B2 接入 · 提交 2）
# ============================================================
# 合成数据，不拿真实饮片当样本：真实标注会随数据补齐而变，
# 测的是「avoid 有没有生效」，不是「现在哪味饮片标了什么」。
_FAKE_CATALOG: dict[str, dict] = {
    "陈皮": {
        "name": "陈皮",
        "nature": "warm",
        "flavors": ["pungent"],
        "meridians": ["脾"],
        "effects": ["理气"],
        "max_daily_g": 6,
        "suitable_constitutions": ["qi_deficiency"],
        "unsuitable_for": [],
        "brewing": {"requires_cooking": False},
    },
    "金银花": {
        "name": "金银花",
        "nature": "cold",
        "flavors": ["sweet"],
        "meridians": ["肺"],
        "effects": ["清热"],
        "max_daily_g": 6,
        "suitable_constitutions": ["qi_deficiency"],
        "unsuitable_for": ["yang_deficiency"],
        "brewing": {"requires_cooking": False},
    },
}


def test_avoid_blocks_herbs_unsuitable_for_secondary_constitution(
    monkeypatch,
) -> None:
    """屏蔽集里体质标为「不宜」的饮片必须被挡在候选集外。

    兼体质只能有一个收敛方向（主导体质），其余体质不改方向、只做排除 ——
    所以这里断言的是「排除」，不是「换方向」。
    """
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: _FAKE_CATALOG)

    plain = [h["name"] for h in filter_by_constitution("qi_deficiency")]
    both = [
        h["name"]
        for h in filter_by_constitution("qi_deficiency", avoid=("yang_deficiency",))
    ]

    # 负控制：不给 avoid 时它还在 ⇒ 上面的消失确实由 avoid 造成，不是碰巧没数据
    assert "金银花" in plain
    assert "金银花" not in both
    assert "陈皮" in both, "主导体质契合且未被屏蔽的饮片必须留下"

    # 透传：Agent2 的候选清单里也必须看不到它（模型看不见 ⇒ 不可能被选上）
    from app.agents.agent2_recommend import _candidate_lines

    lines = _candidate_lines(Constitution.QI_DEFICIENCY, avoid=("yang_deficiency",))
    assert "金银花" not in lines
    assert "陈皮" in lines


def test_avoid_empty_is_equivalent_to_no_avoid(monkeypatch) -> None:
    """收口判据：既有调用方不传 avoid 时，行为必须与改动前**完全一致**。

    遍历全部就绪体质，而不是抽查一个 —— 只改一处最容易漏的就是「别的体质变了」。
    """
    for cid in sorted(ready_constitutions()):
        assert filter_by_constitution(cid, avoid=()) == filter_by_constitution(cid), cid

    # 负控制：判据非真空 —— 非空 avoid 在合成数据上确实会改变结果，
    # 否则上面那条等式可能只是「两边都返回同一个东西」。
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: _FAKE_CATALOG)
    assert filter_by_constitution(
        "qi_deficiency", avoid=("yang_deficiency",)
    ) != filter_by_constitution("qi_deficiency")


# ============================================================
# 离线路径的兼体质屏蔽（B2 接入 · 提交 3，D6-A′ 硬剔除）
# ============================================================
def _warm_meal():
    from app.domain.models import ParsedFood, ParsedMeal

    # 命中 RULES 里的 greasy（陈皮 + 山楂）。刻意**不** monkeypatch `_pick_rule`：
    # 场景规则分支才是正常流程真正走的那条，而它原本完全不经过体质。
    return ParsedMeal(
        foods=[ParsedFood(name="牛肉", amount_desc="一盘")],
        overall_nature=Nature.WARM,
    )


def test_offline_avoid_removes_blocked_herbs_on_rule_branch() -> None:
    """离线路径命中场景规则时，屏蔽集同样要生效（§0.1 的核心）。

    陈皮对阴虚质标不宜、山楂对气虚质标不宜 —— 这两条都来自真实 herbs.json，
    不靠合成数据（拿真实标注当样本在这里是安全的：断言的是「剔除动作发生了」，
    且饮片名在测试里写死，数据一改这里就会红，正是想要的）。
    """
    from app.services import matcher

    plain, _, _ = matcher.fallback_recommend(_warm_meal(), Constitution.BALANCED)
    plain_names = {h.name for h in plain[0].herbs}
    # 负控制：不给 avoid 时两味都在 ⇒ 下面的消失确实是屏蔽造成的
    assert plain_names == {"陈皮", "山楂"}, plain_names

    recs, _, _ = matcher.fallback_recommend(
        _warm_meal(), Constitution.BALANCED, avoid=("yin_deficiency",)
    )
    names = {h.name for h in recs[0].herbs}
    assert "陈皮" not in names, names
    assert "山楂" in names, names


def test_offline_avoid_never_returns_empty_or_unsafe_blend() -> None:
    """硬剔除把整组剔空 ⇒ 退通用兜底，并留痕。契约是「永远给出合法且安全的搭配」。

    不能因为屏蔽就把推荐清空 —— 那等于用「没答案」代替「安全答案」。
    """
    from app.services import matcher

    avoid = ("yin_deficiency", "qi_deficiency")  # 陈皮 + 山楂 都会被剔掉
    recs, _, hits = matcher.fallback_recommend(
        _warm_meal(), Constitution.BALANCED, avoid=avoid
    )

    assert recs, "剔空后必须退通用兜底，不能返回空推荐"
    assert recs[0].herbs
    assert "avoid_cleared_blend" in hits, hits
    assert "原搭配对兼夹体质不宜" in recs[0].fit_reason, "必须说明这不是原配的那组"

    # 兜底上来的饮片同样要过屏蔽集 —— 否则只是把不安全往后挪了一层
    blocked = matcher._herbs_unsuitable_for_any(set(avoid))
    assert not ({h.name for h in recs[0].herbs} & blocked)
