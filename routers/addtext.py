from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Form, HTTPException, APIRouter
from sqlmodel import Session, select
from datetime import datetime, timezone
import html
from typing import List
import re

from database import get_session
from models import Text, TextBase, TextChunk


router = APIRouter(prefix="/addtext", tags=["teachers"])


def sanitize_text(text: str) -> str:
    """Sanitize text input while preserving chunk tags"""
    # Temporarily replace chunk tags
    text = text.replace("<chunk>", "|||CHUNKOPEN|||")
    text = text.replace("</chunk>", "|||CHUNKCLOSE|||")

    # Sanitize
    text = html.escape(text)
    text = " ".join(text.split())

    # Restore chunk tags
    text = text.replace("|||CHUNKOPEN|||", "<chunk>")
    text = text.replace("|||CHUNKCLOSE|||", "</chunk>")
    return text


def validate_chunks(content: str) -> bool:
    """Validate that chunks are properly formatted and balanced"""
    open_tags = content.count("<chunk>")
    close_tags = content.count("</chunk>")
    if open_tags != close_tags:
        return False
    # Check proper nesting
    return bool(re.match(r"^(.*?<chunk>.*?</chunk>)*.*?$", content))


def split_into_chunks(content: str) -> List[str]:
    """Split content into chunks based on <chunk></chunk> tags"""
    if not validate_chunks(content):
        raise HTTPException(
            status_code=400,
            detail="Invalid chunk formatting. Ensure all <chunk> tags are properly closed.",
        )

    # Split content into chunks
    chunks = re.split(r"</chunk>\s*<chunk>", content)

    # Clean up first and last chunk
    chunks[0] = chunks[0].replace("<chunk>", "")
    chunks[-1] = chunks[-1].replace("</chunk>", "")

    return [chunk.strip() for chunk in chunks]


@router.post("/texts/", response_model=Text)
async def create_text(
    title: str = Form(...),
    content: str = Form(...),
    teacher_id: int = Form(None),
    session: Session = Depends(get_session),
):
    sanitized_title = sanitize_text(title)
    sanitized_content = sanitize_text(content)

    # Split content into chunks
    chunks = split_into_chunks(sanitized_content)

    # Create text record
    text = Text(
        title=sanitized_title,
        content=sanitized_content,
        created_at=datetime.now(timezone.utc),
        teacher_id=teacher_id,
    )

    session.add(text)
    session.commit()
    session.refresh(text)

    # Create chunks
    for i, chunk_content in enumerate(chunks, 1):
        chunk = TextChunk(
            text_id=text.id,
            content=chunk_content,
            sequence_number=i,
            created_at=datetime.now(timezone.utc),
        )
        session.add(chunk)

    session.commit()
    return text


@router.delete("/texts/{text_id}")
async def delete_text(text_id: int, session: Session = Depends(get_session)):
    # Delete associated chunks first
    chunks_statement = select(TextChunk).where(TextChunk.text_id == text_id)
    chunks = session.exec(chunks_statement).all()
    for chunk in chunks:
        session.delete(chunk)

    # Delete the text
    text = session.get(Text, text_id)
    if not text:
        raise HTTPException(status_code=404, detail="Text not found")

    session.delete(text)
    session.commit()

    return {"message": f"Text {text_id} and its chunks deleted"}
