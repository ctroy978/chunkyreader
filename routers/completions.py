from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from typing import List, Optional
from database import get_session
from models import ReadingCompletion, User, Text
from auth.dependencies import get_current_teacher
from datetime import datetime, timedelta

router = APIRouter(prefix="/completions", tags=["completions"])


class CompletionResponse:
    """Response model for completion records"""

    def __init__(self, completion: ReadingCompletion, student: User, text: Text):
        self.id = completion.id
        self.student_name = student.full_name
        self.student_email = student.email
        self.text_title = text.title
        self.completed_at = completion.completed_at
        self.passed = completion.passed
        self.ai_feedback = completion.ai_feedback
        self.correct_answers = completion.correct_answers


@router.get("/")
async def get_completions(
    student_name: Optional[str] = Query(None),
    text_title: Optional[str] = Query(None),
    passed: Optional[bool] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_session),
    _: User = Depends(get_current_teacher),
):
    """
    Get completion records with optional filters.
    Returns most recent completions first.
    """
    query = (
        select(ReadingCompletion, User, Text)
        .join(User, ReadingCompletion.student_id == User.id)
        .join(Text, ReadingCompletion.text_id == Text.id)
    )

    # Apply filters with proper handling
    if student_name and student_name.strip():  # Check if not empty string
        query = query.where(User.full_name.ilike(f"%{student_name.strip()}%"))

    if text_title and text_title.strip():  # Check if not empty string
        query = query.where(Text.title.ilike(f"%{text_title.strip()}%"))

    if passed is not None:  # Already handled by FastAPI's bool conversion
        query = query.where(ReadingCompletion.passed == passed)

    if from_date:
        # Ensure start of day
        from_date = datetime.combine(from_date.date(), datetime.min.time())
        query = query.where(ReadingCompletion.completed_at >= from_date)

    if to_date:
        # Ensure end of day
        to_date = datetime.combine(to_date.date(), datetime.max.time())
        query = query.where(ReadingCompletion.completed_at <= to_date)

    # Order by most recent first
    query = query.order_by(ReadingCompletion.completed_at.desc())

    # Apply pagination
    query = query.offset(skip).limit(limit)

    results = db.exec(query).all()

    return [
        CompletionResponse(completion, student, text)
        for completion, student, text in results
    ]
