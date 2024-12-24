from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from database import get_session
from models import User, Text, TextChunk

router = APIRouter(prefix="/student", tags=["students"])


@router.get("/teachers/", response_model=List[dict])
async def get_teachers(session: Session = Depends(get_session)):
    """Get all teachers"""
    teachers = session.exec(select(User).where(User.is_teacher == True)).all()
    return [{"id": t.id, "full_name": t.full_name} for t in teachers]


@router.get("/teachers/{teacher_id}/texts", response_model=List[dict])
async def get_teacher_texts(teacher_id: int, session: Session = Depends(get_session)):
    """Get all texts for a specific teacher"""
    # Verify the requested user is actually a teacher
    teacher = session.exec(
        select(User).where(User.id == teacher_id).where(User.is_teacher == True)
    ).first()

    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    texts = session.exec(select(Text).where(Text.teacher_id == teacher_id)).all()

    return [{"id": t.id, "title": t.title, "created_at": t.created_at} for t in texts]


@router.get("/texts/{text_id}/first-chunk")
async def get_first_chunk(text_id: int, session: Session = Depends(get_session)):
    """Get the first chunk of a specific text"""
    chunk = session.exec(
        select(TextChunk)
        .where(TextChunk.text_id == text_id)
        .where(TextChunk.sequence_number == 1)
    ).first()

    if not chunk:
        raise HTTPException(status_code=404, detail="Text chunk not found")

    return {
        "chunk_id": chunk.id,
        "content": chunk.content,
        "sequence_number": chunk.sequence_number,
    }


@router.get("/texts/{text_id}/next-chunk/{current_chunk_id}")
async def get_next_chunk(
    text_id: int, current_chunk_id: int, session: Session = Depends(get_session)
):
    """Get the next chunk of text after the current chunk"""
    # First get the current chunk to know its sequence number
    current_chunk = session.exec(
        select(TextChunk)
        .where(TextChunk.id == current_chunk_id)
        .where(TextChunk.text_id == text_id)  # Verify chunk belongs to correct text
    ).first()

    if not current_chunk:
        raise HTTPException(status_code=404, detail="Current chunk not found")

    # Get the next chunk by sequence number
    next_chunk = session.exec(
        select(TextChunk)
        .where(TextChunk.text_id == text_id)
        .where(TextChunk.sequence_number == current_chunk.sequence_number + 1)
    ).first()

    if not next_chunk:
        raise HTTPException(status_code=404, detail="No more chunks available")

    return {
        "chunk_id": next_chunk.id,
        "content": next_chunk.content,
        "sequence_number": next_chunk.sequence_number,
    }
