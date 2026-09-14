"""接口与中间结构的唯一真源：请求 / 响应 / Agent 产物全部在这里定义。

改了这里的字段名就等于改了对外契约，必须同步改前端与提示词。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Constitution,
    CookingMethod,
    Flavor,
    MealTime,
    Nature,
)


# ============================================================
# 通用
# ============================================================
class Disclaimer(BaseModel):
    """免责声明。所有业务响应必须携带，前端统一渲染，禁止各自硬编码文案。"""

    version: str = Field(default="v1")
    text: str = Field(
        default=(
            "本内容基于中医饮食养生常识与药食同源食材，仅供日常饮食参考，"
            "不构成医疗建议，也不能替代医师的诊断与治疗。"
            "孕期、哺乳期、经期、儿童、慢性病患者及正在服药者，"
            "请先咨询执业医师或药师。若食用后不适，请立即停用并就医。"
        )
    )
    is_medical_advice: Literal[False] = False


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


# ============================================================
# Agent 1 产物：饮食解析
# ============================================================
class ParsedFood(BaseModel):
    """单个食物条目。"""

    name: str = Field(description="食物名称，如 麻辣烫、冰可乐")
    amount_desc: str = Field(default="未指明", description="份量描述，如 一份、两碗")
    nature: Nature = Field(default=Nature.UNKNOWN, description="寒热属性")
    flavors: list[Flavor] = Field(default_factory=list, description="五味")
    cooking: CookingMethod = Field(default=CookingMethod.UNKNOWN, description="烹饪方式")
    note: str | None = Field(default=None, description="补充说明，如 冰镇、重辣")


class ParsedMeal(BaseModel):
    """Agent 1 的完整输出，也是 Agent 2 的输入。"""

    foods: list[ParsedFood] = Field(default_factory=list)
    meal_time: MealTime = Field(default=MealTime.UNKNOWN)
    overall_nature: Nature = Field(default=Nature.UNKNOWN, description="整餐寒热总评")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertain_items: list[str] = Field(
        default_factory=list, description="未能识别的食物名，前端可提示用户补充"
    )
    summary: str = Field(default="", description="一句话复述，用于前端回显")


# ============================================================
# Agent 2 产物：茶饮推荐
# ============================================================
class HerbInBlend(BaseModel):
    """配方中的单味饮片。"""

    name: str
    amount_g: float = Field(ge=0, description="建议用量（克）")
    nature: Nature = Nature.UNKNOWN
    flavors: list[Flavor] = Field(default_factory=list)
    meridians: list[str] = Field(default_factory=list, description="归经，如 脾、胃")
    role: str = Field(default="", description="在该搭配中的作用，一句话")


class BrewGuide(BaseModel):
    """冲泡说明。"""

    vessel: str = Field(default="保温杯或盖碗")
    water_ml: int = Field(default=400, ge=100, le=2000)
    water_temp_c: int = Field(default=95, ge=40, le=100)
    steps: list[str] = Field(default_factory=list)
    steep_min: int = Field(default=5, ge=1, le=60)
    refill_times: int = Field(default=2, ge=0, le=5)


class Recommendation(BaseModel):
    """单条推荐。"""

    title: str
    herbs: list[HerbInBlend] = Field(default_factory=list)
    brew: BrewGuide = Field(default_factory=BrewGuide)
    fit_reason: str = Field(default="", description="为什么适合该用户与该餐")
    cautions: list[str] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class Basis(BaseModel):
    """推荐依据，用于前端展示与事后归因。"""

    constitution: Constitution
    constitution_label: str
    rule_hits: list[str] = Field(default_factory=list)
    guardrail_applied: list[str] = Field(default_factory=list)


class Meta(BaseModel):
    """耗时与降级信息。"""

    agent1_ms: int | None = None
    agent2_ms: int | None = None
    total_ms: int | None = None
    model: str | None = None
    degraded: bool = Field(default=False, description="是否走了规则兜底")
    degraded_reason: str | None = None


# ============================================================
# 接口请求 / 响应
# ============================================================
class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="用户原始口述")
    meal_time: MealTime | None = None
    constitution_override: Constitution | None = None
    exclude_herbs: list[str] = Field(default_factory=list)
    session_id: str | None = None

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text 不能为空白")
        return v


class AnalyzeResponse(BaseModel):
    request_id: str
    parsed: ParsedMeal
    recommendations: list[Recommendation] = Field(default_factory=list)
    basis: Basis
    disclaimer: Disclaimer = Field(default_factory=Disclaimer)
    meta: Meta = Field(default_factory=Meta)
    user_message: str = Field(default="", description="需要向用户补充说明的话")


class ProfileResponse(BaseModel):
    user_id: str
    constitution: Constitution
    label: str
    source: str = Field(default="manual", description="questionnaire / manual / inferred")
    updated_at: datetime | None = None


class ProfileUpdateRequest(BaseModel):
    constitution: Constitution
    source: str = "manual"
    answers: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    credentials_ok: bool
    herbs_loaded: int
    data_files_ok: bool
    dsh_home: str
    dsh_home_exists: bool
    model: str
    disclaimer_version: str


class CatalogHerb(BaseModel):
    """饮片目录条目，用于 /api/catalog/herbs 与前端"可加料"选择。"""

    id: str
    name: str
    nature: Nature
    flavors: list[Flavor] = Field(default_factory=list)
    meridians: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    max_daily_g: float
    cautions: list[str] = Field(default_factory=list)
    suitable_constitutions: list[Constitution] = Field(default_factory=list)
    brewing: dict[str, Any] = Field(default_factory=dict)
    unsuitable_for: list[str] = Field(default_factory=list)
