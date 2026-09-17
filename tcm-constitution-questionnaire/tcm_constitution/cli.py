"""中医体质问卷命令行界面。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .questions import ANSWER_LABELS, questions_for_sex
from .scoring import score_questionnaire


def _ask_sex() -> str:
    while True:
        value = input("请选择本次使用的性别限定题 [1=女性, 2=男性]：").strip()
        if value == "1":
            return "female"
        if value == "2":
            return "male"
        print("请输入 1 或 2。")


def _ask_answer(number: int, text: str) -> int:
    print(f"\n{number}. {text}")
    print("  " + "；".join(f"{key}={label}" for key, label in ANSWER_LABELS.items()))
    while True:
        value = input("回答 [1-5]：").strip()
        if value in {"1", "2", "3", "4", "5"}:
            return int(value)
        print("请输入 1、2、3、4 或 5。")


def run_interactive() -> tuple[dict[str, int], str]:
    print("GB/T 46939-2025 中医体质分类与判定（近一年体验和感觉）")
    print("本地运行；程序不会上传或保存答案，除非您使用 --output。")
    sex = _ask_sex()
    questions = questions_for_sex(sex)
    answers = {
        question.id: _ask_answer(index, question.text)
        for index, question in enumerate(questions, start=1)
    }
    return answers, sex


def load_answers(path: Path, sex_override: str | None) -> tuple[dict[str, int], str]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    answers = payload.get("answers", payload)
    sex = sex_override or payload.get("sex")
    if sex not in {"female", "male"}:
        raise ValueError("JSON 中须提供 sex=female/male，或使用 --sex 参数")
    if not isinstance(answers, dict):
        raise ValueError("answers 必须是 JSON 对象")
    return answers, sex


def print_result(result: dict[str, Any]) -> None:
    print("\n判定结果（GB/T 46939-2025）")
    print("-" * 52)
    for detail in result["scores"].values():
        print(
            f"{detail['name']:<5}  转化分 {detail['transformed_score']:>6.2f}  "
            f"判定：{detail['status']}"
        )

    summary = result["summary"]
    confirmed = "、".join(summary["biased_constitutions_confirmed"]) or "无"
    tendencies = "、".join(summary["biased_constitutions_tendency"]) or "无"
    print("-" * 52)
    print(f"平和质：{summary['balanced']}")
    print(f"偏颇体质（是）：{confirmed}")
    print(f"偏颇体质（倾向是）：{tendencies}")
    print("\n提示：允许兼夹体质；最高分排序不等于国标规定的唯一诊断。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GB/T 46939-2025 中医体质问卷")
    parser.add_argument("--input", type=Path, help="读取 JSON 答案；省略则交互答题")
    parser.add_argument("--output", type=Path, help="将完整结果写入 JSON")
    parser.add_argument("--sex", choices=("female", "male"), help="覆盖 JSON 中的 sex")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.input:
            answers, sex = load_answers(args.input, args.sex)
        else:
            answers, sex = run_interactive()
        result = score_questionnaire(answers, sex)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}")
        return 2

    print_result(result)
    if args.output:
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n结果已写入：{args.output}")
    return 0
