"""体质「就绪闸门」测试：收录 ≠ 可用。

背景（2026-09-17，5→9 型）
--------------------------
Step 1 把四个新体质加进 `Constitution` 枚举和 `constitution.json`，同时引入**派生闸门**
`safety.ready_constitutions()` —— 某体质可用的充要条件是「herbs.json 里至少有 1 味把它
标进 `suitable_constitutions`」。闸门放在两处，缺一不可：

* `main.constitutions`（`/api/constitutions`）—— 管住下拉框里有什么；
* `orchestrator._constitution_of` —— 管住**运行时**，手搓请求指定体质也绕不过。

Step 2（2026-09-17）补完 herbs.json 的 10 格标注后，**四型已全部就绪**。闸门因此从
「挡住这四型」变成「挡住**将来任何**新增但没补数据的体质」。

⚠️ 这次升级逼出了一个测试写法上的坑，别再踩回去
------------------------------------------------
Step 1 阶段，「未就绪体质」是一种**数据状态**（枚举里有、herbs.json 里没有），于是当时
直接拿 `yin_deficiency` 当未就绪样本是能测的。数据补齐之后，任何「拿某个具体体质当
未就绪样本」的测试都会**静默失效** —— 它测的是数据现状，不是闸门逻辑，红了绿了都
说明不了闸门还在不在。

所以本文件现在一律用 `monkeypatch` **现场造**一个未就绪体质。判据：如果你要验证的行为
在数据补齐前后都该成立，就不能依赖「哪一型现在没数据」。

本文件守四件事：
1. 九型全部就绪；且就绪是**数据派生**的，不是手工开关；
2. 未就绪的体质不出现在选项里，被直接指定时给 **422 而不是 500**；
3. 闸门顺序：高风险分支 > 体质闸门 > 凭据校验；
4. 枚举 / constitution.json / docs/constitution-9-types.json 三处 id 与顺序一致。

全部离线运行，不调用任何网络接口、不需要 API Key。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain import safety
from app.domain.enums import CONSTITUTION_LABELS, Constitution
from app.domain.models import AnalyzeRequest
from app.domain.safety import ready_constitutions

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
PROJECT_CONSTITUTIONS = CORE_DIR / "data" / "constitution.json"
REF_PATH = PROJECT_ROOT / "docs" / "constitution-9-types.json"

# 国标九型的完整顺序（= 枚举顺序 = constitution.json 顺序）
ALL_NINE = [
    "balanced",
    "qi_deficiency",
    "yang_deficiency",
    "yin_deficiency",
    "phlegm_damp",
    "damp_heat",
    "blood_stasis",
    "qi_stagnation",
    "special_diathesis",
]
LEGACY_FIVE = ["balanced", "qi_deficiency", "yang_deficiency", "phlegm_damp", "damp_heat"]
NEW_FOUR = ["yin_deficiency", "blood_stasis", "qi_stagnation", "special_diathesis"]


# ============================================================
# 0. 造未就绪样本的工具（本文件的写法核心）
# ============================================================
@pytest.fixture(scope="module")
def catalog_snapshot() -> dict[str, dict]:
    """真实 catalog 的一份副本，**在 monkeypatch 之前**取好。

    为什么要先取：下面几条测试会把 `safety.load_herb_catalog` 换成"改造过的 catalog"。
    如果改造函数自己又去调 `load_herb_catalog()`，就会递归到那个被替换的实现上
    （`RecursionError`，踩过一次）。所以快照与改造必须分成两步。
    """
    return {k: {**v} for k, v in safety.load_herb_catalog().items()}


def _without_suitable(catalog: dict[str, dict], cid: str) -> dict[str, dict]:
    """副本：抹掉任何饮片对 `cid` 的 suitable 标注 —— 该体质因此未就绪。"""
    patched = {k: {**v} for k, v in catalog.items()}
    for entry in patched.values():
        entry["suitable_constitutions"] = [
            c for c in (entry.get("suitable_constitutions") or []) if c != cid
        ]
    return patched


def _without_any_suitable(catalog: dict[str, dict]) -> dict[str, dict]:
    """副本：清空所有 suitable 标注 —— 没有任何体质就绪。"""
    patched = {k: {**v} for k, v in catalog.items()}
    for entry in patched.values():
        entry["suitable_constitutions"] = []
    return patched


@pytest.fixture(scope="module")
def project_ids() -> list[str]:
    raw = json.loads(PROJECT_CONSTITUTIONS.read_text(encoding="utf-8"))
    return [c["id"] for c in raw["constitutions"]]


@pytest.fixture(scope="module")
def ref_ids() -> list[str]:
    raw = json.loads(REF_PATH.read_text(encoding="utf-8"))
    return [c["id"] for c in raw["constitutions"]]


# ============================================================
# 1. 闸门本身
# ============================================================
def test_all_nine_constitutions_are_ready() -> None:
    """九型数据都已备齐 —— 这是 Step 2 的验收标准。

    注意它编码的是一个**事实**（数据齐了），不是不变量：哪天它红了，
    先查是不是有人把 herbs.json 的标注删了，**而不是**急着改这条测试。
    """
    missing = set(ALL_NINE) - ready_constitutions()
    assert not missing, f"这些体质本该就绪却缺 suitable 数据：{sorted(missing)}"


def test_legacy_five_are_still_ready() -> None:
    """原有 5 型不许因为这次改动变成未就绪（闸门写反也关不掉它们）。"""
    missing = set(LEGACY_FIVE) - ready_constitutions()
    assert not missing, f"这几种原有体质不应变成未就绪：{sorted(missing)}"


def test_ready_is_derived_from_herbs_json(
    monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """就绪集合**完全由 herbs.json 派生**：清空全部标注 → 一型都不就绪。

    这条是「没有手工开关」的证明：不给数据就一型都不可用，补上一味就立刻可用，
    中间没有任何 flag 可以漏翻。
    """
    patched = _without_any_suitable(catalog_snapshot)
    target = next(iter(patched))
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: patched)

    assert ready_constitutions() == set(), "没有任何 suitable 标注时不该有体质就绪"

    patched[target]["suitable_constitutions"] = ["yin_deficiency"]
    assert ready_constitutions() == {"yin_deficiency"}, "补上一味标注就应立刻就绪"


def test_only_suitable_counts_not_unsuitable(
    monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """只有 `suitable_constitutions` 能让体质就绪；`unsuitable_for` 不算。

    守的是那个**静默失效**：`unsuitable_for` 是裸字符串列表，写进新体质 id
    不会报错也不会生效（runtime 永远产不出该 id）。若哪天有人把它也当成
    「数据备齐」的信号，闸门就会放行一个 `filter_by_constitution` 仍会抛错的体质
    —— 用户一点又回到 500。
    """
    patched = _without_any_suitable(catalog_snapshot)
    for entry in patched.values():
        entry["unsuitable_for"] = []
    target = next(iter(patched))
    patched[target]["unsuitable_for"] = ["qi_stagnation"]
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: patched)

    assert ready_constitutions() == set()


def test_missing_catalog_means_nothing_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """整个 herbs.json 缺失时，没有任何体质可服务（不能假装能收敛）。"""
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: {})
    assert ready_constitutions() == set()


# ============================================================
# 2. 运行时闸门（orchestrator）
# ============================================================
def test_unready_constitution_raises_with_actionable_code(
    monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """直接指定未就绪体质 → AnalyzeError(CONSTITUTION_NOT_READY)。

    ⚠️ 未就绪样本是**现场造**的：数据补齐后 `yin_deficiency` 已就绪，
    再拿它当样本这条测试就会失效 —— 而它以前正是这么写的。

    另外注意这里**没有传 Key** 也照样拿到体质错误：体质闸门刻意排在凭据校验
    **之前**（`analyze` 里 `_constitution_of` 早于 `NO_API_KEY`），
    否则用户会先看到"缺 Key"，修好 Key 再撞一次墙。
    """
    from app.services.orchestrator import AnalyzeError, analyze

    monkeypatch.setattr(
        safety, "load_herb_catalog", lambda: _without_suitable(catalog_snapshot, "yin_deficiency")
    )

    with pytest.raises(AnalyzeError) as ei:
        analyze(
            AnalyzeRequest(text="晚上吃了火锅", constitution_override=Constitution.YIN_DEFICIENCY),
            api_key=None,
        )
    assert ei.value.code == "CONSTITUTION_NOT_READY"
    assert "阴虚质" in ei.value.message, "错误文案要给出人话名称，不能只给 id"


def test_unready_constitution_in_avoid_is_also_blocked(
    monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """屏蔽集里的体质**同样**要过就绪闸门（B2 接入 · 接入点 ①）。

    主导体质备齐、屏蔽集里某一型没备齐是完全可能的：屏蔽靠 `unsuitable_for`，
    而就绪判据看的是 `suitable_constitutions`，两者不是同一份数据。
    放过去就会出现「这个体质没数据、却照样拿它来屏蔽饮片」的静默不一致。
    """
    from app.services.orchestrator import AnalyzeError, analyze

    monkeypatch.setattr(
        safety, "load_herb_catalog", lambda: _without_suitable(catalog_snapshot, "yin_deficiency")
    )

    with pytest.raises(AnalyzeError) as ei:
        analyze(
            AnalyzeRequest(
                text="晚上吃了火锅",
                constitution_override=Constitution.QI_DEFICIENCY,  # 主导体质是就绪的
                avoid_constitutions=[Constitution.YIN_DEFICIENCY],
            ),
            api_key=None,
        )
    assert ei.value.code == "CONSTITUTION_NOT_READY"
    assert "阴虚质" in ei.value.message

    # 负控制：同一个请求不带 avoid 时能过闸门（停在 NO_API_KEY）——
    # 证明上面那条错误确实来自屏蔽集，不是主导体质本身没备齐
    with pytest.raises(AnalyzeError) as ok:
        analyze(
            AnalyzeRequest(text="晚上吃了火锅", constitution_override=Constitution.QI_DEFICIENCY),
            api_key=None,
        )
    assert ok.value.code == "NO_API_KEY"


def test_new_four_constitutions_pass_the_gate() -> None:
    """Step 2 的直接验收：四个新体质都能过闸门。

    用一个必然失败于**下一步**的请求来证明它们过关了：没带 Key，所以应报
    `NO_API_KEY` 而不是 `CONSTITUTION_NOT_READY`。若闸门仍把四型挡着，这里会先报体质错误。
    """
    from app.services.orchestrator import AnalyzeError, analyze

    for cid in NEW_FOUR:
        with pytest.raises(AnalyzeError) as ei:
            analyze(
                AnalyzeRequest(text="晚上吃了火锅", constitution_override=Constitution(cid)),
                api_key=None,
            )
        assert ei.value.code == "NO_API_KEY", f"{cid} 应已就绪，不该报体质错误"


def test_default_constitution_is_ready() -> None:
    """请求不带体质时落到平和质，而平和质必须始终可用（否则整个服务打不开）。"""
    from app.services.orchestrator import AnalyzeError, analyze

    with pytest.raises(AnalyzeError) as ei:
        analyze(AnalyzeRequest(text="晚上吃了火锅"), api_key=None)
    assert ei.value.code == "NO_API_KEY"


def test_high_risk_branch_outranks_the_gate(
    monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """体质闸门必须排在高风险分支**之后**。

    安全提示是"无条件可用"的（高风险分支不调用模型、不花一分钱），
    不该被"数据没备齐"这种配置问题挡在前面——否则一个说了"我怀孕了"的用户
    会因为选了个未就绪体质而看到配置错误，而不是"请先咨询执业医师"。

    这条断言把优先级钉死在测试里，防止以后有人把闸门挪回函数开头。
    未就绪样本同样是现场造的（原因见文件头）。
    """
    from app.services.orchestrator import analyze

    monkeypatch.setattr(
        safety, "load_herb_catalog", lambda: _without_suitable(catalog_snapshot, "yin_deficiency")
    )

    resp = analyze(
        AnalyzeRequest(
            text="我怀孕了，晚上吃了火锅",
            constitution_override=Constitution.YIN_DEFICIENCY,
        ),
        api_key=None,  # 连 Key 都没有，也要能拿到安全提示
    )
    assert resp.recommendations == []
    assert resp.meta.degraded is True
    assert resp.meta.degraded_reason == "high_risk_group"
    assert "咨询执业医师" in (resp.user_message or "")


# ============================================================
# 3. HTTP 层：422 而不是 500
# ============================================================
@pytest.fixture
def http_client():
    pytest.importorskip("fastapi", reason="HTTP 层测试需要 [web] extra")
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_api_lists_all_nine_constitutions(http_client) -> None:
    """四型数据备齐后，下拉框自动补齐到 9 型，顺序与 constitution.json 一致。"""
    r = http_client.get("/api/constitutions")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert ids == ALL_NINE, "顺序应与 constitution.json 一致，且九型齐全"


def test_api_hides_a_constitution_that_lost_its_data(
    http_client, monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """数据被拿掉，它就立刻从选项里消失 —— 闸门是活的，不是一次性快照。"""
    monkeypatch.setattr(
        safety, "load_herb_catalog", lambda: _without_suitable(catalog_snapshot, "yin_deficiency")
    )
    ids = [item["id"] for item in http_client.get("/api/constitutions").json()]
    assert "yin_deficiency" not in ids
    assert ids == [c for c in ALL_NINE if c != "yin_deficiency"]


def test_api_constitutions_are_labelled(http_client) -> None:
    """返回字段不变（前端与终端都依赖它）。"""
    body = http_client.get("/api/constitutions").json()
    for item in body:
        assert item["label"] == CONSTITUTION_LABELS[item["id"]]
        assert item["one_line"].strip()


def test_override_of_unready_constitution_is_422_not_500(
    http_client, monkeypatch: pytest.MonkeyPatch, catalog_snapshot: dict[str, dict]
) -> None:
    """绕过 UI 直接指定未就绪体质 → 422（可诊断），不是 500（看起来像崩了）。

    这条是双层闸门的价值所在：只过滤下拉框的话，这里会打到
    `filter_by_constitution` 的 `MissingConstitutionDataError`，
    被 api/analyze.py 的兜底 except 包成 500 INTERNAL_ERROR。
    """
    monkeypatch.setattr(
        safety, "load_herb_catalog", lambda: _without_suitable(catalog_snapshot, "yin_deficiency")
    )
    r = http_client.post(
        "/api/analyze",
        json={"text": "晚上吃了火锅", "constitution_override": "yin_deficiency"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "CONSTITUTION_NOT_READY"


def test_unknown_constitution_id_is_rejected_by_schema(http_client) -> None:
    """枚举里没有的 id 由 Pydantic 挡下（422），不会走到编排层。

    ⚠️ 这里的 422 与上一条的 422 **形状不同**，别搞混：
    * 枚举外 id → FastAPI/Pydantic 的请求校验错误，`detail` 是**数组**；
    * 枚举内但未就绪 → 我们自己的 `{"code": ..., "message": ...}`，`detail` 是**字典**。
    前端若要提示用户，只能依赖后者；前者是开发期错误。
    """
    r = http_client.post(
        "/api/analyze",
        json={"text": "晚上吃了火锅", "constitution_override": "no_such_type"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list), "枚举外 id 应由请求校验拦下，而不是走我们的闸门"
    assert "no_such_type" in r.text


# ============================================================
# 4. 三处 id 与顺序一致性（防漂移）
# ============================================================
def test_enum_matches_constitution_json_ids_and_order(project_ids) -> None:
    """枚举顺序 == constitution.json 顺序。国标顺序是有人读的展示顺序。"""
    assert project_ids == [c.value for c in Constitution]


def test_enum_matches_reference_json_ids_and_order(ref_ids) -> None:
    """枚举 / constitution.json / 9-types.json 三处 id 必须完全一致。

    这三份数据由三个不同的人（或时刻）维护，任何一处改了 id 或调了顺序，
    症状都是**静默的**：herbs.json 的标注失配、下拉框少一项、文档对不上号。
    这里用一个断言把三者钉死。
    """
    assert ref_ids == [c.value for c in Constitution]


def test_labels_cover_every_member() -> None:
    """每个枚举成员都要有中文标签，否则界面会显示裸 id。"""
    assert set(CONSTITUTION_LABELS) == {c.value for c in Constitution}
