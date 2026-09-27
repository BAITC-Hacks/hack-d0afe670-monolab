from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import COMPLAINT_LLM_ENABLED, OPENAI_API_KEY, OPENAI_MODEL
from app.models.schemas import ComplaintGenerateRequest

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None

_SYSTEM = """Ты юридический редактор заявлений граждан в органы власти РК.
Улучши текст заявления: формальный тон, точные ссылки на нормы, без эмоций.
Сохрани структуру (шапка, факты, правовое обоснование, ПРОШУ, приложение).
Не выдумывай номера договоров, БИН, даты — используй только данные из исходника.
Верни ТОЛЬКО JSON: {"subject": "...", "target_department": "...", "document_body": "..."}
subject — до 100 символов. document_body — с переносами \\n."""


async def polish_complaint_with_llm(
    body: ComplaintGenerateRequest,
    draft_subject: str,
    draft_target: str,
    draft_document: str,
) -> Optional[dict[str, str]]:
    if not COMPLAINT_LLM_ENABLED or not OPENAI_API_KEY:
        return None

    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    user_payload = {
        "user_info": body.user_info.model_dump() if body.user_info else {},
        "defect_info": body.defect_info.model_dump(),
        "contract_info": body.contract_info.model_dump(),
        "draft": {
            "subject": draft_subject,
            "target_department": draft_target,
            "document_body": draft_document,
        },
    }

    try:
        response = await asyncio.wait_for(
            _client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                max_tokens=2500,
                temperature=0.2,
                response_format={"type": "json_object"},
            ),
            timeout=25.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)
        if not data.get("document_body"):
            return None
        return {
            "subject": str(data.get("subject") or draft_subject)[:100],
            "target_department": str(data.get("target_department") or draft_target),
            "document_body": str(data["document_body"]),
        }
    except Exception as exc:
        logger.warning("complaint LLM polish failed: %s", exc)
        return None
