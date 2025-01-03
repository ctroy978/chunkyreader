from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel, EmailStr
from database import get_session
from models import User
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from auth.otp import OTPHandler
import os
from dotenv import load_dotenv

load_dotenv()

# Email configuration
conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_USERNAME"),
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
)

fastmail = FastMail(conf)


class InitialRegistration(BaseModel):
    username: str
    email: EmailStr
    full_name: str


class CompleteRegistration(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    verification_code: str


async def send_registration_email(email: str, otp: str, full_name: str):
    """Send registration verification email"""
    message = MessageSchema(
        subject="Complete Your Registration",
        recipients=[email],
        body=f"""
        <html>
            <body>
                <h2>Welcome to Student Reader, {full_name}!</h2>
                <p>Your registration verification code is: <strong>{otp}</strong></p>
                <p>This code will expire in 10 minutes.</p>
                <p>If you didn't request this registration, please ignore this email.</p>
            </body>
        </html>
        """,
        subtype="html",
    )
    await fastmail.send_message(message)


@router.post("/initiate-registration")
async def initiate_registration(
    registration: InitialRegistration, db: Session = Depends(get_session)
):
    # Check if email already exists
    existing_email = db.exec(
        select(User).where(User.email == registration.email)
    ).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Check if username already exists
    existing_username = db.exec(
        select(User).where(User.username == registration.username)
    ).first()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken"
        )

    # Generate and store OTP
    otp_handler = OTPHandler(db)
    otp = await otp_handler.generate_otp()
    await otp_handler.store_otp(registration.email, otp)

    # Send registration email
    await send_registration_email(registration.email, otp, registration.full_name)

    return {
        "message": "Registration verification code sent",
        "note": "Please check your email for the verification code",
    }


@router.post("/complete-registration")
async def complete_registration(
    registration: CompleteRegistration, db: Session = Depends(get_session)
):
    # Verify OTP
    otp_handler = OTPHandler(db)
    is_valid = await otp_handler.verify_otp(
        registration.email, registration.verification_code
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )

    # Create new user
    new_user = User(
        username=registration.username,
        email=registration.email,
        full_name=registration.full_name,
        is_teacher=False,  # Default to student
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "Registration successful"}
