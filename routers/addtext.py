from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Form, HTTPException, APIRouter, Request
from sqlmodel import Session, select
from datetime import datetime, timezone
import html
from typing import List
import re
import bleach

from database import get_session
from models import Text, TextBase, TextChunk, User
from auth.dependencies import get_current_teacher


router = APIRouter(prefix="/addtext", tags=["teachers"])


def sanitize_text(text: str) -> str:
    """
    Sanitizes input text while preserving <chunk> tags and converting
    paragraph breaks to HTML for proper display in the browser.

    Args:
        text (str): Input text, with or without chunk tags

    Returns:
        str: Sanitized text with HTML paragraphs and preserved chunk tags if present

    Raises:
        HTTPException: If the text cannot be properly sanitized
    """
    from fastapi import HTTPException
    import bleach
    import re

    # First, safely store the chunk tags
    chunk_placeholder_start = "___CHUNK_START_PLACEHOLDER___"
    chunk_placeholder_end = "___CHUNK_END_PLACEHOLDER___"

    # Check if this text contains any chunk-like content
    has_chunk_content = "<chunk>" in text or "</chunk>" in text

    if has_chunk_content:
        # Replace chunk tags with placeholders before processing
        text = text.replace("<chunk>", chunk_placeholder_start)
        text = text.replace("</chunk>", chunk_placeholder_end)

    # Normalize line endings
    text = text.replace("\r\n", "\n")

    # Split into paragraphs and wrap in <p> tags
    paragraphs = re.split(r"\n\s*\n", text)
    processed_paras = []
    for para in paragraphs:
        para = para.strip()
        if para:
            # Don't wrap placeholders in <p> tags
            if not (chunk_placeholder_start in para or chunk_placeholder_end in para):
                processed_paras.append(f"<p>{para}</p>")
            else:
                processed_paras.append(para)

    # Join the processed paragraphs
    text = "\n".join(processed_paras)

    # Sanitize while preserving paragraph tags
    sanitized = bleach.clean(
        text, tags=["p"], attributes={}, strip=True, strip_comments=True
    )

    if has_chunk_content:
        # Restore chunk tags
        sanitized = sanitized.replace(chunk_placeholder_start, "<chunk>")
        sanitized = sanitized.replace(chunk_placeholder_end, "</chunk>")

    # Clean up whitespace
    sanitized = re.sub(r"\s*\n\s*", "\n", sanitized)

    # Final validation
    if not sanitized or sanitized.isspace():
        raise HTTPException(
            status_code=400, detail="Sanitization resulted in empty text"
        )

    return sanitized


def validate_chunks(text: str) -> bool:
    """
    Validates that chunk tags are properly formatted and balanced.

    Args:
        text (str): Text to validate

    Returns:
        bool: True if validation passes

    Raises:
        HTTPException: With specific details about validation failures
    """
    from fastapi import HTTPException
    import re

    # First check - make sure we have proper opening tags
    if "chunk>" in text and "<chunk>" not in text:
        raise HTTPException(
            status_code=400,
            detail="Found malformed opening chunk tag 'chunk>'. Did you mean '<chunk>'?",
        )

    # Second check - make sure we have proper closing tags
    if "</chunk" in text and "</chunk>" not in text:
        raise HTTPException(
            status_code=400,
            detail="Found malformed closing chunk tag. Did you mean '</chunk>'?",
        )

    # Count opening and closing tags
    open_tags = len(re.findall(r"<chunk>", text))
    close_tags = len(re.findall(r"</chunk>", text))

    if open_tags == 0 and close_tags == 0:
        raise HTTPException(
            status_code=400,
            detail="No chunk tags found. Text must be divided into chunks using <chunk>...</chunk> tags",
        )

    if open_tags != close_tags:
        raise HTTPException(
            status_code=400,
            detail=f"Mismatched chunk tags: found {open_tags} opening tags and {close_tags} closing tags",
        )

    # Check for proper nesting using regex
    chunk_pattern = r"<chunk>.*?</chunk>"
    if not re.findall(chunk_pattern, text, re.DOTALL):
        raise HTTPException(
            status_code=400,
            detail="Chunk tags are not properly nested. Each chunk must start with <chunk> and end with </chunk>",
        )

    return True


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
    current_teacher: User = Depends(get_current_teacher),
    session: Session = Depends(get_session),
):
    try:
        # First sanitize the text
        sanitized_title = sanitize_text(title)
        sanitized_content = sanitize_text(content)

        # Only validate chunk formatting for the content, not the title
        if not validate_chunks(sanitized_content):
            raise HTTPException(
                status_code=400,
                detail="Invalid chunk formatting. Ensure all <chunk> tags are properly closed.",
            )

        # Split content into chunks
        chunks = split_into_chunks(sanitized_content)

        # Create text record
        text = Text(
            title=sanitized_title,
            content=sanitized_content,
            created_at=datetime.now(timezone.utc),
            teacher_id=current_teacher.id,
            total_chunks=len(chunks),
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

    except Exception as e:
        print("Error during processing:", str(e))  # Debug
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/texts/", response_model=List[dict])
async def get_texts(
    session: Session = Depends(get_session),
    current_teacher: User = Depends(get_current_teacher),
):
    """Get all texts for the current teacher"""
    texts = session.exec(
        select(Text).where(Text.teacher_id == current_teacher.id)
    ).all()

    return [
        {"id": text.id, "title": text.title, "created_at": text.created_at}
        for text in texts
    ]


# @router.post("/texts/", response_model=Text)
# async def create_text(
#     request: Request,  # Add this to see raw request
#     title: str = Form(...),
#     content: str = Form(...),
#     current_teacher: User = Depends(get_current_teacher),
#     session: Session = Depends(get_session),
# ):
#     # Debug logging
#     body = await request.body()
#     print("Raw request body:", body)
#     print("Content type:", request.headers.get("content-type"))
#     print("Current teacher:", current_teacher)

#     sanitized_title = sanitize_text(title)
#     sanitized_content = sanitize_text(content)
#     ...


@router.delete("/texts/{text_id}")
async def delete_text(
    text_id: int,
    session: Session = Depends(get_session),
    current_teacher: User = Depends(get_current_teacher),
):
    # Verify the text belongs to the current teacher
    text = session.get(Text, text_id)
    if not text:
        raise HTTPException(status_code=404, detail="Text not found")

    if text.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this text"
        )

    # Delete associated chunks first
    chunks_statement = select(TextChunk).where(TextChunk.text_id == text_id)
    chunks = session.exec(chunks_statement).all()
    for chunk in chunks:
        session.delete(chunk)

    # Delete the text
    session.delete(text)
    session.commit()

    return {"message": f"Text {text_id} and its chunks deleted"}
