"""药物资料不得进入饮食推荐链路的源码守卫。"""

from __future__ import annotations

from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parents[1]
FORBIDDEN_PATHS = (
    CORE_DIR / "app" / "domain" / "safety.py",
    CORE_DIR / "app" / "services" / "food_lookup.py",
    CORE_DIR / "app" / "services" / "matcher.py",
    CORE_DIR / "app" / "services" / "orchestrator.py",
    *sorted((CORE_DIR / "app" / "agents" / "prompts").glob("*.md")),
)
FORBIDDEN_MARKERS = ("medication_reference", "constitution_medication")


def _assert_medication_isolated(sources: dict[str, str]) -> None:
    violations = {
        name: marker
        for name, source in sources.items()
        for marker in FORBIDDEN_MARKERS
        if marker in source
    }
    assert not violations, f"药物资料进入了饮食推荐链路：{violations}"


def test_medication_reference_stays_out_of_recommendation_paths() -> None:
    sources = {
        path.relative_to(CORE_DIR).as_posix(): path.read_text(encoding="utf-8")
        for path in FORBIDDEN_PATHS
    }
    _assert_medication_isolated(sources)


def test_medication_isolation_guard_has_a_negative_control() -> None:
    with pytest.raises(AssertionError, match="药物资料进入了饮食推荐链路"):
        _assert_medication_isolated(
            {"app/services/fake.py": "from app.services import medication_reference"}
        )
