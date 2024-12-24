from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime, timezone


class User(SQLModel, table=True):
    # This is the base user model that handles both teachers and students
    # Teachers can create texts and students can complete readings
    # is_teacher flag determines user permissions and available features
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    email: str
    full_name: str
    hashed_password: str
    is_teacher: bool = Field(default=False)

    # Relationships:
    # - teacher_texts: texts created by this user (if they're a teacher)
    # - reading_completions: reading assignments completed by this user (if they're a student)

    teacher_texts: List["Text"] = Relationship(back_populates="teacher")
    reading_completions: List["ReadingCompletion"] = Relationship(
        back_populates="student"
    )


class TextBase(SQLModel):
    # Base model for text content that will be divided into chunks
    # Used as foundation for Text model to allow for easy creation/validation
    title: str
    content: str  # original full text value
    created_at: datetime
    teacher_id: Optional[int] = Field(foreign_key="user.id")
    total_chunks: int


class Text(TextBase, table=True):
    # Main text model that inherits from TextBase
    # Represents a complete reading assignment
    id: Optional[int] = Field(default=None, primary_key=True)
    teacher: User = Relationship(
        back_populates="teacher_texts"
    )  # This matches the User model's relationship
    chunks: List["TextChunk"] = Relationship(back_populates="text")
    completions: List["ReadingCompletion"] = Relationship(back_populates="text")


class TextChunk(SQLModel, table=True):
    # Individual chunks of text that students read and answer questions about
    # Created by parsing <chunk> tags in the original text
    id: Optional[int] = Field(default=None, primary_key=True)
    text_id: int = Field(foreign_key="text.id")
    text: Text = Relationship(back_populates="chunks")
    content: str
    sequence_number: int
    created_at: datetime


class ReadingCompletion(SQLModel, table=True):
    # Records student completion of entire text assignments
    # Includes AI feedback and pass/fail status
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="user.id")
    text_id: int = Field(foreign_key="text.id")
    completed_at: datetime = Field(default=datetime.now(timezone.utc))
    passed: bool
    ai_feedback: str

    student: User = Relationship(back_populates="reading_completions")
    text: Text = Relationship(back_populates="completions")
