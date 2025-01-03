from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from typing import List
from database import get_session
from models import Text, User, TextChunk, ReadingSession, ReadingCompletion
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel
from dotenv import load_dotenv
from typing import Union, Literal
import os
import random
import re
import json
from datetime import datetime, timezone
from .session_manager import get_or_create_session, append_to_conversation
from auth.dependencies import get_current_user


router = APIRouter(prefix="/test", tags=["test"])

model = GroqModel("llama-3.1-70b-versatile")

load_dotenv()


# Models for sequential test questions
class Question(BaseModel):
    sequence: int
    question: str


class TestQuestions(BaseModel):
    text_id: int
    questions: List[Question]


class TestSubmission(BaseModel):
    text_id: int
    answers: List[str]  # Array of answers in same order as questions


class TestSessionData(BaseModel):
    chunk_ids: List[int]
    chunks: List[str]
    questions: List[str]  # Store just the question texts in order


class TestRequest(BaseModel):
    text_id: int


class TestAnswer(BaseModel):
    question_id: int
    answer: str


class EvalAnswers(BaseModel):
    correct: int = Field(
        ..., description="How many questions did the student answer correctly."
    )
    incorrect: int = Field(
        ..., description="How many questions did the student answer incorrectly."
    )
    feedback: str = Field(
        ..., description="Evaluation of the student's overall performance on the test."
    )


class TestResult(BaseModel):
    feedback: str
    correct: int
    incorrect: int
    questions_and_answers: List[dict]


def create_agent(return_type: Literal["testquestions", "evalanswers"]):
    if return_type == "testquestions":
        return_type = TestQuestions
    elif return_type == "evalanswers":
        return_type = EvalAnswers
    return Agent(
        model,
        result_type=return_type,
        system_prompt=(
            "You are creating and evaluating a final comprehension test for students who have "
            "just completed reading a text. Generate 5 challenging questions that "
            "test overall understanding of the main themes, events, and concepts."
        ),
    )


test_agent = create_agent("testquestions")
eval_agent = create_agent("evalanswers")


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


# test.py


@router.post("/generate", response_model=TestQuestions)
async def generate_test(
    request: TestRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Get text and validate
    text_stmt = select(Text).where(Text.id == request.text_id)
    text = db.exec(text_stmt).first()
    if not text:
        raise HTTPException(status_code=404, detail="Text not found")

    # Get chunks and select random ones
    chunk_stmt = select(TextChunk).where(TextChunk.text_id == request.text_id)
    chunks = db.exec(chunk_stmt).all()
    selected_chunks = random.sample(chunks, min(3, len(chunks)))
    content = clean_text(" ".join(chunk.content for chunk in selected_chunks))

    # Generate questions
    result = await test_agent.run(
        f"For text: '{clean_text(text.title)}', using these excerpts: {content}..."
    )

    # Convert to sequential questions
    sequential_questions = []
    for i, q in enumerate(result.data.questions, start=1):
        sequential_questions.append(Question(sequence=i, question=q.question))

    # Store in session
    session = await get_or_create_session(
        user_id=current_user.id,
        text_id=text.id,
        chunk_id=selected_chunks[0].id,
        db=db,
    )

    # Store sequential test data
    test_data = TestSessionData(
        chunk_ids=[chunk.id for chunk in selected_chunks],
        chunks=[chunk.content for chunk in selected_chunks],
        questions=[q.question for q in sequential_questions],
    )

    await append_to_conversation(
        session_id=session.id,
        role="system",
        content=test_data.dict(),
        msg_type="test_generation",
        db=db,
    )

    return TestQuestions(text_id=text.id, questions=sequential_questions)


#################
@router.post("/submit", response_model=TestResult)
async def submit_test(
    submission: TestSubmission,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # Validate text exists
    text = db.exec(select(Text).where(Text.id == submission.text_id)).first()
    if not text:
        raise HTTPException(status_code=404, detail="Text not found")

    # Get active session
    session = db.exec(
        select(ReadingSession).where(
            ReadingSession.user_id == current_user.id,
            ReadingSession.text_id == submission.text_id,
            ReadingSession.is_completed == False,
        )
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="No active session found")

    # Get test data from session
    conversation = json.loads(session.conversation_context)
    test_data = None
    for message in conversation:
        if message.get("type") == "test_generation":
            test_data = message.get("content")
            break

    if not test_data:
        raise HTTPException(status_code=404, detail="Test data not found")

    # Prepare evaluation data with sequential questions and answers
    evaluation_data = {
        "original_text": "\n".join(test_data["chunks"]),
        "questions_and_answers": [
            {
                "sequence": i + 1,
                "question": question,
                "student_answer": submission.answers[i],
            }
            for i, question in enumerate(test_data["questions"])
        ],
    }

    # Generate evaluation prompt
    evaluation_prompt = f"""
   Original text:
   {evaluation_data['original_text']}

   Student answers:
   """
    for qa in evaluation_data["questions_and_answers"]:
        evaluation_prompt += f"""
       Question {qa['sequence']}: {qa['question']}
       Answer: {qa['student_answer']}
       """

    # Evaluate answers
    result = await eval_agent.run(evaluation_prompt)

    # Store results and complete session
    session.is_completed = True
    db.commit()

    return TestResult(
        feedback=result.data.feedback,
        correct=result.data.correct,
        incorrect=result.data.incorrect,
        questions_and_answers=evaluation_data["questions_and_answers"],
    )
