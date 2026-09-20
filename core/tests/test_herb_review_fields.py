"""E2：饮片条目「逐条审核字段」的派生不变式与负控制。

守的是**静默退化**：字段补上后某天被脚本回写/合并弄丢，而 `_meta.review_status`
（文件级）仍在 —— 文件看着「有审核状态」，实际逐条审核位已经没了。
食物侧（`food_properties.json`）是靠 `patch_food_table.py` 的 `FIELD_ORDER` 强制写入，
饮片侧没有那条管线，所以用本守卫钉住。

按项目纪律：**不写数据快照式断言**（`assert len(herbs) == 34` 这类，加一味就必红，
且分不清「数据坏了」还是「活儿干完了」），只写**结构性**判据 + 负控制，
并断言「守卫至少看到了 N 味」以防恒真。
"""

from __future__ import annotations

import json
from pathlib import Path

HERBS_PATH = Path(__file__).resolve().parent.parent / "data" / "herbs.json"

# E2 补的 4 个字段（拍板 B：位置在 brewing 之后）
REVIEW_FIELDS = ("review_status", "reviewed_by", "reviewed_at", "review_note")

ALLOWED_STATUS = {"pending", "approved", "rejected"}

# 拍板 A：**不补** `reviewed` 布尔 —— 它是食物侧迁移遗留，饮片侧没有任何消费者。
# 出现了就说明有人照着食物侧的表抄了一遍，属静默分叉。
FORBIDDEN_FIELD = "reviewed"


def _load_herbs() -> list[dict]:
    data = json.loads(HERBS_PATH.read_text(encoding="utf-8"))
    return data["herbs"]


def _guard_review_fields(herbs: list[dict]) -> tuple[list[str], int]:
    """逐味检查审核字段。返回 (问题清单, 实际检查到的字段槽数)。

    判据（全部结构性，不比对具体值）：
      1. 4 个字段必须存在（值可以是 null）
      2. `review_status` 必须 ∈ 三态
      3. 状态为 approved / rejected ⇒ 必须能追溯到人（`reviewed_by` + `reviewed_at`）
      4. 状态为 pending ⇒ 不该带 `reviewed_at`（否则是「改了状态忘了清日期」）
      5. 不得出现拍板排除的 `reviewed` 布尔

    第 3 条是本守卫的真实价值：它把「审核状态」与「审核动作留痕」绑在一起，
    使「把 pending 批量改成 approved 却没真的审核」无法静默通过。
    """
    bad: list[str] = []
    checked = 0
    for h in herbs:
        hid = h.get("id", "?")
        for f in REVIEW_FIELDS:
            if f in h:
                checked += 1
            else:
                bad.append(f"{hid} 缺审核字段 {f}")

        status = h.get("review_status")
        if status is not None and status not in ALLOWED_STATUS:
            bad.append(f"{hid} 的 review_status 非法：{status!r}")

        if status in ("approved", "rejected"):
            if not h.get("reviewed_by") or not h.get("reviewed_at"):
                bad.append(f"{hid} 状态为 {status} 却没留 reviewed_by / reviewed_at")

        if status == "pending" and h.get("reviewed_at"):
            bad.append(f"{hid} 状态是 pending 却带着 reviewed_at")

        if FORBIDDEN_FIELD in h:
            bad.append(f"{hid} 出现 {FORBIDDEN_FIELD} 字段（拍板 A：本轮不补）")

    return bad, checked


# ============================================================ 正控（真实数据）
def test_every_herb_has_review_fields() -> None:
    herbs = _load_herbs()

    # 防恒真的下界：守卫必须真的看到了一批饮片，而不是空表上「没报错」
    assert len(herbs) >= 30, f"只读到 {len(herbs)} 味，守卫没覆盖到真实数据"

    bad, checked = _guard_review_fields(herbs)
    assert bad == [], "审核字段缺失或非法：\n" + "\n".join(bad)

    # 每个字段槽都要被数到 —— 防止遍历逻辑被改坏后「恰好没问题」
    assert checked == len(herbs) * len(REVIEW_FIELDS)


# ============================================================ 负控制（人造样本）
def _sample() -> dict:
    """从真实数据取一味做样本：负控制必须建立在真实形态上。"""
    herb = dict(_load_herbs()[0])
    assert set(REVIEW_FIELDS).issubset(herb), "样本本身就不带审核字段，负控制无意义"
    return herb


def test_guard_flags_missing_field() -> None:
    herb = _sample()
    herb.pop("review_note")
    bad, _ = _guard_review_fields([herb])
    assert bad, "删掉一个审核字段却没有报红"


def test_guard_flags_illegal_status() -> None:
    herb = _sample()
    herb["review_status"] = "done"  # 不在三态内
    bad, _ = _guard_review_fields([herb])
    assert bad, "非法 review_status 没有报红"


def test_guard_flags_approved_without_trace() -> None:
    """把 pending 改成 approved 却没留审核人 —— 这是最需要挡住的静默通道。"""
    herb = _sample()
    herb["review_status"] = "approved"
    assert herb["reviewed_by"] is None and herb["reviewed_at"] is None
    bad, _ = _guard_review_fields([herb])
    assert bad, "approved 却无 reviewed_by / reviewed_at，没有报红"


def test_guard_flags_pending_with_date() -> None:
    herb = _sample()
    herb["reviewed_at"] = "2026-09-20"
    bad, _ = _guard_review_fields([herb])
    assert bad, "pending 却带 reviewed_at，没有报红"


def test_guard_flags_forbidden_bool() -> None:
    herb = _sample()
    herb["reviewed"] = True
    bad, _ = _guard_review_fields([herb])
    assert bad, "出现了拍板排除的 reviewed 布尔，没有报红"


def test_guard_negative_controls_are_not_vacuous() -> None:
    """所有负控制样本在「问题清单」为空时不该被误报 —— 反向确认判据不是永久为真。"""
    bad, checked = _guard_review_fields([_sample()])
    assert bad == []
    assert checked == len(REVIEW_FIELDS)
