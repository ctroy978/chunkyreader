from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime, timezone, timedelta


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    email: str
    full_name: str
    hashed_password: str
    is_teacher: bool = Field(default=False)
    is_deleted: bool = Field(default=False, index=True)
    deleted_at: Optional[datetime] = Field(default=None)

    teacher_texts: List["Text"] = Relationship(back_populates="teacher")
    reading_completions: List["ReadingCompletion"] = Relationship(
        back_populates="student"
    )

    admin_privilege: Optional["AdminPrivilege"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "uselist": False,
            "foreign_keys": "[AdminPrivilege.user_id]",
        },
    )


class TextBase(SQLModel):
    # Base model for text content that will be divided into chunks
    # Used as foundation for Text model to allow for easy creation/validation
    title: str
    content: str  # original full text value
    created_at: datetime
    teacher_id: Optional[int] = Field(foreign_key="user.id")
    total_chunks: int
    is_deleted: bool = Field(default=False, index=True)
    deleted_at: Optional[datetime] = Field(default=None)


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
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="user.id")
    text_id: int = Field(foreign_key="text.id")
    completed_at: datetime = Field(default=datetime.now(timezone.utc))
    passed: bool
    ai_feedback: str
    correct_answers: int = Field(default=0)

    student: User = Relationship(back_populates="reading_completions")
    text: Text = Relationship(back_populates="completions")


class ReadingSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Core identifiers
    user_id: int = Field(foreign_key="user.id", index=True)
    text_id: int = Field(foreign_key="text.id", index=True)
    chunk_id: int = Field(foreign_key="textchunk.id")  # For tracking progress

    # AI conversation thread
    conversation_context: str = Field(
        default="[]", description="Stores the conversation history for AI context"
    )

    # Session management
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=3)
    )
    is_completed: bool = Field(default=False)

    class Config:
        arbitrary_types_allowed = True


class AdminPrivilege(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    granted_by_id: Optional[int] = Field(foreign_key="user.id", nullable=True)
    grant_reason: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)

    # Relationships
    user: "User" = Relationship(
        back_populates="admin_privilege",
        sa_relationship_kwargs={"foreign_keys": "[AdminPrivilege.user_id]"},
    )
    granted_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AdminPrivilege.granted_by_id]"}
    )
