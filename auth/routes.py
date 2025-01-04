from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from typing import Optional

# from datetime import timedelta
from pydantic import BaseModel, EmailStr
from models import User, AdminPrivilege
from sqlmodel import Session, select
from .dependencies import pwd_context  # for password hashing
import secrets  # for generating random tokens
import string  # for generating verification code
from datetime import datetime, timedelta, timezone  # for timestamp handling
from fastapi_mail import MessageSchema
from .otp import fastmail  # Add this import
from sqlalchemy import and_

from database import get_session
from .dependencies import (
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_user,
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
    otp_handler = OTPHandler(db)
    is_valid = await otp_handler.verify_otp(verify_data.email, verify_data.otp)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OTP"
        )

    # Get the user to include username and check admin status
    statement = (
        select(User, AdminPrivilege)
        .outerjoin(
            AdminPrivilege,
            and_(User.id == AdminPrivilege.user_id, AdminPrivilege.is_active == True),
        )
        .where(User.email == verify_data.email)
    )

    result = db.exec(statement).first()
    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    user, admin_privilege = result

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": verify_data.email,
            "username": user.username,
            "is_teacher": user.is_teacher,
            "admin_privilege": admin_privilege is not None,
        },
        expires_delta=access_token_expires,
    )

    return Token(access_token=access_token, token_type="bearer")


class UserResponse(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    is_teacher: bool


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        is_teacher=current_user.is_teacher,
    )


#######


class InitialRegistration(BaseModel):
    username: str
    email: EmailStr
    full_name: str


class CompleteRegistration(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    verification_code: str


# Store pending registrations temporarily
pending_registrations = {}


@router.post("/initiate-registration")
async def initiate_student_registration(
    registration: InitialRegistration, db: Session = Depends(get_session)
):
    """Start the registration process by sending verification code"""
    # Check if username already exists
    existing_user = db.exec(
        select(User).where(User.username == registration.username)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email already exists
    existing_email = db.exec(
        select(User).where(User.email == registration.email)
    ).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Generate verification code
    verification_code = "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(6)
    )

    # Store pending registration
    pending_registrations[registration.email] = {
        "username": registration.username,
        "full_name": registration.full_name,
        "verification_code": verification_code,
        "timestamp": datetime.now(timezone.utc),
    }

    # Send verification email
    message = MessageSchema(
        subject="Verify Your Student Reader Registration",
        recipients=[registration.email],
        body=f"""
        <html>
            <body>
                <h2>Verify Your Registration</h2>
                <p>Your verification code is: <strong>{verification_code}</strong></p>
                <p>This code will expire in 15 minutes.</p>
                <p>If you didn't request this registration, please ignore this email.</p>
            </body>
        </html>
        """,
        subtype="html",
    )

    await fastmail.send_message(message)

    return {"message": "Verification code sent to email"}


@router.post("/complete-registration", response_model=UserResponse)
async def complete_student_registration(
    registration: CompleteRegistration, db: Session = Depends(get_session)
):
    """Complete registration with verification code"""
    # Check if we have a pending registration for this email
    pending = pending_registrations.get(registration.email)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending registration found",
        )

    # Check if verification code has expired (15 minutes)
    if (datetime.now(timezone.utc) - pending["timestamp"]) > timedelta(minutes=15):
        del pending_registrations[registration.email]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    # Verify the code
    if registration.verification_code != pending["verification_code"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
        )

    # Create the user
    user = User(
        username=registration.username,
        email=registration.email,
        full_name=registration.full_name,
        hashed_password=pwd_context.hash(secrets.token_hex(32)),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Clean up pending registration
    del pending_registrations[registration.email]

    return UserResponse(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_teacher=user.is_teacher,
    )
