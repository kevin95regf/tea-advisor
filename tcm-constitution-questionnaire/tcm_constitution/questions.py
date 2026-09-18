"""GB/T 46939-2025 中医体质问卷题库。

问卷附录有 30 个计分条目，其中 3 个问题同时用于两个分量表。
本模块的题库含 27 个不同问题；因湿热质的两个性别限定题只答其一，
每位答题者实际回答 26 个问题。计分时，同一答案会按国标分别计入相应分量表。
"""

from __future__ import annotations

from dataclasses import dataclass


ANSWER_LABELS: dict[int, str] = {
    1: "没有（根本不）",
    2: "很少（有一点）",
    3: "有时（有些）",
    4: "经常（相当）",
    5: "总是（非常）",
}

CONSTITUTION_NAMES: dict[str, str] = {
    "balanced": "平和质",
    "qi_deficiency": "气虚质",
    "yang_deficiency": "阳虚质",
    "yin_deficiency": "阴虚质",
    "phlegm_damp": "痰湿质",
    "damp_heat": "湿热质",
    "blood_stasis": "血瘀质",
    "qi_stagnation": "气郁质",
    "special_diathesis": "特禀质",
}

BIASED_CONSTITUTIONS: tuple[str, ...] = tuple(
    key for key in CONSTITUTION_NAMES if key != "balanced"
)


@dataclass(frozen=True)
class ScaleUse:
    """一个题目在某分量表中的用法。"""

    scale: str
    reverse: bool = False


@dataclass(frozen=True)
class Question:
    """去重后的一个问卷问题。"""

    id: str
    text: str
    uses: tuple[ScaleUse, ...]
    sex: str | None = None


QUESTIONS: tuple[Question, ...] = (
    Question("q01", "您精力充沛吗？", (ScaleUse("balanced"),)),
    Question(
        "q02",
        "您容易疲乏吗？",
        (ScaleUse("balanced", reverse=True), ScaleUse("qi_deficiency")),
    ),
    Question(
        "q03",
        "您感到闷闷不乐、情绪低沉吗？",
        (ScaleUse("balanced", reverse=True), ScaleUse("qi_stagnation")),
    ),
    Question(
        "q04",
        "您比一般人耐受不了寒冷（冬天的寒冷，夏天的冷空调、电扇等）吗？",
        (ScaleUse("balanced", reverse=True), ScaleUse("yang_deficiency")),
    ),
    Question(
        "q05", "您容易气短（呼吸短促，接不上气）吗？", (ScaleUse("qi_deficiency"),)
    ),
    Question("q06", "您容易心慌吗？", (ScaleUse("qi_deficiency"),)),
    Question(
        "q07", "您胃脘部、背部或腰膝部怕冷吗？", (ScaleUse("yang_deficiency"),)
    ),
    Question(
        "q08", "您感到怕冷，衣服比别人穿得多吗？", (ScaleUse("yang_deficiency"),)
    ),
    Question(
        "q09", "您感觉身体、脸上发热吗？", (ScaleUse("yin_deficiency"),)
    ),
    Question("q10", "您皮肤或口唇干吗？", (ScaleUse("yin_deficiency"),)),
    Question(
        "q11", "您面部两颧潮红或偏红吗？", (ScaleUse("yin_deficiency"),)
    ),
    Question(
        "q12",
        "您感到身体沉重不轻松或不爽快吗？",
        (ScaleUse("phlegm_damp"),),
    ),
    Question(
        "q13", "您腹部肥满松软吗？", (ScaleUse("phlegm_damp"),)
    ),
    Question(
        "q14", "您嘴里有黏黏的感觉吗？", (ScaleUse("phlegm_damp"),)
    ),
    Question(
        "q15",
        "您面部或鼻部有油腻感或者油亮发光吗？",
        (ScaleUse("damp_heat"),),
    ),
    Question(
        "q16", "您小便时尿道有发热感、尿色浓（深）吗？", (ScaleUse("damp_heat"),)
    ),
    Question(
        "q17_female",
        "您带下色黄（白带颜色发黄）吗？",
        (ScaleUse("damp_heat"),),
        sex="female",
    ),
    Question(
        "q17_male",
        "您的阴囊部位潮湿吗？",
        (ScaleUse("damp_heat"),),
        sex="male",
    ),
    Question("q18", "您身体上有哪里疼痛吗？", (ScaleUse("blood_stasis"),)),
    Question(
        "q19", "您面色晦黯或容易出现褐斑吗？", (ScaleUse("blood_stasis"),)
    ),
    Question("q20", "您口唇颜色偏暗吗？", (ScaleUse("blood_stasis"),)),
    Question(
        "q21", "您容易精神紧张、焦虑不安吗？", (ScaleUse("qi_stagnation"),)
    ),
    Question(
        "q22", "您多愁善感、感情脆弱吗？", (ScaleUse("qi_stagnation"),)
    ),
    Question(
        "q23", "您没有感冒时也会打喷嚏吗？", (ScaleUse("special_diathesis"),)
    ),
    Question(
        "q24",
        "您容易过敏（对药物、食物、气味、花粉或在季节交替、气候变化时）吗？",
        (ScaleUse("special_diathesis"),),
    ),
    Question(
        "q25",
        "您的皮肤容易起荨麻疹（风团、风疹块、风疙瘩）吗？",
        (ScaleUse("special_diathesis"),),
    ),
    Question(
        "q26", "您的皮肤一抓就红，并出现抓痕吗？", (ScaleUse("special_diathesis"),)
    ),
)

QUESTION_BY_ID: dict[str, Question] = {question.id: question for question in QUESTIONS}


def questions_for_sex(sex: str) -> tuple[Question, ...]:
    """返回本次应回答的问题；湿热质只保留一个性别限定题。"""

    if sex not in {"female", "male"}:
        raise ValueError("sex 必须是 'female' 或 'male'")
    return tuple(q for q in QUESTIONS if q.sex is None or q.sex == sex)
