from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocRecord(Base):
    __tablename__ = "docs"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    file_name: Mapped[str]
    uploaded_at: Mapped[str]
    status: Mapped[str] = mapped_column(default="processing", index=True)
    total_chars: Mapped[int] = mapped_column(default=0)
    chunks: Mapped[list["ChunkRecord"]] = relationship(
        back_populates="doc",
        cascade="all, delete-orphan",
    )


class ChunkRecord(Base):
    __tablename__ = "doc_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    doc_id: Mapped[str] = mapped_column(ForeignKey("docs.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(index=True)
    title: Mapped[str]
    content: Mapped[str]
    page: Mapped[Optional[int]] = mapped_column(default=None)
    char_start: Mapped[Optional[int]] = mapped_column(default=None)
    chunk_order: Mapped[int] = mapped_column(default=0, index=True)
    doc: Mapped[DocRecord] = relationship(back_populates="chunks")
