"""体质「就绪闸门」测试：收录 ≠ 可用。

背景（2026-09-17，5→9 型）
--------------------------
把四个新体质加进 `Constitution` 枚举和 `constitution.json` 之后，它们立刻就能被
请求指定——但 `herbs.json` 里还没有任何饮片标注它们，`filter_by_constitution`
会抛 `MissingConstitutionDataError`，用户在界面上一点就是 500。

所以引入**派生闸门** `safety.ready_constitutions()`：某体质可用的充要条件就是
「herbs.json 里至少有 1 味把它标进 `suitable_constitutions`」。
闸门放在两处，缺一不可：

* `main.constitutions`（`/api/constitutions`）—— 管住下拉框里有什么；
* `orchestrator._constitution_of` —— 管住**运行时**，手搓请求指定体质也绕不过。

本文件守的是这三件事：
1. 未就绪的体质不出现在选项里，且被直接指定时返回 **422 而不是 500**；
2. 闸门是**数据派生**的，不是手工开关（补上数据就自动开放，不用翻任何 flag）；
3. 枚举 / `constitution.json` / `docs/constitution-9-types.json` 三处的 id 与顺序一致
   —— 这类漂移一旦发生，症状是「悄悄少一个体质」或「标注全失配」，很难查。

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

# 四型刚进枚举但 herbs.json 尚未标注
NOT_READY_YET = ["yin_deficiency", "blood_stasis", "qi_stagnation", "special_diathesis"]
LEGACY_FIVE = ["balanced", "qi_deficiency", "yang_deficiency", "phlegm_damp", "damp_heat"]


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
def test_legacy_five_are_ready_and_new_four_are_not() -> None:
    """当前状态：5 型就绪，4 型未就绪。

    ⚠️ 四型那条断言会在 **Step 2**（补 herbs.json 标注）之后失效——
    那时改这条测试是**正当的**：它编码的是「数据还没写」这个中间状态，
    不是不变量。真正的不变量由下面几条（派生逻辑 + 双层闸门）守着。
    """
    ready = ready_constitutions()
    for cid in LEGACY_FIVE:
        assert cid in ready, f"{cid} 原有体质应保持就绪"
    for cid in NOT_READY_YET:
        assert cid not in ready, f"{cid} 数据未备齐，不应就绪"


def test_ready_is_derived_from_herbs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """给某味饮片加上标的，它对应的体质立刻出现在集合里 —— 证明是数据派生，不是开关。"""
    catalog = safety.load_herb_catalog()
    target = next(iter(catalog))
    patched = {k: dict(v) for k, v in catalog.items()}
    patched[target]["suitable_constitutions"] = ["yin_deficiency"]
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: patched)

    assert "yin_deficiency" in ready_constitutions()
    # 造出来的数据不该把别的体质捎进去
    assert "blood_stasis" not in ready_constitutions()


def test_only_suitable_counts_not_unsuitable(monkeypatch: pytest.MonkeyPatch) -> None:
    """只有 `suitable_constitutions` 能让体质就绪；`unsuitable_for` 不算。

    这条守的是那个**静默失效**：`unsuitable_for` 是裸字符串列表，
    写进新体质 id 不会报错也不会生效（runtime 永远产不出该 id）。
    若哪天有人把它也当成「数据备齐」的信号，闸门就会放行一个
    `filter_by_constitution` 仍然会抛错的体质 —— 又回到 500。
    """
    catalog = safety.load_herb_catalog()
    target = next(iter(catalog))
    patched = {k: dict(v) for k, v in catalog.items()}
    patched[target]["suitable_constitutions"] = []
    patched[target]["unsuitable_for"] = ["qi_stagnation"]
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: patched)

    assert "qi_stagnation" not in ready_constitutions()


def test_missing_catalog_means_nothing_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """整个 herbs.json 缺失时，没有任何体质可服务（不能假装能收敛）。"""
    monkeypatch.setattr(safety, "load_herb_catalog", lambda: {})
    assert ready_constitutions() == set()


# ============================================================
# 2. 运行时闸门（orchestrator）
# ============================================================
def test_unready_constitution_raises_with_actionable_code() -> None:
    """直接指定未就绪体质 → AnalyzeError(CONSTITUTION_NOT_READY)。

    注意这里**没有传 Key** 也照样拿到体质错误：体质闸门刻意排在凭据校验
    **之前**（orchestrator.analyze 里 `_constitution_of` 早于 `NO_API_KEY`），
    否则用户会先看到"缺 Key"，修好 Key 再撞一次墙。
    """
    from app.services.orchestrator import AnalyzeError, analyze

    with pytest.raises(AnalyzeError) as ei:
        analyze(
            AnalyzeRequest(text="晚上吃了火锅", constitution_override=Constitution.YIN_DEFICIENCY),
            api_key=None,
        )
    assert ei.value.code == "CONSTITUTION_NOT_READY"
    assert "阴虚质" in ei.value.message, "错误文案要给出人话名称，不能只给 id"


def test_ready_constitution_passes_the_gate() -> None:
    """就绪体质要能过闸门。

    用一个必然失败于**下一步**的请求来证明它过关了：没带 Key，所以应报
    `NO_API_KEY` 而不是 `CONSTITUTION_NOT_READY`。若闸门写反，这里会先报体质错误。
    """
    from app.services.orchestrator import AnalyzeError, analyze

    with pytest.raises(AnalyzeError) as ei:
        analyze(
            AnalyzeRequest(text="晚上吃了火锅", constitution_override=Constitution.BALANCED),
            api_key=None,
        )
    assert ei.value.code == "NO_API_KEY"


def test_default_constitution_is_ready() -> None:
    """请求不带体质时落到平和质，而平和质必须始终可用（否则整个服务打不开）。"""
    from app.services.orchestrator import AnalyzeError, analyze

    with pytest.raises(AnalyzeError) as ei:
        analyze(AnalyzeRequest(text="晚上吃了火锅"), api_key=None)
    assert ei.value.code == "NO_API_KEY"


def test_high_risk_branch_outranks_the_gate() -> None:
    """体质闸门必须排在高风险分支**之后**。

    安全提示是"无条件可用"的（高风险分支不调用模型、不花一分钱），
    不该被"数据没备齐"这种配置问题挡在前面——否则一个说了"我怀孕了"的用户
    会因为选了个未就绪体质而看到配置错误，而不是"请先咨询执业医师"。
    这条断言把优先级钉死在测试里，防止以后有人把闸门挪回函数开头。
    """
    from app.services.orchestrator import analyze

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


def test_api_lists_only_ready_constitutions(http_client) -> None:
    """下拉框里只有就绪体质；四型数据没备齐就不该出现。"""
    r = http_client.get("/api/constitutions")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert ids == LEGACY_FIVE, "顺序应与 constitution.json 一致，且不含未就绪体质"
    for cid in NOT_READY_YET:
        assert cid not in ids


def test_api_constitutions_are_labelled(http_client) -> None:
    """返回字段不变（前端与终端都依赖它）。"""
    body = http_client.get("/api/constitutions").json()
    for item in body:
        assert item["label"] == CONSTITUTION_LABELS[item["id"]]
        assert item["one_line"].strip()


def test_override_of_unready_constitution_is_422_not_500(http_client) -> None:
    """绕过 UI 直接指定未就绪体质 → 422（可诊断），不是 500（看起来像崩了）。

    这条是双层闸门的价值所在：只过滤下拉框的话，这里会打到
    `filter_by_constitution` 的 `MissingConstitutionDataError`，
    被 api/analyze.py 的兜底 except 包成 500 INTERNAL_ERROR。
    """
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
