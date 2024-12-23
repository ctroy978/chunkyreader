# models.py
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone


class TextBase(SQLModel):
    title: str
    content: str
    created_at: datetime
    teacher_id: Optional[int] = None


class Text(TextBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class TextChunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text_id: int = Field(foreign_key="text.id")
    content: str
    sequence_number: int
    created_at: datetime
