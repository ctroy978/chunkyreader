from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from typing import Optional
from datetime import timedelta
from pydantic import BaseModel, EmailStr

from database import get_session
from .dependencies import (
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from .otp import OTPHandler

router = APIRouter(tags=["authentication"])


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    otp: str


class Token(BaseModel):
    access_token: str
    token_type: str


@router.post("/request-otp")
async def request_otp(request: OTPRequest, db: Session = Depends(get_session)) -> dict:
    """Request an OTP to be sent to the user's email."""
    otp_handler = OTPHandler(db)
    return await otp_handler.handle_login_request(request.email)


@router.post("/verify-otp", response_model=Token)
async def verify_otp(
    verify_data: OTPVerify, db: Session = Depends(get_session)
) -> Token:
    """Verify OTP and return access token if valid."""
    otp_handler = OTPHandler(db)
    is_valid = await otp_handler.verify_otp(verify_data.email, verify_data.otp)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP"
        )

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": verify_data.email}, expires_delta=access_token_expires
    )

    return Token(access_token=access_token, token_type="bearer")


@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Protected endpoint - returns current user's information"""
    return {
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_teacher": current_user.is_teacher,
    }
