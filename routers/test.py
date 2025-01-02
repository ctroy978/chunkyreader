from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from typing import List
from database import get_session
from models import Text, User, TextChunk, ReadingSession
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel
from dotenv import load_dotenv
from typing import Union, Literal
import os
import random
import re
import json
from .session_manager import get_or_create_session, append_to_conversation
from auth.dependencies import get_current_user

router = APIRouter(prefix="/test", tags=["test"])

model = GroqModel("llama-3.1-70b-versatile")

load_dotenv()


class TestRequest(BaseModel):
    text_id: int


class Question(BaseModel):
    id: int
    question: str


class TestQuestions(BaseModel):
    text_id: int
    questions: List[Question]


class TestAnswer(BaseModel):
    question_id: int
    answer: str


# submitted by student
class TestSubmission(BaseModel):
    text_id: int
    answers: dict[int, str]  # student answers in {question_id: answer} format


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


from .session_manager import get_or_create_session, append_to_conversation
from models import User


@router.post("/generate", response_model=TestQuestions)
async def generate_test(
    request: TestRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),  # Add user dependency
):
    # Existing code to get text and validate
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

    # Get or create session
    session = await get_or_create_session(
        user_id=current_user.id,
        text_id=text.id,
        chunk_id=selected_chunks[0].id,  # Using first chunk as reference
        db=db,
    )

    # Store test data in session
    test_data = {
        "chunk_ids": [chunk.id for chunk in selected_chunks],
        "chunks": [chunk.content for chunk in selected_chunks],
        "questions": {str(q.id): q.question for q in result.data.questions},
    }

    await append_to_conversation(
        session_id=session.id,
        role="system",
        content=test_data,
        msg_type="test_generation",
        db=db,
    )

    return result.data


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

    # Get the session for this text and user
    session = db.exec(
        select(ReadingSession).where(
            ReadingSession.user_id == current_user.id,
            ReadingSession.text_id == submission.text_id,
            ReadingSession.is_completed == False,
        )
    ).first()

    if not session:
        raise HTTPException(
            status_code=404, detail="No active reading session found for this text"
        )

    # Find the test_generation data in the conversation context
    conversation = json.loads(session.conversation_context)
    test_data = None
    for message in conversation:
        if message.get("type") == "test_generation":
            test_data = message.get("content")
            break

    if not test_data:
        raise HTTPException(status_code=404, detail="Test data not found in session")

    evaluation_data = {
        "original_text": "\n".join(test_data["chunks"]),
        "questions_and_answers": [
            {
                "question_id": q_id,
                "question": test_data["questions"][q_id],
                "student_answer": submission.answers.get(
                    int(q_id), "No answer provided"
                ),
            }
            for q_id in test_data["questions"].keys()
        ],
        "total_questions": len(test_data["questions"]),
    }

    evaluation_prompt = f"""
    Here is the original text the student read:
    {evaluation_data['original_text']}

    Please evaluate these student answers:
    """
    for qa in evaluation_data["questions_and_answers"]:
        evaluation_prompt += f"""
        Question {qa['question_id']}: {qa['question']}
        Student's Answer: {qa['student_answer']}
        """

    # Send to AI for evaluation
    result = await eval_agent.run(evaluation_prompt)

    # Store the evaluation results in the session
    await append_to_conversation(
        session_id=session.id,
        role="assistant",
        content={
            "correct": result.data.correct,
            "incorrect": result.data.incorrect,
            "feedback": result.data.feedback,
        },
        msg_type="test_evaluation",
        db=db,
    )

    # Mark the session as completed
    session.is_completed = True
    db.commit()

    return TestResult(
        feedback=result.data.feedback,
        correct=result.data.correct,
        incorrect=result.data.incorrect,
        questions_and_answers=evaluation_data["questions_and_answers"],
    )
