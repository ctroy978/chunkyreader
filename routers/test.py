from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List
from database import get_session
from models import Text, User, TextChunk
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel
from dotenv import load_dotenv
import os
import random
import re

router = APIRouter(prefix="/test", tags=["test"])

model = GroqModel("llama-3.1-70b-versatile")

load_dotenv()


class Question(BaseModel):
    id: int
    question: str


class TestQuestions(BaseModel):
    text_id: int
    questions: List[Question]


class TestAnswer(BaseModel):
    question_id: int
    answer: str


class TestSubmission(BaseModel):
    text_id: int
    answers: dict[int, str]


class TestResult(BaseModel):
    score: float
    feedback: List[dict]


def create_test_agent():
    return Agent(
        model,
        result_type=TestQuestions,
        system_prompt=(
            "You are creating a final comprehension test for students who have "
            "just completed reading a text. Generate 5 challenging questions that "
            "test overall understanding of the main themes, events, and concepts."
        ),
    )


test_agent = create_test_agent()


def clean_text(text: str) -> str:
    """Clean text by removing HTML tags, chunk markers, and extra whitespace."""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove chunk markers
    text = re.sub(r"<\/?chunk>", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove leading/trailing whitespace
    return text.strip()


class TestRequest(BaseModel):
    text_id: int


@router.post("/generate", response_model=TestQuestions)
async def generate_test(request: TestRequest, db: Session = Depends(get_session)):
    text_stmt = select(Text).where(Text.id == request.text_id)
    text = db.exec(text_stmt).first()
    if not text:
        raise HTTPException(status_code=404, detail="Text not found")

    chunk_stmt = select(TextChunk).where(TextChunk.text_id == request.text_id)
    chunks = db.exec(chunk_stmt).all()
    selected_chunks = random.sample(chunks, min(3, len(chunks)))
    content = clean_text(" ".join(chunk.content for chunk in selected_chunks))

    result = await test_agent.run(
        f"For text: '{clean_text(text.title)}', using these excerpts: {content}..."
    )
    return result.data


@router.post("/submit", response_model=TestResult)
async def submit_test(submission: TestSubmission, db: Session = Depends(get_session)):
    # Validate text exists
    text = db.exec(select(Text).where(Text.id == submission.text_id)).first()
    if not text:
        raise HTTPException(status_code=404, detail="Text not found")

    # Process each answer and generate feedback
    feedback = []
    total_score = 0
    num_questions = len(submission.answers)

    for question_id, answer in submission.answers.items():
        # Here you could add more sophisticated answer evaluation
        # For now, we'll give a basic score and feedback
        score = 1.0  # You could implement actual scoring logic
        total_score += score
        feedback.append(
            {
                "question_id": question_id,
                "score": score,
                "feedback": "Thank you for your answer.",  # You could implement AI feedback
            }
        )

    return TestResult(score=(total_score / num_questions) * 100, feedback=feedback)
