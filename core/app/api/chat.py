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

from app.agents.multi_provider import MODEL_MAPPING, get_multi_provider_runtime
from app.agents.runtime import CredentialError
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

    api_key = ""
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:].strip()
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_API_KEY", "message": "缺少 API Key，请先打开 API 设置填写。"},
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


@router.get("/chat/personas", summary="旧版兼容接口")
async def list_personas() -> list[dict[str, str]]:
    return []
