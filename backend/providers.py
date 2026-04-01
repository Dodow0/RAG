"""
providers.py — Embedding & Generation 客户端封装。

两个类都通过 OpenAI Python SDK 的 base_url 参数对接任意兼容接口，
只需在 config.py（或环境变量）中切换 URL + KEY + MODEL 即可。
"""

from __future__ import annotations

import logging
from openai import OpenAI
from config import (
    EMBED_BASE_URL, EMBED_API_KEY, EMBED_MODEL, EMBED_BATCH,
    GEN_BASE_URL, GEN_API_KEY, GEN_MODEL, GEN_MAX_TOKENS, GEN_TEMPERATURE,
)

log = logging.getLogger("rag.providers")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Embedding Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EmbeddingClient:
    """
    通用 Embedding 客户端，兼容任何实现了 OpenAI /v1/embeddings 接口的服务。

    用法：
        client = EmbeddingClient()
        vectors = client.embed(["文本一", "文本二"])
    """

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=EMBED_API_KEY or "no-key",   # 本地服务（如 Ollama）无需真实 key
            base_url=EMBED_BASE_URL,
        )
        self.model = EMBED_MODEL
        log.info(
            "EmbeddingClient  base_url=%s  model=%s  batch=%d",
            EMBED_BASE_URL, EMBED_MODEL, EMBED_BATCH,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        批量生成向量，自动分批（每批 EMBED_BATCH 条）。
        换行符替换为空格，防止部分 API 报错。
        """
        cleaned = [t.replace("\n", " ") for t in texts]
        all_vectors: list[list[float]] = []

        for i in range(0, len(cleaned), EMBED_BATCH):
            batch = cleaned[i : i + EMBED_BATCH]
            response = self._client.embeddings.create(model=self.model, input=batch)
            # 按 index 排序确保顺序与输入一致
            all_vectors.extend(
                item.embedding
                for item in sorted(response.data, key=lambda x: x.index)
            )

        return all_vectors

    def embed_one(self, text: str) -> list[float]:
        """便捷方法：单条文本向量化。"""
        return self.embed([text])[0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Generation Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# RAG 系统提示词（可按需修改）
_SYSTEM_PROMPT = """\
你是一个专业的知识库问答助手。
请严格基于用户提供的参考资料回答问题，不要编造资料中没有的内容。
如果资料不足以回答问题，请如实说明。
回答时请结构清晰、语言简洁。\
"""


class GenerationClient:
    """
    通用生成客户端，兼容任何实现了 OpenAI /v1/chat/completions 接口的服务。

    用法：
        client = GenerationClient()
        answer = client.generate(question="...", context_chunks=[...])
    """

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=GEN_API_KEY or "no-key",
            base_url=GEN_BASE_URL,
        )
        self.model = GEN_MODEL
        log.info(
            "GenerationClient  base_url=%s  model=%s  max_tokens=%d  temperature=%.1f",
            GEN_BASE_URL, GEN_MODEL, GEN_MAX_TOKENS, GEN_TEMPERATURE,
        )

    def generate(self, question: str, context_chunks: list[dict]) -> str:
        """
        基于检索到的 chunks 构建 prompt，调用生成 API 返回回答。

        context_chunks 中每个 dict 至少包含：
            title, content, doc_title, relevance_score
        """
        # 构建参考资料文本块
        context_text = "\n\n---\n\n".join(
            f"【资料 {i+1}】来源：《{c['doc_title']}》 / {c['title']}"
            f"（相关性 {c['relevance_score']}%）\n{c['content']}"
            for i, c in enumerate(context_chunks)
        )

        user_message = (
            f"以下是从知识库中检索到的参考资料：\n\n"
            f"{context_text}\n\n"
            f"请根据以上资料回答问题：{question}"
        )

        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=GEN_MAX_TOKENS,
            temperature=GEN_TEMPERATURE,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )

        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            return response["choices"][0]["message"]["content"]

        return response.choices[0].message.content

    def generate_stream(self, question: str, context_chunks: list[dict]):
        """
        流式生成回答，按增量 token 产出字符串片段。
        """
        context_text = "\n\n---\n\n".join(
            f"【资料 {i+1}】来源：『{c['doc_title']}』/ {c['title']}"
            f"（相关性 {c['relevance_score']}%）\n{c['content']}"
            for i, c in enumerate(context_chunks)
        )

        user_message = (
            f"以下是从知识库中检索到的参考资料：\n\n"
            f"{context_text}\n\n"
            f"请根据以上资料回答问题：{question}"
        )

        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=GEN_MAX_TOKENS,
            temperature=GEN_TEMPERATURE,
            stream=True,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )

        if isinstance(response, str):
            for ch in response:
                yield ch
            return

        if isinstance(response, dict):
            text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            for ch in text:
                yield ch
            return

        for part in response:
            text = None
            if isinstance(part, dict):
                delta = part.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content")
            else:
                choice = part.choices[0] if part.choices else None
                if choice and getattr(choice, "delta", None):
                    text = getattr(choice.delta, "content", None)
            if text:
                for ch in text:
                    yield ch
