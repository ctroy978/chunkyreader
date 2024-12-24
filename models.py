# models.py
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime, timezone


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    email: str
    full_name: str
    hashed_password: str
    is_teacher: bool = Field(default=False)
    teacher_texts: List["Text"] = Relationship(back_populates="teacher")


class TextBase(SQLModel):
    title: str
    content: str
    created_at: datetime
    teacher_id: Optional[int] = Field(foreign_key="user.id")


class Text(TextBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    teacher: User = Relationship(
        back_populates="teacher_texts"
    )  # This matches the User model's relationship
    chunks: List["TextChunk"] = Relationship(back_populates="text")


class TextChunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text_id: int = Field(foreign_key="text.id")
    text: Text = Relationship(back_populates="chunks")
    content: str
    sequence_number: int
    created_at: datetime
