"""LLM wrapper: ChatOpenAI + hỗ trợ `reasoning_content` của các model "thinking".

Các model suy luận (DeepSeek-R1/V4 thinking, Qwen3...) trả thêm trường
`reasoning_content` trong response và đòi hỏi nó PHẢI được gửi lại ở các lượt
sau (đặc biệt quanh tool-call). `ChatOpenAI` bản chuẩn không trích xuất cũng
không gửi lại trường này (xem comment trong langchain_openai/chat_models/base.py)
nên provider trả 400: "reasoning_content is required for thinking tool-call history".

Subclass dưới đây vá đúng 2 chỗ đó, giữ nguyên mọi hành vi khác — tức là không
cần tắt thinking mode, cứ đi thẳng chuẩn OpenAI-compatible.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class ThinkingChatOpenAI(ChatOpenAI):
    """ChatOpenAI có pass-through `reasoning_content` (nhận về + gửi lại)."""

    def _convert_chunk_to_generation_chunk(
        self, chunk: Any, default_chunk_class: Any, base_generation_info: Any
    ):
        """Bản chuẩn bỏ qua `reasoning_content` trong delta khi stream — giữ lại nó."""
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None
        choices = chunk.get("choices") or []
        if not choices:
            return generation_chunk
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content")
        if reasoning and isinstance(generation_chunk.message, AIMessageChunk):
            existing = generation_chunk.message.additional_kwargs.get("reasoning_content", "")
            generation_chunk.message.additional_kwargs["reasoning_content"] = existing + reasoning
        return generation_chunk

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):
        result = super()._create_chat_result(response, generation_info)
        try:
            raw = (
                response
                if isinstance(response, dict)
                else response.model_dump(warnings=False)
            )
        except Exception:  # noqa: BLE001
            # Payload lạ từ provider: bỏ qua reasoning, không chặn flow chính
            logger.debug(
                "reasoning_content extraction skipped: unexpected response shape",
                exc_info=True,
            )
            return result
        for choice, gen in zip(raw.get("choices") or [], result.generations, strict=False):
            reasoning = (choice.get("message") or {}).get("reasoning_content")
            if reasoning:
                gen.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            return payload  # responses API hoặc payload lạ — không đụng vào
        originals = self._convert_input(input_).to_messages()
        for raw_msg, orig in zip(raw_messages, originals, strict=False):
            if not isinstance(orig, AIMessage) or not isinstance(raw_msg, dict):
                continue
            reasoning = orig.additional_kwargs.get("reasoning_content")
            if reasoning:
                raw_msg["reasoning_content"] = reasoning
        return payload
