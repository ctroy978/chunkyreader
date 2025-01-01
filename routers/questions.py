from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from database import get_session
from models import TextChunk, User
from dotenv import load_dotenv
import os
from typing import Union, Literal
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel
from .session_manager import get_or_create_session, append_to_conversation

router = APIRouter(prefix="/questions", tags=["questions"])

load_dotenv()

# Define all models


class BuildQuestion(BaseModel):
    question: str = Field(
        ...,
        description="A question designed to test the student's reading comprehension of the reading material.",
    )


class AnswerEvalResponse(BaseModel):
    message: str = Field(
        ..., description="Evaluate the student's answer and provide feedback"
    )
    can_proceed: bool = Field(
        ...,
        description="Decide whether or not the student can proceed to the next reading section.",
    )
    question: Union[str, None] = Field(
        ..., description="A follow up question if the student needs more guidance."
    )
    conversation_id: str


class AnswerEvalRequest(BaseModel):
    chunk_id: int
    text_id: int
    user_email: str
    answer: str
    current_question: str


class QuestionRequest(BaseModel):
    chunk_id: int
    text_id: int
    user_email: str


class QuestionResponse(BaseModel):
    question: str


# Setup agent

model = GroqModel("llama-3.1-70b-versatile")


def create_agent(return_type: Literal["buildquestion", "answerevalresponse"]):
    if return_type == "buildquestion":
        return_type = BuildQuestion
    elif return_type == "answerevalresponse":
        return_type = AnswerEvalResponse

    return Agent(
        model,
        result_type=return_type,
        system_prompt=(
            "You are a reading teacher working one on one with a student."
            "When replying, always reply directly to the student. Use words such as 'you' and 'your' when talking to the stuent."
            "When given a chunk of text, you will develop a challenging reading comprehension question based on that text."
            "When you are given a student's answer, you will evaluate the answere. If the answer isn't satisfactory, provide helpful feedback to the student."
            "If the student's answer demonstrates a deep understanding of the text, you can advance the student to the next reading session."
            "When evaluating the answer, you will decide whether or not a student can proceed to the next reading assignment."
        ),
    )


gen_agent = create_agent("buildquestion")
eval_agent = create_agent("answerevalresponse")

# add the username of the student to the agent
# @gen_agent.system_prompt
# def add_the_users_name(ctx: RunContext[str]) -> str:
#     return f"The user's name is {ctx.deps}."


def get_username(email: str, db: Session = Depends(get_session)) -> str:
    statement = select(User).where(User.email == email)
    user = db.exec(statement).first()
    return user.username


async def build_question(chunk: str) -> str:
    query = f"Reading sample: '{chunk}'. Analyze the reading sample and develop a reading comprehension question from the passage. Ask the student to answer your question."
    result = await gen_agent.run(query)

    # Clean up the question text - remove any 'question=' prefix and quotes
    question_text = str(result.data.question)
    if "question=" in question_text:
        question_text = question_text.split("question=")[1].strip("'\"")
    return question_text.rstrip("?")  # Remove trailing question mark if present


async def build_evaluation(chunk: str, current_question: str, answer: str) -> str:
    instructions_to_ai = """Look at the reading sample and the question you asked the student. You are to evaluate the merits of the student's answer 
    and decide if the student understands well enough to proceed to the next question. If the student's
    answer isn't acceptable, provide some feedback and possibly a hint to help the student better understand the text."""

    query = f"Reading sample: '{chunk}'. Question: '{current_question}. Answer: '{answer}'. Instructions: '{instructions_to_ai}'."
    result = await eval_agent.run(query)
    return result


# student sends the reading chunk here. We reply with a reading comprehension question.
@router.post("/generate", response_model=QuestionResponse)
async def generate_question(
    request: QuestionRequest, db: Session = Depends(get_session)
):
    # Get chunk content
    statement = select(TextChunk).where(TextChunk.id == request.chunk_id)
    chunk = db.exec(statement).first()
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Text Chunk not found"
        )

    # Get user info
    statement = select(User).where(User.email == request.user_email)
    user = db.exec(statement).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Get or create session
    session = await get_or_create_session(
        user_id=user.id, text_id=request.text_id, chunk_id=request.chunk_id, db=db
    )

    # Add chunk to conversation
    await append_to_conversation(
        session_id=session.id,
        role="system",
        content=f"CHUNK: {chunk.content}",
        msg_type="chunk",
        db=db,
    )

    # For testing, use dummy question
    current_question = "how do you feel about this."

    # When ready for AI, uncomment this:
    # current_question = await build_question(chunk.content)

    # Add question to conversation
    await append_to_conversation(
        session_id=session.id,
        role="assistant",
        content=f"QUESTION: {current_question}",
        msg_type="question",
        db=db,
    )

    return QuestionResponse(question=f"{current_question}?")


@router.post("/evaluate-answer", response_model=AnswerEvalResponse)
async def evaluate_answer(
    request: AnswerEvalRequest, db: Session = Depends(get_session)
):
    # get the chunk used to ask question
    statement = select(TextChunk).where(TextChunk.id == request.chunk_id)
    chunk = db.exec(statement).first()
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Text Chunk not found"
        )

    # result = await build_evaluation(chunk, request.current_question, request.answer)
    # return AnswerEvalResponse(
    #     message=result.data.message,
    #     can_proceed=result.data.can_proceed,
    #     question=result.data.question,
    #     conversation_id="dummy-number 123",
    # )

    """
    Evaluate student's answer and determine if they can proceed.
    This is a dummy version that alternates between proceeding and asking follow-up.
    """
    # This is just a dummy response - will be replaced with real AI logic
    # For testing, let's just alternate between proceed and follow-up
    import random

    is_satisfactory = random.choice([True, False])

    if is_satisfactory:
        return AnswerEvalResponse(
            message="Excellent work! You've shown good understanding of this section.",
            can_proceed=True,
            question=None,
            conversation_id="dummy-convo-123",
        )
    else:
        return AnswerEvalResponse(
            message="Good start, but let's explore this further.",
            can_proceed=False,
            question="Can you provide a specific example from the text to support your answer?",
            conversation_id="dummy-convo-123",
        )
