"""问卷 scores → 推荐链路输入 的换算层守卫。

写法沿用本仓的「派生不变式 + 负控制」范式：每条守卫除了断言好样本成立，
还要断言**坏样本上同一条判据为假** —— 否则守卫可能一直是真空的，红了绿了都说明不了问题。

不写数据快照：样本一律用 `_mk()` 现场合成，**不用真实问卷结果当样本**
（真实数据的分布会随题库/权重变化，测的是数据现状而不是换算逻辑）。

七条守卫：

* R1 输出 id 全 ∈ `Constitution`，非法 id 当场报错（防 `phlegm_dampness` 回流）
* R2 主导体质不得出现在屏蔽集里
* R3 每个「是」都必须落在 `primary ∪ avoid`（不丢）
* R4 有「是」时，「倾向是」绝不能当主导体质
* R5 `tendency` 的 note 必含强制告知（D2-B）
* R6 分数并列时结果确定（同输入两次一致）
* R7 判不出就抛错，**不许默认平和质**（D3）
"""

from __future__ import annotations

import pytest

from app.domain.constitution_resolver import (
    TENDENCY_NOTICE,
    Resolution,
    UndeterminedConstitutionError,
    UnknownConstitutionError,
    resolve_from_scores,
    validate_resolution,
)
from app.domain.enums import CONSTITUTION_LABELS, Constitution


def _mk(
    entries: dict[str, tuple[str, float]],
    *,
    balanced: str = "否",
    balanced_score: float = 50.0,
) -> dict:
    """合成一个 `score_questionnaire()["scores"]` 形状的入参。

    entries: {体质 id: (判定字面量, 转化分)}；插入顺序保留，供 R6 测确定性。
    """

    scores = {
        cid: {
            "name": CONSTITUTION_LABELS.get(cid, cid),
            "transformed_score": score,
            "status": status,
        }
        for cid, (status, score) in entries.items()
    }
    scores.setdefault(
        Constitution.BALANCED.value,
        {
            "name": CONSTITUTION_LABELS[Constitution.BALANCED.value],
            "transformed_score": balanced_score,
            "status": balanced,
        },
    )
    return scores


def _ids(res: Resolution) -> set[str]:
    return {res.primary.value, *(a.value for a in res.avoid)}


def _covers(confirmed: set[str], res: Resolution) -> bool:
    return confirmed <= _ids(res)


def _tendency_not_primary(res: Resolution, tendency_id: str) -> bool:
    return res.primary.value != tendency_id


def test_r1_output_ids_are_valid_constitutions() -> None:
    res = resolve_from_scores(
        _mk({"qi_deficiency": ("是", 55.0), "yang_deficiency": ("是", 45.0)})
    )
    assert _ids(res) <= {c.value for c in Constitution}

    # 负控制：旧拼写一旦回流必须当场炸，而不是静默变成匹配不上任何规则的 id
    with pytest.raises(UnknownConstitutionError):
        resolve_from_scores(_mk({"phlegm_dampness": ("是", 55.0)}))


def test_r2_primary_never_in_avoid() -> None:
    res = resolve_from_scores(
        _mk(
            {
                "qi_deficiency": ("是", 55.0),
                "yang_deficiency": ("是", 45.0),
                "yin_deficiency": ("是", 41.0),
            }
        )
    )
    assert res.primary not in res.avoid

    # 负控制：校验器必须能抓到「主导体质被自己屏蔽」——会把推荐收敛到空集
    bad = Resolution(
        primary=Constitution.QI_DEFICIENCY,
        avoid=[Constitution.QI_DEFICIENCY],
        status="confirmed",
    )
    with pytest.raises(ValueError):
        validate_resolution(bad)


def test_r3_every_confirmed_is_covered() -> None:
    confirmed = {"qi_deficiency", "yang_deficiency", "yin_deficiency"}
    res = resolve_from_scores(_mk({cid: ("是", 50.0) for cid in confirmed}))
    assert _covers(confirmed, res)

    # 负控制：只收 2 个（漏 1 个）必须被判出来
    truncated = Resolution(
        primary=Constitution.QI_DEFICIENCY,
        avoid=[Constitution.YANG_DEFICIENCY],
        status="confirmed",
    )
    assert not _covers(confirmed, truncated)


def test_r4_tendency_never_becomes_primary_when_confirmed() -> None:
    res = resolve_from_scores(
        _mk({"qi_deficiency": ("是", 55.0), "yang_deficiency": ("倾向是", 35.0)})
    )
    assert _tendency_not_primary(res, "yang_deficiency")
    # 倾向不是判定，也不进屏蔽集 —— 避免过度屏蔽
    assert res.avoid == []

    # 负控制：同一判据在坏样本上必须为假，证明上面那条不是真空断言
    bad = Resolution(
        primary=Constitution.YANG_DEFICIENCY,
        avoid=[Constitution.QI_DEFICIENCY],
        status="confirmed",
    )
    assert not _tendency_not_primary(bad, "yang_deficiency")


def test_r5_tendency_note_is_mandatory() -> None:
    res = resolve_from_scores(_mk({"qi_deficiency": ("倾向是", 35.0)}))
    assert res.status == "tendency"
    assert TENDENCY_NOTICE in res.note

    # 负控制：去掉强制告知的那一句必须被拒
    bad = Resolution(
        primary=Constitution.QI_DEFICIENCY,
        status="tendency",
        note="按倾向处理：倾向气虚质。",
    )
    with pytest.raises(ValueError):
        validate_resolution(bad)


def test_r6_tie_is_deterministic() -> None:
    first = _mk({"yin_deficiency": ("是", 40.0), "blood_stasis": ("是", 40.0)})
    swapped = _mk({"blood_stasis": ("是", 40.0), "yin_deficiency": ("是", 40.0)})
    r1 = resolve_from_scores(first)
    r2 = resolve_from_scores(swapped)
    assert r1.primary == r2.primary
    assert [a.value for a in r1.avoid] == [a.value for a in r2.avoid]

    # 负控制：判据非真空 —— 并列时取枚举序靠前者，另一个必须落进屏蔽集
    order = [c.value for c in Constitution]
    earlier, later = sorted(["yin_deficiency", "blood_stasis"], key=order.index)
    assert r1.primary.value == earlier
    assert later in {a.value for a in r1.avoid}


def test_r7_undetermined_raises_instead_of_defaulting_to_balanced() -> None:
    with pytest.raises(UndeterminedConstitutionError):
        resolve_from_scores(_mk({"qi_deficiency": ("否", 10.0)}, balanced="否"))

    # 负控制：平和质为「是」时**不许**抛 —— 证明上面不是「总是抛」
    ok = resolve_from_scores(
        _mk({"qi_deficiency": ("否", 10.0)}, balanced="是", balanced_score=75.0)
    )
    assert ok.primary == Constitution.BALANCED
    assert ok.status == "balanced"
