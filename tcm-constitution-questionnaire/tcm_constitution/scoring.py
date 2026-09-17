"""GB/T 46939-2025 中医体质计分与判定。"""

from __future__ import annotations

from typing import Any, Mapping

from .questions import (
    BIASED_CONSTITUTIONS,
    CONSTITUTION_NAMES,
    questions_for_sex,
)


def reverse_score(value: int) -> int:
    """五级评分的逆向计分：1↔5、2↔4、3 不变。"""

    return 6 - value


def transformed_score(raw_score: int, item_count: int) -> float:
    """国标转化分公式，结果范围为 0–100。"""

    if item_count <= 0:
        raise ValueError("item_count 必须大于 0")
    return (raw_score - item_count) / (item_count * 4) * 100


def classify_biased(score: float) -> str:
    """判定八种偏颇体质之一。"""

    if score >= 40:
        return "是"
    if score >= 30:
        return "倾向是"
    return "否"


def classify_balanced(score: float, biased_scores: Mapping[str, float]) -> str:
    """结合其余八种体质分数判定平和质。"""

    values = list(biased_scores.values())
    if len(values) != 8:
        raise ValueError("平和质判定需要全部 8 种偏颇体质的转化分")
    if score >= 60 and all(value < 30 for value in values):
        return "是"
    if score >= 60 and all(value < 40 for value in values):
        return "基本是"
    return "否"


def score_questionnaire(answers: Mapping[str, int], sex: str) -> dict[str, Any]:
    """计算全部九种体质的原始分、转化分和标准判定。

    Parameters
    ----------
    answers:
        题号到 1–5 整数答案的映射。重复用于多个分量表的问题只需回答一次。
    sex:
        ``female`` 或 ``male``，仅用于选择湿热质的性别限定题。
    """

    questions = questions_for_sex(sex)
    missing = [q.id for q in questions if q.id not in answers]
    if missing:
        raise ValueError(f"缺少答案：{', '.join(missing)}")

    invalid = {
        q.id: answers[q.id]
        for q in questions
        if isinstance(answers[q.id], bool)
        or not isinstance(answers[q.id], int)
        or not 1 <= answers[q.id] <= 5
    }
    if invalid:
        raise ValueError(f"答案必须是 1–5 的整数：{invalid}")

    scale_values: dict[str, list[int]] = {key: [] for key in CONSTITUTION_NAMES}
    for question in questions:
        answer = answers[question.id]
        for use in question.uses:
            scale_values[use.scale].append(reverse_score(answer) if use.reverse else answer)

    score_details: dict[str, dict[str, Any]] = {}
    precise_scores: dict[str, float] = {}
    for scale, values in scale_values.items():
        raw = sum(values)
        precise = transformed_score(raw, len(values))
        precise_scores[scale] = precise
        score_details[scale] = {
            "name": CONSTITUTION_NAMES[scale],
            "raw_score": raw,
            "item_count": len(values),
            "transformed_score": round(precise, 2),
        }

    biased_scores = {key: precise_scores[key] for key in BIASED_CONSTITUTIONS}
    score_details["balanced"]["status"] = classify_balanced(
        precise_scores["balanced"], biased_scores
    )
    for scale in BIASED_CONSTITUTIONS:
        score_details[scale]["status"] = classify_biased(precise_scores[scale])

    confirmed = [
        CONSTITUTION_NAMES[key]
        for key in BIASED_CONSTITUTIONS
        if score_details[key]["status"] == "是"
    ]
    tendencies = [
        CONSTITUTION_NAMES[key]
        for key in BIASED_CONSTITUTIONS
        if score_details[key]["status"] == "倾向是"
    ]
    ranking = sorted(
        (
            {
                "constitution": CONSTITUTION_NAMES[key],
                "score": round(precise_scores[key], 2),
                "status": score_details[key]["status"],
            }
            for key in BIASED_CONSTITUTIONS
        ),
        key=lambda row: (-row["score"], row["constitution"]),
    )

    return {
        "standard": "GB/T 46939-2025",
        "sex_specific_path": sex,
        "scores": score_details,
        "summary": {
            "balanced": score_details["balanced"]["status"],
            "biased_constitutions_confirmed": confirmed,
            "biased_constitutions_tendency": tendencies,
        },
        "ranking_nonstandard": ranking,
        "notes": [
            "标准允许多种偏颇体质同时判定为“是”或“倾向是”。",
            "ranking_nonstandard 仅按分数排序，不是国标规定的唯一主导体质诊断。",
            "本结果用于体质筛查与健康教育，不能替代中医师四诊合参或医疗诊断。",
        ],
    }
