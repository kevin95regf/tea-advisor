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
class Verification(BaseModel):
    """属性的来源与可信度。

    三层架构的元数据：前端据此决定"要不要打待验证标记"，
    Agent2 据此决定"能不能把这个属性当输入用"。
    """

    source: str = Field(
        default="llm",
        description="rule 硬规则库 / composed 组合推理 / llm 模型推测 / unresolved 无法判定",
    )
    confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    unverified: bool = Field(
        default=True, description="true 表示未经中医食性验证，界面必须标注"
    )
    detail: str | None = Field(default=None, description="判定过程说明，便于排查")


class ParsedFood(BaseModel):
    """单个食物条目。"""

    name: str = Field(description="食物名称，如 麻辣烫、冰可乐")
    amount_desc: str = Field(default="未指明", description="份量描述，如 一份、两碗")
    nature: Nature = Field(default=Nature.UNKNOWN, description="寒热属性")
    flavors: list[Flavor] = Field(default_factory=list, description="五味")
    cooking: CookingMethod = Field(default=CookingMethod.UNKNOWN, description="烹饪方式")
    note: str | None = Field(default=None, description="补充说明，如 冰镇、重辣")
    verification: Verification = Field(default_factory=Verification)


class MealDimension(BaseModel):
    """一个维度（脾胃冲击度 / 湿气生成度）的确定性打分结果。

    分数与档位全部由 ``core/data/diet_signals.json`` 派生，本文件不写死任何阈值；
    ``cap`` 与 ``action_label`` 也来自数据文件，所以两个壳不需要自己维护「/3」或中文标签。
    """

    score: int = Field(default=0, description="加权求和后按 cap 封顶的分数")
    cap: int = Field(default=3, description="封顶值，来自数据文件；壳里不要写死")
    action: str = Field(default="none", description="机器可读档位，如 protect_stomach")
    action_label: str = Field(default="", description="档位中文短语，供两个壳直接渲染")
    signals: list[str] = Field(
        default_factory=list, description="本次参与计分的信号中文标签（去重）"
    )
    evidence_floor: str = Field(
        default="full", description="本次计分依赖的最弱依据：full/partial/clinical/none"
    )
    basis: str = Field(default="", description="依据说明")


class MealConflict(BaseModel):
    """寒热错杂判定。

    三个字段的值必须**原样**来自 ``nature_math.detect_nature_conflict``：
    组装层不得另判一套（测试用派生不变式钉住）。
    """

    conflict: bool = False
    heat_side: list[str] = Field(default_factory=list, description="偏热一侧的条目名")
    cold_side: list[str] = Field(default_factory=list, description="偏寒一侧的条目名")


class MealSignals(BaseModel):
    """整餐的确定性信号汇总，挂在 ``ParsedMeal.signals`` 上。

    三个子块都可能为 None（维度定义缺失时不臆造结论）。
    """

    impact: MealDimension | None = None
    dampness: MealDimension | None = None
    conflict: MealConflict | None = None


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
    signals: MealSignals | None = Field(
        default=None,
        description=(
            "整餐确定性信号（冲击度/湿气度/寒热错杂）。"
            "None 表示未计算——既有构造方不传即保持旧行为。"
        ),
    )


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


class EvidenceReference(BaseModel):
    """本次推荐用到的原料对应的**公开依据**。

    ``supports`` 只表示该来源明确提到了这些原料与当前方向，
    **不代表来源支持本程序生成的具体搭配、克数或个体化使用**。

    ``note`` 携带来源自身的注意事项（如药典引用的是 2020 版、已被 2025 版废止），
    属于「必须跟着依据走」的诚实边界，前端不得省略。
    """

    id: str = Field(description="来源 id，对应 herb_evidence_sources.json 的 source_registry 键")
    title: str = Field(description="来源标题")
    publisher: str = Field(description="发布方")
    url: str = Field(description="原文链接")
    supports: list[str] = Field(default_factory=list, description="该来源点名的原料（项目正名）")
    note: str = Field(default="", description="来源自身的注意事项")


class Basis(BaseModel):
    """推荐依据，用于前端展示与事后归因。"""

    constitution: Constitution
    constitution_label: str
    rule_hits: list[str] = Field(default_factory=list)
    guardrail_applied: list[str] = Field(default_factory=list)
    references: list[EvidenceReference] = Field(
        default_factory=list,
        description="本次实际推荐原料对应的公开依据（只含命中本次原料的来源）",
    )


class Meta(BaseModel):
    """耗时与降级信息。"""

    agent1_ms: int | None = None
    agent2_ms: int | None = None
    total_ms: int | None = None
    model: str | None = None
    degraded: bool = Field(default=False, description="是否走了规则兜底")
    degraded_reason: str | None = None

    # --- 凭据与后端来源 ---
    # key_source 让前端能区分"本次用了你填的 Key"与"本次根本没调用模型"
    # （后者是高风险人群分支，不花钱）。本项目只用调用方提供的 Key，
    # 不存在"服务端内置 Key"这回事。
    key_source: Literal["user", "not_used"] = Field(
        default="user",
        description=(
            "user = 本次用了调用方提供的 Key；"
            "not_used = 本次未调用模型（如高风险人群分支）"
        ),
    )
    backend: str | None = Field(
        default=None, description="Agent 运行时后端：direct 直连官方 API / dsh 子进程"
    )


# ============================================================
# 接口请求 / 响应
# ============================================================
class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="用户原始口述")
    meal_time: MealTime | None = None
    constitution_override: Constitution | None = None
    exclude_herbs: list[str] = Field(default_factory=list)
    session_id: str | None = None
    avoid_constitutions: list[Constitution] = Field(
        default_factory=list,
        description=(
            "兼体质屏蔽集（B2 接入）：这些体质标为「不宜」的饮片一并排除，"
            "但**不改变收敛方向** —— 方向仍由 constitution_override 唯一决定。"
            "默认空 ⇒ 与既有调用方行为完全一致。"
        ),
    )

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
    herbs_loaded: int
    data_files_ok: bool
    dsh_home: str
    dsh_home_exists: bool
    model: str
    disclaimer_version: str

    # 前端据此决定怎么提示用户。刻意没有 credentials_ok ——
    # 本项目不使用服务端内置 Key，"服务端有没有 Key"不是一个有意义的状态。
    backend: str = Field(default="direct", description="Agent 后端：direct / dsh")
    user_key_supported: bool = Field(
        default=True, description="是否支持用户自带 API Key（dsh 后端不支持）"
    )


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
