from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from typing import List

from database import create_db_and_tables

from routers import addtext, student, questions, session_manager, test
from auth.routes import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(
    title="Student Reader API",
    lifespan=lifespan,
)


app.include_router(auth_router, prefix="/auth")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Your Vue dev server URL
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "accept"],
    expose_headers=["Content-Type", "Authorization"],
)

app.include_router(addtext.router)
app.include_router(student.router)
app.include_router(questions.router)
app.include_router(session_manager.router)
app.include_router(test.router)
