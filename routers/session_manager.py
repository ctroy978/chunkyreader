from sqlmodel import Session, select
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status, APIRouter
from models import ReadingSession
from typing import Optional, List, Dict
import json
from sqlalchemy import text


router = APIRouter(prefix="/session_manager", tags=["questions"])


class ReadingSessionManager:
    def __init__(self, db: Session):
        self.db = db
        self.SESSION_EXPIRY = timedelta(days=7)  # Sessions expire after 1 week

    async def create_or_get_session(
        self, user_id: int, text_id: int, chunk_id: int, initial_question: str
    ) -> ReadingSession:
        await self._cleanup_expired_sessions()

        existing = self.db.exec(
            select(ReadingSession).where(
                ReadingSession.user_id == user_id,
                ReadingSession.text_id == text_id,
                ReadingSession.is_completed == False,
            )
        ).first()

        if existing:
            existing.chunk_id = chunk_id  # Update current chunk
            self.db.commit()
            return existing

        new_session = ReadingSession(
            user_id=user_id,
            text_id=text_id,
            chunk_id=chunk_id,
            current_question=initial_question,
            conversation_context=json.dumps([]),
            expires_at=datetime.now(timezone.utc) + self.SESSION_EXPIRY,
            is_completed=False,
        )

        self.db.add(new_session)
        self.db.commit()
        self.db.refresh(new_session)
        return new_session

    async def get_session(self, user_id: int, text_id: int) -> Optional[ReadingSession]:
        """Get existing session by text_id"""
        return self.db.exec(
            select(ReadingSession).where(
                ReadingSession.user_id == user_id,
                ReadingSession.text_id == text_id,
                ReadingSession.is_completed == False,
            )
        ).first()

    async def update_conversation(
        self,
        session_id: int,
        user_id: int,
        new_message: Dict,
        new_question: Optional[str] = None,
    ) -> ReadingSession:
        """Update the conversation context with a new message"""
        session = self.db.exec(
            select(ReadingSession).where(
                ReadingSession.id == session_id, ReadingSession.user_id == user_id
            )
        ).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reading session not found",
            )

        # Load existing conversation
        try:
            conversation = json.loads(session.conversation_context)
        except json.JSONDecodeError:
            conversation = []

        # Add new message
        conversation.append(new_message)

        # Update session
        session.conversation_context = json.dumps(conversation)
        if new_question:
            session.current_question = new_question
        session.expires_at = (
            datetime.now(timezone.utc) + self.SESSION_EXPIRY
        )  # Reset expiration

        self.db.commit()
        self.db.refresh(session)
        return session

    async def get_conversation_history(
        self, session_id: int, user_id: int
    ) -> List[Dict]:
        """Get the conversation history for a session"""
        session = self.db.exec(
            select(ReadingSession).where(
                ReadingSession.id == session_id, ReadingSession.user_id == user_id
            )
        ).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reading session not found",
            )

        try:
            return json.loads(session.conversation_context)
        except json.JSONDecodeError:
            return []

    async def complete_session(self, session_id: int, user_id: int):
        """Mark a session as completed"""
        session = self.db.exec(
            select(ReadingSession).where(
                ReadingSession.id == session_id, ReadingSession.user_id == user_id
            )
        ).first()

        if session:
            session.is_completed = True
            self.db.commit()

    async def get_incomplete_sessions(self, user_id: int) -> List[ReadingSession]:
        """Get all incomplete sessions for a user"""
        return self.db.exec(
            select(ReadingSession).where(
                ReadingSession.user_id == user_id, ReadingSession.is_completed == False
            )
        ).all()

    async def _cleanup_expired_sessions(self):
        self.db.execute(
            text("DELETE FROM readingsession WHERE expires_at < :now"),
            {"now": datetime.now(timezone.utc)},
        )
