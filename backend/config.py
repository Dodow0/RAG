"""
config.py — 所有 AI Provider 和服务配置集中在这里。
修改这里的配置即可切换任意兼容 OpenAI API 的 Embedding / 生成 服务。
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import os
import platform


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ① Embedding Provider
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 任何兼容 OpenAI /v1/embeddings 接口的服务都可以接入，例如：
#
#  Provider        | EMBED_BASE_URL                              | EMBED_MODEL
#  ──────────────────────────────────────────────────────────────────────────
#  OpenAI          | https://api.openai.com/v1                  | text-embedding-3-small
#  Azure OpenAI    | https://<res>.openai.azure.com/openai/v1   | text-embedding-ada-002
#  Ollama (本地)   | http://localhost:11434/v1                   | nomic-embed-text
#  Jina AI         | https://api.jina.ai/v1                     | jina-embeddings-v3
#  Together AI     | https://api.together.xyz/v1                | togethercomputer/m2-bert-80M-8k-retrieval
#  Cohere (compat) | https://api.cohere.com/compatibility/v1    | embed-multilingual-v3.0
#

EMBED_BASE_URL  = os.environ.get("EMBED_BASE_URL",  "https://api.openai.com/v1")
EMBED_API_KEY   = os.environ.get("EMBED_API_KEY",   os.environ.get("OPENAI_API_KEY", ""))
EMBED_MODEL     = os.environ.get("EMBED_MODEL",     "text-embedding-3-small")
EMBED_DIMENSION = int(os.environ.get("EMBED_DIMENSION", "1536"))
EMBED_BATCH     = int(os.environ.get("EMBED_BATCH",     "512"))   # 每批最多条数


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ② Generation Provider
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 任何兼容 OpenAI /v1/chat/completions 接口的服务都可以接入，例如：
#
#  Provider        | GEN_BASE_URL                                | GEN_MODEL
#  ──────────────────────────────────────────────────────────────────────────
#  OpenAI          | https://api.openai.com/v1                  | gpt-4o
#  Anthropic*      | https://api.anthropic.com/v1               | claude-sonnet-4-20250514
#  Ollama (本地)   | http://localhost:11434/v1                   | llama3.2
#  DeepSeek        | https://api.deepseek.com/v1                | deepseek-chat
#  Groq            | https://api.groq.com/openai/v1             | llama-3.3-70b-versatile
#  Together AI     | https://api.together.xyz/v1                | meta-llama/Llama-3.3-70B-Instruct-Turbo
#  SiliconFlow     | https://api.siliconflow.cn/v1              | Qwen/Qwen2.5-72B-Instruct
#  月之暗面 (Kimi) | https://api.moonshot.cn/v1                 | moonshot-v1-8k
#
# * Anthropic 原生 API 不兼容 OpenAI，建议使用 OpenAI 兼容层或直接切换 Provider
#

GEN_BASE_URL  = os.environ.get("GEN_BASE_URL",  "https://api.openai.com/v1")
GEN_API_KEY   = os.environ.get("GEN_API_KEY",   os.environ.get("OPENAI_API_KEY", ""))
GEN_MODEL     = os.environ.get("GEN_MODEL",     "gpt-4o-mini")
GEN_MAX_TOKENS = int(os.environ.get("GEN_MAX_TOKENS", "2048"))
GEN_TEMPERATURE = float(os.environ.get("GEN_TEMPERATURE", "0.2"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ③ LangChain 文本切分参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHUNK_SIZE    = int(os.environ.get("CHUNK_SIZE",    "800"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "150"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ④ ChromaDB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHROMA_PATH       = os.environ.get("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION = os.environ.get("CHROMA_COLLECTION", "rag_knowledge_base")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑤ 检索参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOP_K = int(os.environ.get("TOP_K", "5"))

# SQLAlchemy (SQLite)
SQLITE_URL = os.environ.get("SQLITE_URL", "sqlite:///./rag_docs.db")

# Redis (RQ)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
EVENT_CHANNEL = os.environ.get("EVENT_CHANNEL", "rag_events")

# Task processing mode: rq | background | inline
DEFAULT_PROCESSING_MODE = "background"
PROCESSING_MODE = os.environ.get("PROCESSING_MODE", DEFAULT_PROCESSING_MODE)
