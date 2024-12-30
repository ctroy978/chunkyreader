from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from database import get_session
from models import TextChunk, User
from dotenv import load_dotenv
import os


router = APIRouter(prefix="/questions", tags=["questions"])

load_dotenv()


class QuestionRequest(BaseModel):
    chunk_id: int
    text_id: int
    user_email: str


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

    # get the username of the student
    statement = select(User).where(User.email == request.user_email)
    user = db.exec(statement).first()

    return QuestionResponse(
        question=f"Hello {user.username}! What is the main idea of this passage?"
    )
