"""家用食疗汤模板：数据、food/herb 组件校验、只读工具函数。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parent.parent
DATA = CORE / "data"

EXPECTED_FIVE = {
    "yiner_lianzi_baihe",
    "qizao_jitang",
    "shenqi_dazao",
    "qingbuliang_wl",
    "shanzha_maiya",
}


@pytest.fixture(scope="module")
def herbs_by_id():
    herbs = json.loads((DATA / "herbs.json").read_text(encoding="utf-8"))["herbs"]
    return {h["id"]: h for h in herbs}


@pytest.fixture(scope="module")
def food_ids():
    raw = json.loads((DATA / "food_properties.json").read_text(encoding="utf-8"))
    ids: set[str] = set()
    foods = raw.get("foods")
    if isinstance(foods, list):
        for item in foods:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
    tea = raw.get("tea_drinks")
    if isinstance(tea, dict):
        for item in tea.get("items") or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
    return ids


@pytest.fixture(scope="module")
def soup_payload():
    path = DATA / "soup_templates.json"
    assert path.is_file(), "soup_templates.json 必须存在"
    return json.loads(path.read_text(encoding="utf-8"))


def test_soup_templates_file_and_kind(soup_payload):
    assert soup_payload.get("_meta", {}).get("kind_constraint") == "food_therapy_only"
    templates = soup_payload["templates"]
    assert len(templates) >= 7
    ids = {t["id"] for t in templates}
    assert "sishen_tang" in ids and "jiangzao_cha" in ids
    assert EXPECTED_FIVE <= ids
    for t in templates:
        assert t["kind"] == "food_therapy", t["id"]
        assert t.get("review_status") == "pending"
        assert isinstance(t.get("kitchen_amount_hint"), str) and t["kitchen_amount_hint"].strip()
        assert isinstance(t.get("components"), list) and t["components"]


def test_soup_template_components_herb_or_food(soup_payload, herbs_by_id, food_ids):
    for t in soup_payload["templates"]:
        for c in t["components"]:
            has_herb = "herb_id" in c and c["herb_id"] is not None
            has_food = "food_id" in c and c["food_id"] is not None
            assert has_herb != has_food, f"{t['id']} 必须二选一: {c}"
            assert c.get("role") == "ingredient"
            if has_herb:
                assert c["herb_id"] in herbs_by_id, f"{t['id']} herb {c['herb_id']}"
            else:
                assert c["food_id"] in food_ids, f"{t['id']} food {c['food_id']}"


def test_five_templates_expected_components(soup_payload):
    by_id = {t["id"]: t for t in soup_payload["templates"]}

    def ids(tid: str) -> tuple[set[str], set[str]]:
        herbs, foods = set(), set()
        for c in by_id[tid]["components"]:
            if "herb_id" in c:
                herbs.add(c["herb_id"])
            if "food_id" in c:
                foods.add(c["food_id"])
        return herbs, foods

    h, f = ids("yiner_lianzi_baihe")
    assert h == {"lianzi", "baihe"} and f == {"yiner"}

    h, f = ids("qizao_jitang")
    assert h == {"huangqi", "hongzao"} and f == {"jirou"}
    assert "dangshen" not in h  # 可选不强制

    h, f = ids("shenqi_dazao")
    assert h == {"huangqi", "dangshen", "hongzao"} and not f

    h, f = ids("qingbuliang_wl")
    assert h == {"yuzhu", "maidong", "baihe", "lianzi", "shanyao"} and not f

    h, f = ids("shanzha_maiya")
    assert h == {"shanzha", "maiya"} and not f
    cautions = " ".join(by_id["shanzha_maiya"]["cautions"])
    assert "哺乳" in cautions and ("孕" in cautions or "孕妇" in cautions)
    assert "回乳" in cautions

    qizao_text = json.dumps(by_id["qizao_jitang"], ensure_ascii=False)
    assert "补中益气" in qizao_text  # caution 禁挂
    assert by_id["qizao_jitang"]["display_name"] != "补中益气汤"


def test_soup_templates_loader_and_tools():
    from app.services.soup_templates import (
        SoupTemplateNotFound,
        clear_soup_templates_cache,
        get_soup_template,
        list_food_therapy_templates,
        list_soup_templates,
        load_soup_templates,
    )

    clear_soup_templates_cache()
    data = load_soup_templates()
    listed = list_food_therapy_templates()
    tools = list_soup_templates()
    assert len(listed) == len(data["templates"]) == len(tools)
    assert len(tools) >= 7
    assert all(t["kind"] == "food_therapy" for t in tools)

    approved_only = list_soup_templates(include_pending=False)
    assert approved_only == []  # 当前全 pending

    one = get_soup_template("sishen_tang")
    assert one["id"] == "sishen_tang"
    assert one["_query_meta"]["auto_recommend_allowed"] is False
    assert "pending" in one["_query_meta"]["disclaimer"]

    with pytest.raises(SoupTemplateNotFound):
        get_soup_template("not_a_real_formula")


def test_tool_registry_stub_resolves_soup_tools():
    from app.agents.tool_registry_stub import iter_tool_specs, resolve_tool

    names = {s["name"] for s in iter_tool_specs()}
    assert "list_soup_templates" in names and "get_soup_template" in names
    lst = resolve_tool("list_soup_templates")
    get = resolve_tool("get_soup_template")
    assert callable(lst) and callable(get)
    assert len(lst()) >= 7
    assert get("jiangzao_cha")["display_name"] == "姜枣茶"
    assert resolve_tool("no_such_tool") is None


@pytest.mark.parametrize(
    "comp",
    [
        {"food_id": "__no_such_food__", "role": "ingredient"},
        {"herb_id": "__no_such_herb__", "role": "ingredient"},
        {"herb_id": "lianzi", "food_id": "yiner", "role": "ingredient"},
        {"role": "ingredient"},
        {"herb_id": "lianzi", "role": "jun"},
    ],
)
def test_validator_rejects_bad_components(comp):
    """负控制：未知 food_id/herb_id、二者并存/全缺、非 ingredient 角色都必须被拒。"""
    from app.services.soup_templates import SoupTemplatesError, validate_soup_templates_payload

    payload = {
        "templates": [
            {
                "id": "bad",
                "kind": "food_therapy",
                "review_status": "pending",
                "kitchen_amount_hint": "x",
                "components": [comp],
            }
        ]
    }
    with pytest.raises(SoupTemplatesError):
        validate_soup_templates_payload(payload)
