"""单字关键词的**跨条目子串**误命中（**D29**）。

背景：`鸡蛋` 的 `keywords` 末项曾是裸字「蛋」，而匹配是**子串级** ⇒ 输入「蛋糕」
会同时命中「蛋糕」与「鸡蛋」（实测 `match_foods('蛋糕') -> ['蛋糕', '鸡蛋']`），
等于**以 0.9 呈现一个不属于它的四气**（与 D4／D5／D17 同族）。

⚠️ 判据**不是长度**：全表 15 个单字 keywords 里只有 6 个踩中（鱼/姜/梨/糖/盐/蛋），
而「粥/虾/蟹/葱/蒜/藕/柑/醋/馍」都是**独立食物名**、命中是对的 ⇒ 一刀切禁单字会
误伤这 9 个。真正的判据是「**这个单字是否作为子串出现在别的条目里**」。

本轮只处理「蛋」（跨物种误命中：蛋糕不是鸡蛋）。其余 5 个（鱼/姜/梨/糖/盐）同类
问题**登记在白名单里**，与 D12 的短 note 白名单同形状：不静默存在，新增即变红。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from app.services.food_lookup import match_foods  # noqa: E402

# 现存（已登记、暂不处理）的单字关键词违规条目：
#   鱼(yuxia) — 生鱼片/水煮鱼/炸鱼薯条 里都有「鱼」（同类，重复但方向不反）
#   姜(jiang) — 姜茶（同类）
#   梨(li)   — 牛油果的别名「鳄梨」含「梨」（**跨物种**，待 D11 同族一起议）
#   糖(tang) — 姜茶的关键词「红糖姜茶」含「糖」
#   盐(yan)  — 炸鸡的关键词「盐酥鸡」含「盐」
SINGLE_CHAR_WHITELIST = frozenset({"yuxia", "jiang", "li", "tang", "yan"})


def _entries() -> list[dict]:
    d = json.loads((CORE_DIR / "data" / "food_properties.json").read_text(encoding="utf-8"))
    return d["foods"] + d["tea_drinks"]["items"]


def _offending_ids(entries: list[dict]) -> set[str]:
    """哪些条目的**单字**关键词，作为子串出现在**别的**条目（≥2 字词）里。"""
    others_words: dict[str, set[str]] = {}
    for e in entries:
        words = {str(w) for w in
                 [e.get("name") or ""] + list(e.get("aliases") or []) + list(e.get("keywords") or [])}
        others_words[e["id"]] = {w for w in words if len(w) > 1}

    offenders: set[str] = set()
    for e in entries:
        for kw in e.get("keywords") or []:
            if len(str(kw)) != 1:
                continue
            for oid, words in others_words.items():
                if oid == e["id"]:
                    continue
                if any(kw in w for w in words):
                    offenders.add(e["id"])
                    break
            else:
                continue
            break
    return offenders


def test_no_new_single_char_offenders():
    """新增的单字违规必须变红（现有 5 条在白名单里，不静默存在）。"""
    offenders = _offending_ids(_entries())
    assert offenders, "一个违规都没算出来 —— 判据写错了（别让它静默失效）"
    unexpected = offenders - SINGLE_CHAR_WHITELIST
    assert not unexpected, f"新增了单字跨条目误命中：{sorted(unexpected)}"


def test_whitelist_entries_are_really_offenders():
    """反向：白名单里的条目必须**真的**还违规 —— 否则白名单腐烂了（与 D12 同形）。"""
    offenders = _offending_ids(_entries())
    stale = SINGLE_CHAR_WHITELIST - offenders
    assert not stale, f"白名单里这些已经不违规了，删掉：{sorted(stale)}"


def test_cake_no_longer_drags_in_egg():
    """本条的正例：说「蛋糕」不该再带出「鸡蛋」。"""
    names = [e.get("name") for e in match_foods("蛋糕")]
    assert names == ["蛋糕"], names


def test_egg_itself_still_matches():
    """别为了去掉误命中，把正常匹配也弄丢。"""
    names = [e.get("name") for e in match_foods("水煮蛋")]
    assert "鸡蛋" in names, names


def test_guard_would_catch_a_reintroduced_bare_char():
    """变异检验：把「蛋」加回 `jidan`，判据必须报它违规 —— 否则判据恒真。"""
    entries = _entries()
    for e in entries:
        if e["id"] == "jidan":
            e["keywords"] = list(e.get("keywords") or []) + ["蛋"]
    assert "jidan" in _offending_ids(entries), "把「蛋」加回去却没被判据抓到 ⇒ 恒真"
