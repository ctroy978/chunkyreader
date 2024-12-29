from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from database import get_session
from models import TextChunk

router = APIRouter(prefix="/questions", tags=["questions"])


class QuestionRequest(BaseModel):
    chunk_id: int
    text_id: int


class QuestionResponse(BaseModel):
    question: str


@router.post("/generate", response_model=QuestionResponse)
async def generate_question(
    request: QuestionRequest, db: Session = Depends(get_session)
):
    """
    Generate a question for the current chunk by first fetching chunk content from db.
    """
    # Get the chunk content from database
    statement = select(TextChunk).where(TextChunk.id == request.chunk_id)
    chunk = db.exec(statement).first()

    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found"
        )

    # Store the chunk text in a variable
    chunk_text = chunk.content

    # TODO: Use chunk_text to generate an appropriate question
    return QuestionResponse(question="What is the main idea of this passage?")
