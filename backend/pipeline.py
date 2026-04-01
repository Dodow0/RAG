"""
pipeline.py — PDF 解析 + LangChain 文本切分。

① pypdf  : 逐页提取文本，记录字符范围用于溯源页码
② LangChain RecursiveCharacterTextSplitter : 语义感知切分
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from config import CHUNK_SIZE, CHUNK_OVERLAP

log = logging.getLogger("rag.pipeline")


# ── 切分器（全局单例）────────────────────────────────────────────────────────

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    # 优先级：段落 > 换行 > 中文句末 > 英文句末 > 分号 > 词 > 字符
    separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", "；", ";", " ", ""],
    length_function=len,
    is_separator_regex=False,
    add_start_index=True,
)


# ── ① pypdf 文本提取 ──────────────────────────────────────────────────────────

def extract_pdf(pdf_bytes: bytes) -> tuple[str, list[tuple[int, int]], str]:
    """
    提取 PDF 文本。

    返回：
        full_text   — 全文（页间以 \\n\\n 分隔）
        page_ranges — [(run_rag.bat, end), ...]  每页文本在 full_text 中的字符范围
        meta_title  — PDF 元数据中的标题（可能为空串）
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise TypeError("extract_pdf expects bytes input")

    reader = PdfReader(io.BytesIO(bytes(pdf_bytes)))

    meta_title = ""
    if reader.metadata and getattr(reader.metadata, "title", None):
        meta_title = (reader.metadata.title or "").strip()

    parts: list[str] = []
    page_ranges: list[tuple[int, int]] = []
    cursor = 0

    for page in reader.pages:
        text = (page.extract_text() or "") + "\n\n"
        parts.append(text)
        page_ranges.append((cursor, cursor + len(text)))
        cursor += len(text)

    return "".join(parts), page_ranges, meta_title


def extract_pdf_path(pdf_path: str | Path) -> tuple[str, list[tuple[int, int]], str]:
    """
    浠庣鐩樿矾寰勮鍙栧苯 PDF锛岄伩鍏嶄竴娆℃€у叏閮ㄨ鍏ュ唴瀛樸€?
    """
    with open(pdf_path, "rb") as handle:
        reader = PdfReader(handle)

        meta_title = ""
        if reader.metadata and getattr(reader.metadata, "title", None):
            meta_title = (reader.metadata.title or "").strip()

        parts: list[str] = []
        page_ranges: list[tuple[int, int]] = []
        cursor = 0

        for page in reader.pages:
            text = (page.extract_text() or "") + "\n\n"
            parts.append(text)
            page_ranges.append((cursor, cursor + len(text)))
            cursor += len(text)

        return "".join(parts), page_ranges, meta_title


def _char_to_page(offset: int, page_ranges: list[tuple[int, int]]) -> int:
    """字符偏移 → 页码（1-based）。"""
    for page_num, (s, e) in enumerate(page_ranges, 1):
        if s <= offset < e:
            return page_num
    return len(page_ranges)


# ── ② LangChain 文本切分 ──────────────────────────────────────────────────────

def split_text(
    full_text: str,
    page_ranges: list[tuple[int, int]],
    file_stem: str,
) -> list[dict]:
    """
    切分全文，每个 chunk 携带：
        id, title, content, page, char_start
    """
    lc_docs = _splitter.create_documents([full_text])
    chunks: list[dict] = []

    for i, doc in enumerate(lc_docs, 1):
        char_start: int = doc.metadata.get("start_index", 0)
        page = _char_to_page(char_start, page_ranges)
        chunks.append({
            "id":         str(i),
            "title":      f"{file_stem} · 片段 {i}（第 {page} 页）",
            "content":    doc.page_content.strip(),
            "page":       page,
            "char_start": char_start,
        })

    log.info("split  %d chars  %d pages  → %d chunks", len(full_text), len(page_ranges), len(chunks))
    return chunks
