from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_ai import Agent
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/vocab", tags=["vocabulary"])


class ChatRequest(BaseModel):
    model: str
    prompt: str


# Initialize the AI agent
agent = Agent(
    "groq:llama3-8b-8192",
    system_prompt="Be concise. You are the teacher replying to your student.",
)


@router.post("/chat/{llms_name}")
async def process_chat(llms_name: str, request: ChatRequest):
    """
    Process vocabulary chat requests.
    This endpoint is separate from the main reading app functionality.
    """
    result = await agent.run(request.prompt)
    return {"data": result, "llms_name": llms_name}
