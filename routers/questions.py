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

router = APIRouter(prefix="/questions", tags=["questions"])

load_dotenv()

# Define all models at the top of your file or module


class BuildQuestion(BaseModel):
    question: str = Field(
        ...,
        description="A question designed to test the student's reading comprehension of the reading material.",
    )


class AnswerEvalResponse(BaseModel):
    message: str = Field(..., description="Evaluation of the student's answer")
    can_proceed: bool = Field(
        ..., description="Does the student understand well enough to move forward."
    )
    question: Union[str, None] = Field(
        ..., description="A follow up question if the student needs more guidance."
    )
    conversation_id: str


# Here, you've already defined your models. Now, use them in your agent setup:

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
            "You are a reading teacher."
            "When given a chunk of text, you will develop a challenging reading comprehension question based on that text."
            "When you are given an answer, you will evaluate the answer. If the answer is unacceptable, you will develop a follow up question."
            "When evaluating the answer, you will decide whether or not a student can proceed to the next reading assignment."
            "Use the student's name when asking questions or providing feedback."
        ),
    )


gen_agent = create_agent("buildquestion")
eval_agent = create_agent("answerevalresponse")


@gen_agent.system_prompt
def add_the_users_name(ctx: RunContext[str]) -> str:
    return f"The user's name is {ctx.deps}."


class QuestionRequest(BaseModel):
    chunk_id: int
    text_id: int
    user_email: str


class QuestionResponse(BaseModel):
    question: str


def get_username(email: str, db: Session = Depends(get_session)) -> str:
    statement = select(User).where(User.email == email)
    user = db.exec(statement).first()
    return user.username


# student sends the reading chunk here and the first question is returned.
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Text Chunk not found"
        )

    # Store the chunk text in a variable
    chunk_text = chunk.content

    # get the username of the student
    statement = select(User).where(User.email == request.user_email)
    user = db.exec(statement).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )

    # TODO check for current session. If one exists, add to it. If it doesnt, creat it

    # develop question

    current_question = await get_question(chunk_text, user.username)

    return QuestionResponse(question=f"{current_question}?")


async def get_question(chunk: str, username: str) -> str:
    # Construct the query
    query = f"Reading sample: '{chunk}'. Analyze the reading sample and develop a reading comprehension question from the passage. Ask the student to answer your question."
    result = await gen_agent.run(query, deps=username)

    return result.data


####submit work test zone #######


# After a question is answered, these models come into play.
class AnswerEvalRequest(BaseModel):
    chunk_id: int
    text_id: int
    user_email: str
    answer: str
    current_question: str


@router.post("/evaluate-answer", response_model=AnswerEvalResponse)
async def evaluate_answer(
    request: AnswerEvalRequest, db: Session = Depends(get_session)
):
    return AnswerEvalResponse(
        message="Good start, but let's explore this further.",
        can_proceed=False,
        question="Can you provide a specific example from the text to support your answer?",
        conversation_id="dummy-convo-123",
    )

    # """
    # Evaluate student's answer and determine if they can proceed.
    # This is a dummy version that alternates between proceeding and asking follow-up.
    # """
    # # This is just a dummy response - will be replaced with real AI logic
    # # For testing, let's just alternate between proceed and follow-up
    # import random

    # is_satisfactory = random.choice([True, False])

    # if is_satisfactory:
    #     return AnswerEvalResponse(
    #         message="Excellent work! You've shown good understanding of this section.",
    #         can_proceed=True,
    #         question=None,
    #         conversation_id="dummy-convo-123",
    #     )
    # else:
    #     return AnswerEvalResponse(
    #         message="Good start, but let's explore this further.",
    #         can_proceed=False,
    #         question="Can you provide a specific example from the text to support your answer?",
    #         conversation_id="dummy-convo-123",
    # )
