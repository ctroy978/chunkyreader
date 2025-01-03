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


async def build_evaluation(
    chunk: str, current_question: str, answer: str
) -> AnswerEvalResponse:
    try:
        instructions_to_ai = (
            "Evaluate the student's answer using this simple rubric:\n\n"
            "1. Basic Understanding: The student's answer shows a solid grasp of the main idea.\n"
            "2. Supporting Details: The student offers specific and relevant details to support their answer.\n"
            "3. Expression: The student's answer is clear and coherent. Some grammatical errors can be allowed.\n\n"
            "When giving feedback, start with what they got right and offer gentle suggestions. Use encouraging language.\n\n"
            "Students should proceed if they demonstrate Basic Understanding of the main point, and offer accurate "
            "Supporting Details, even if some details are missing."
        )

        query = f"Reading sample: '{chunk}'. Question: '{current_question}'. Answer: '{answer}'. Instructions: '{instructions_to_ai}'."
        result = await eval_agent.run(query)

        return result.data

    except Exception as e:
        # Return a graceful fallback response if AI evaluation fails
        return AnswerEvalResponse(
            message="I cannot properly evaluate your answer right now. Please try submitting again.",
            can_proceed=False,
            question=current_question,
            conversation_id="error",
        )


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

    # For testing, use dummy question
    # current_question = "how do you feel about this."

    # When ready for AI, uncomment this:
    current_question = await build_question(chunk.content)

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
    try:
        # Get the chunk used to ask question
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

        # Get/create session
        session = await get_or_create_session(
            user_id=user.id, text_id=request.text_id, chunk_id=request.chunk_id, db=db
        )

        # Store student's answer
        await append_to_conversation(
            session_id=session.id,
            role="user",
            content=request.answer,
            msg_type="answer",
            db=db,
        )
        result = await build_evaluation(
            chunk.content, request.current_question, request.answer
        )

        # Store feedback
        await append_to_conversation(
            session_id=session.id,
            role="assistant",
            content=result.message,
            msg_type="feedback",
            db=db,
        )

        # Store follow-up question if exists
        if result.question:
            await append_to_conversation(
                session_id=session.id,
                role="assistant",
                content=result.question,
                msg_type="question",
                db=db,
            )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error evaluating answer: {str(e)}",
        )
    # this is dummy response.
    # return AnswerEvalResponse(
    #     message="This is the message",
    #     can_proceed=True,
    #     question="This is from question",
    #     conversation_id="dummy_id 123",
    # )
