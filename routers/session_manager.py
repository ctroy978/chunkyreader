from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_session
from models import ReadingSession
import json

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def get_or_create_session(
    user_id: int, text_id: int, chunk_id: int, db: Session
) -> ReadingSession:
    """Get existing session or create new one"""
    # Try to find existing active session
    statement = select(ReadingSession).where(
        ReadingSession.user_id == user_id,
        ReadingSession.text_id == text_id,
        ReadingSession.is_completed == False,
    )
    session = db.exec(statement).first()

    # Create new session if none exists
    if not session:
        session = ReadingSession(user_id=user_id, text_id=text_id, chunk_id=chunk_id)
        db.add(session)
        db.commit()
        db.refresh(session)

    return session


async def append_to_conversation(
    session_id: int,
    role: str,  # 'system', 'assistant', or 'user'
    content: str,
    msg_type: str,  # 'chunk', 'question', or 'answer'
    db: Session,
) -> None:
    """Add a new message to the conversation context"""
    session = db.get(ReadingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Load existing conversation
    conversation = json.loads(session.conversation_context)

    # Add new message
    conversation.append({"role": role, "content": content, "type": msg_type})

    # Save updated conversation
    session.conversation_context = json.dumps(conversation)
    db.commit()


async def get_conversation_context(session_id: int, db: Session) -> str:
    """Retrieve the full conversation context"""
    session = db.get(ReadingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session.conversation_context


async def get_current_question(session_id: int, db: Session) -> str:
    """Helper function to get the current question from conversation context"""
    conversation = json.loads(await get_conversation_context(session_id, db))
    # Find the last question in the conversation
    for message in reversed(conversation):
        if message["type"] == "question":
            return message["content"]
    return ""
