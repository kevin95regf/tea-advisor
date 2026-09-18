"""问卷结果 → 推荐链路输入的换算层（纯函数，不依赖问卷子包）。

设计约束（见 `docs/b2-questionnaire-integration-plan.md`）：

* **core 不 import `tcm-constitution-questionnaire`** —— 入参就是那个 `scores` dict，
  所以 core 的测试零外部依赖（D5）。
* 换算必须**从 `scores` 的键取 id**，不能反查中文名：子包 `summary` 里装的是中文名，
  反查等于维护第二份事实源。B2 改名（`phlegm_dampness` → `phlegm_damp`）的价值就在这一步兑现。

入参形状（`score_questionnaire()["scores"]`）::

    {"<constitution_id>": {"name": ..., "transformed_score": float, "status": str, ...}}

偏颇体质的 `status` ∈ {"是", "倾向是", "否"}；平和质 ∈ {"是", "基本是", "否"}。

⚠️ 语义边界（D2/D3）：「倾向是」（转化分 30–40）**不是判定**，只是筛查信号。
它不进屏蔽集，只在没有任何「是」时才顶上来当主导体质，且必须强制告知用户。
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

from .enums import CONSTITUTION_LABELS, Constitution

# 国标判定用的字面量。写成常量而不是散落的字符串，避免与子包的取值漂移。
STATUS_YES = "是"
STATUS_TENDENCY = "倾向是"
STATUS_BASIC_YES = "基本是"

# 「基本是」要向用户点名的偏颇体质分数下限（30 分起是「倾向是」）。
TENDENCY_FLOOR = 30

# D2-B 的强制告知文案：倾向兜底时必须原样告知，一个字都不能少。
TENDENCY_NOTICE = "问卷未达判定阈值，按倾向处理"


class UnknownConstitutionError(ValueError):
    """`scores` 里出现了不是 `Constitution` 合法值的键，或缺少必要字段。

    这条错误的意义是**防回潮**：`phlegm_dampness` 之类的旧拼写一旦从问卷侧回流，
    会在换算时当场炸掉，而不是静默变成一个匹配不上任何规则的 id。
    与 `tests/test_questionnaire_id_alignment.py` 互为表里。
    """


class UndeterminedConstitutionError(ValueError):
    """判不出体质：平和质为「否」，且既无「是」也无「倾向是」。

    此时**不许默认平和质**（D3）—— 冒充平和质会让用户拿到一份无依据的推荐。
    调用方应当让用户手动选。
    """


class Resolution(BaseModel):
    """问卷结果换算后的推荐链路输入。"""

    # 主导体质：唯一的收敛方向（推荐只能按一个方向做）。
    primary: Constitution
    # 屏蔽集：这些体质标为「不宜」的饮片要一并排除，但不改变收敛方向。
    avoid: list[Constitution] = Field(default_factory=list)
    # 判定来源，决定 note 的写法，也决定调用方要不要强制提示。
    status: Literal["confirmed", "tendency", "balanced", "balanced_basic"]
    # 直接可拼进 AnalyzeResponse.user_message 的说明（D7：不动 Basis，说明走这里）。
    note: str = ""


def _enum_order(value: str) -> int:
    """体质在 `Constitution` 枚举里的位次，用于并列分数时的确定性兜底。"""

    return list(Constitution).index(Constitution(value))


def _sorted_by_score(scores: Mapping[str, Any], ids: list[str]) -> list[str]:
    """按转化分降序；分数并列时按枚举顺序 —— 保证同一输入永远同一输出。"""

    return sorted(
        ids,
        key=lambda key: (-float(scores[key]["transformed_score"]), _enum_order(key)),
    )


def _labels(ids: list[str]) -> str:
    return "、".join(CONSTITUTION_LABELS.get(i, i) for i in ids)


def validate_resolution(resolution: Resolution) -> None:
    """校验一个 `Resolution` 是否自洽。

    独立成公开函数，是为了让守卫测试能**直接喂一个坏样本**验证检查本身有效
    （不是只能测「好样本通过」）。由 `resolve_from_scores` 在返回前调用。
    """

    if resolution.primary in resolution.avoid:
        raise ValueError(
            f"主导体质 {resolution.primary.value} 同时出现在屏蔽集里，会把推荐收敛到空集"
        )
    if resolution.status == "tendency" and TENDENCY_NOTICE not in resolution.note:
        raise ValueError(
            f"status=tendency 的 note 必须包含强制告知「{TENDENCY_NOTICE}」"
        )


def resolve_from_scores(scores: Mapping[str, Any]) -> Resolution:
    """把 `score_questionnaire()["scores"]` 换算成推荐链路的输入。

    判定顺序（D1 主导 + 其余进屏蔽集｜D2-B 倾向兜底 + 强制告知｜D3 平和三档）：

    1. 有「是」⇒ 最高分者为主导体质，其余「是」进屏蔽集
    2. 无「是」有「倾向是」⇒ 最高分倾向为主导体质，**屏蔽集为空**（倾向不是判定）
    3. 都没有、平和质「是」⇒ 平和质
    4. 都没有、平和质「基本是」⇒ 平和质 + 点名 30 分以上的偏颇体质
    5. 都没有、平和质「否」⇒ 抛 `UndeterminedConstitutionError`
    """

    if not isinstance(scores, Mapping):
        raise UnknownConstitutionError(f"scores 必须是映射，收到 {type(scores).__name__}")

    valid = {c.value for c in Constitution}
    unknown = sorted(set(scores) - valid)
    if unknown:
        raise UnknownConstitutionError(
            f"scores 含非法体质 id: {unknown}；合法取值: {sorted(valid)}"
        )
    if Constitution.BALANCED.value not in scores:
        raise UnknownConstitutionError(
            f"scores 缺少 '{Constitution.BALANCED.value}'，无法判定平和质"
        )

    for key, detail in scores.items():
        if not isinstance(detail, Mapping):
            raise UnknownConstitutionError(f"scores['{key}'] 必须是映射")
        if "status" not in detail:
            raise UnknownConstitutionError(f"scores['{key}'] 缺少 status")
        if "transformed_score" not in detail:
            raise UnknownConstitutionError(f"scores['{key}'] 缺少 transformed_score")

    biased = [key for key in scores if key != Constitution.BALANCED.value]
    confirmed = _sorted_by_score(
        scores, [k for k in biased if scores[k]["status"] == STATUS_YES]
    )
    tendency = _sorted_by_score(
        scores, [k for k in biased if scores[k]["status"] == STATUS_TENDENCY]
    )

    if confirmed:
        primary, *rest = confirmed
        note = ""
        if rest:
            note = (
                f"问卷判定你兼有{_labels(confirmed)}，本次按"
                f"{CONSTITUTION_LABELS[primary]}收敛方向，"
                f"同时对{_labels(rest)}标为不宜的饮片一并排除。"
            )
        resolution = Resolution(
            primary=Constitution(primary),
            avoid=[Constitution(i) for i in rest],
            status="confirmed",
            note=note,
        )
        validate_resolution(resolution)
        return resolution

    if tendency:
        resolution = Resolution(
            primary=Constitution(tendency[0]),
            avoid=[],
            status="tendency",
            note=f"{TENDENCY_NOTICE}：倾向{_labels(tendency)}。",
        )
        validate_resolution(resolution)
        return resolution

    balanced_status = scores[Constitution.BALANCED.value]["status"]
    if balanced_status == STATUS_YES:
        resolution = Resolution(
            primary=Constitution.BALANCED, avoid=[], status="balanced", note=""
        )
        validate_resolution(resolution)
        return resolution

    if balanced_status == STATUS_BASIC_YES:
        near = _sorted_by_score(
            scores,
            [
                k
                for k in biased
                if float(scores[k]["transformed_score"]) >= TENDENCY_FLOOR
            ],
        )
        listed = f"，以下偏颇体质转化分已达 {TENDENCY_FLOOR} 分及以上：{_labels(near)}" if near else ""
        resolution = Resolution(
            primary=Constitution.BALANCED,
            avoid=[],
            status="balanced_basic",
            note=f"平和质判定为「{STATUS_BASIC_YES}」{listed}。",
        )
        validate_resolution(resolution)
        return resolution

    raise UndeterminedConstitutionError(
        "问卷未能判出体质（平和质为「否」，且无「是」也无「倾向是」），"
        "不默认平和质，请手动选择体质"
    )
