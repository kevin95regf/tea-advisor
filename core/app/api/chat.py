"""饮食养生对话 API。

在不改变主分析链路的前提下，恢复旧版的连续对话与多模型选择。
候选原料、公开依据和高风险拦截全部复用新版安全层。
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.multi_provider import (
    MODEL_MAPPING,
    PROVIDERS,
    get_multi_provider_runtime,
    get_provider_for_model,
)
from app.agents.runtime import CredentialError
from app.api.auth import extract_api_key
from app.config import get_settings
from app.domain.enums import CONSTITUTION_LABELS, Constitution
from app.domain.models import EvidenceReference
from app.domain.safety import (
    detect_high_risk,
    filter_by_constitution,
    herb_evidence,
    scan_free_text,
)

router = APIRouter()

SYSTEM_PROMPT = """你是中医饮食养生数字助手「茶小助」。
你只提供日常饮食与药食同源茶饮参考，不诊断、不治疗、不开处方。
语气亲切，回答控制在 200 字以内。
只能从给定候选原料里提及茶饮原料，不得自行扩充。
使用“有助于、适合、可以试试、偏于”等表述，不得作疗效承诺。
遇到孕期、哺乳期、儿童、慢性病、正在服药或明显不适，应建议咨询执业医师。
不要虚构文献、链接、剂量或历史人物原话。"""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    model: str = Field(default="deepseek-flash")
    constitution: Constitution = Field(default=Constitution.BALANCED)
    persona: str = Field(default="", description="旧客户端兼容字段，不改变系统身份")


class ChatResponse(BaseModel):
    reply: str
    model: str
    usage: dict | None = None
    elapsed_ms: int
    remembered_messages: int
    persona: str = "tea_assistant"
    references: list[EvidenceReference] = Field(default_factory=list)
    safety_intercepted: bool = False


def _safe_context(constitution: Constitution) -> tuple[list[str], list[dict]]:
    """返回该体质可用的受限候选及对应公开依据。"""

    candidates = filter_by_constitution(constitution.value, limit=12)
    suitable = [
        item["name"]
        for item in candidates
        if constitution.value in (item.get("suitable_constitutions") or [])
    ]
    refs = herb_evidence(set(suitable), constitution.value)
    return suitable, refs


@router.post("/chat", response_model=ChatResponse, summary="饮食养生连续对话")
async def chat_endpoint(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> ChatResponse:
    if request.messages[-1].role != "user":
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CONVERSATION", "message": "对话最后一条必须是用户消息。"},
        )
    if request.model not in MODEL_MAPPING:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNKNOWN_MODEL", "message": "请选择模型列表中的有效模型。"},
        )

    remembered = request.messages[-20:]
    user_text = remembered[-1].content.strip()
    risks = detect_high_risk(user_text)
    if risks:
        return ChatResponse(
            reply=(
                "你描述的情况涉及需要谨慎处理的人群或症状，本程序不提供个体化茶饮建议。"
                "请先咨询执业医师或药师；如果症状明显或正在加重，请及时就医。"
            ),
            model=request.model,
            elapsed_ms=0,
            remembered_messages=len(remembered),
            safety_intercepted=True,
        )

    api_key = extract_api_key(authorization)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_API_KEY", "message": get_settings().missing_credentials_hint()},
        )

    try:
        candidate_names, evidence_items = _safe_context(request.constitution)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CONSTITUTION_NOT_READY", "message": str(exc)},
        ) from exc

    evidence_context = "\n".join(
        f"- {item['publisher']}《{item['title']}》支持：{'、'.join(item['supports'])}。"
        for item in evidence_items
    )
    system = (
        SYSTEM_PROMPT
        + f"\n当前体质：{CONSTITUTION_LABELS[request.constitution.value]}。"
        + f"\n可用候选原料仅限：{'、'.join(candidate_names) or '无'}。"
        + ("\n公开依据摘要：\n" + evidence_context if evidence_context else "")
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(
        {"role": item.role, "content": item.content.strip()} for item in remembered
    )

    started = time.perf_counter()
    try:
        result = get_multi_provider_runtime().run(
            prompt=user_text,
            messages=messages,
            api_key=api_key,
            model=request.model,
            session_id=f"chat-{uuid.uuid4().hex[:10]}",
        )
    except CredentialError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "API_KEY_REJECTED", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "MODEL_ERROR", "message": str(exc)},
        ) from exc

    guard = scan_free_text(result.text)
    reply = result.text
    intercepted = False
    if not guard.ok:
        intercepted = True
        reply = (
            "模型回复未通过养生内容安全检查，因此没有展示。"
            "你可以换一种日常饮食问题重新询问；涉及治疗或用药请咨询执业医师。"
        )

    mentioned = {name for name in candidate_names if name in reply}
    refs = [
        EvidenceReference(**item)
        for item in herb_evidence(mentioned, request.constitution.value)
    ]
    return ChatResponse(
        reply=reply,
        model=request.model,
        usage=result.usage,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        remembered_messages=len(remembered),
        references=refs,
        safety_intercepted=intercepted,
    )


@router.get("/chat/models", summary="可用对话模型")
async def list_models() -> list[dict[str, str]]:
    return [
        {"id": "deepseek-flash", "name": "DeepSeek Chat", "provider": "DeepSeek", "desc": "快速响应"},
        {"id": "deepseek-v4-pro", "name": "DeepSeek Reasoner", "provider": "DeepSeek", "desc": "深度思考"},
        {"id": "qwen-3.8", "name": "通义千问 Plus", "provider": "阿里云", "desc": "通用对话"},
        {"id": "mimo-v2.5", "name": "MiMo V2.5", "provider": "小米", "desc": "标准模型"},
        {"id": "mimo-v2.5-pro", "name": "MiMo V2.5 Pro", "provider": "小米", "desc": "深度推理"},
        {"id": "hy4", "name": "HY4", "provider": "HY", "desc": "通用对话"},
    ]


# 模型的展示名与用途。**只有展示层用它**：判定"这个模型能不能调"一律看
# multi_provider.MODEL_MAPPING（由 PROVIDERS 生成），这里写错不会让调用出错，
# 只会让界面显示得不好看 —— 未登记的模型回退成模型 ID 本身。
_MODEL_META: dict[str, dict[str, str]] = {
    "deepseek-flash": {"name": "DeepSeek Chat", "desc": "快速响应"},
    "deepseek-v4-pro": {"name": "DeepSeek Reasoner", "desc": "深度思考"},
    "qwen-3.8": {"name": "通义千问 Plus", "desc": "通用对话"},
    "qwen-turbo": {"name": "通义千问 Turbo", "desc": "更快更省"},
    "qwen-max": {"name": "通义千问 Max", "desc": "效果优先"},
    "mimo-v2.5": {"name": "MiMo V2.5", "desc": "标准模型"},
    "mimo-v2.5-pro": {"name": "MiMo V2.5 Pro", "desc": "深度推理"},
    "hy4": {"name": "HY4", "desc": "通用对话"},
}


@router.get("/chat/providers", summary="可用模型供应商")
async def list_providers() -> list[dict]:
    """配置向导第 1 步「选择供应商」用。

    与 `/chat/models` 的分工：那个是扁平模型列表（按策划顺序），
    这个按供应商分组并带上 `base_url`，好让用户在界面上看清**请求到底发去哪儿** ——
    接入第三方模型时这是最关键的一条信息，藏起来等于让人盲填 Key。

    真源是 `multi_provider.PROVIDERS`，所以新增供应商只要改那里，界面自动出现。
    """
    out: list[dict] = []
    for provider_id, info in PROVIDERS.items():
        models = [
            {
                "id": model_id,
                "name": _MODEL_META.get(model_id, {}).get("name", model_id),
                "desc": _MODEL_META.get(model_id, {}).get("desc", ""),
            }
            for model_id in info["models"]
        ]
        out.append(
            {
                "id": provider_id,
                "name": info["name"],
                "base_url": info["base_url"],
                # 默认模型 = 该供应商映射表的第一项，与运行时缺省行为一致
                "default_model": models[0]["id"] if models else "",
                "models": models,
            }
        )
    return out


class ChatTestRequest(BaseModel):
    model: str = Field(default="deepseek-flash", description="前端模型 key，须在 MODEL_MAPPING 内")


class ChatTestResponse(BaseModel):
    ok: bool
    model: str
    provider: str
    provider_name: str
    remote_model: str
    base_url: str
    elapsed_ms: int
    message: str
    usage: dict | None = None


@router.post("/chat/test", response_model=ChatTestResponse, summary="连接测试")
async def chat_test(
    request: ChatTestRequest,
    authorization: str | None = Header(default=None),
) -> ChatTestResponse:
    """配置向导第 4 步「连接测试」：真发一次极小的请求，验证 Key + 模型 + 网络。

    为什么必须真发请求：光校验 Key 格式会给出"通过"，而 Key 失效、模型未开通、
    端点不通这三种情况格式校验一概看不出来 —— 这正是连接测试要排除的东西。

    错误码与 `/chat` 保持一致（NO_API_KEY / API_KEY_REJECTED / UNKNOWN_MODEL /
    MODEL_ERROR），前端已按这套码做过引导，复用即可，不另造一套。
    Key 只经 Authorization 头进函数，不进日志、不进响应体。
    """
    if request.model not in MODEL_MAPPING:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNKNOWN_MODEL", "message": "请选择模型列表中的有效模型。"},
        )

    api_key = extract_api_key(authorization)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_API_KEY", "message": get_settings().missing_credentials_hint()},
        )

    provider_id, base_url, remote_model = get_provider_for_model(request.model)
    provider_name = PROVIDERS.get(provider_id, {}).get("name", provider_id)

    started = time.perf_counter()
    try:
        result = get_multi_provider_runtime().run(
            prompt="连接测试：请只回复 OK。",
            messages=[{"role": "user", "content": "连接测试：请只回复 OK。"}],
            api_key=api_key,
            model=request.model,
            session_id=f"test-{uuid.uuid4().hex[:8]}",
            timeout_s=20.0,
        )
    except CredentialError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "API_KEY_REJECTED", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "MODEL_ERROR", "message": str(exc)},
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return ChatTestResponse(
        ok=bool(result.text),
        model=request.model,
        provider=provider_id,
        provider_name=provider_name,
        remote_model=remote_model,
        base_url=base_url,
        elapsed_ms=elapsed_ms,
        message=f"{provider_name} 连接正常，模型已应答。",
        usage=result.usage,
    )


@router.get("/chat/personas", summary="旧版兼容接口")
async def list_personas() -> list[dict[str, str]]:
    return []
