from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from sqlmodel import Session, select, update
from .dependencies import pwd_context
import secrets
import string
from models import User
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

MAX_OTP_ATTEMPTS = 3

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

# Initialize FastMail
fastmail = FastMail(conf)


class OTPHandler:
    def __init__(self, db: Session):
        self.db = db
        self._attempt_store = {}  # Store attempt counts in memory

    async def generate_otp(self) -> str:
        """Generate a 6-character OTP using letters and numbers."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(6))

    async def store_otp(self, email: str, otp: str) -> None:
        """Store hashed OTP in user's hashed_password field."""
        hashed_otp = pwd_context.hash(otp)

        # Reset attempt counter when storing new OTP
        self._attempt_store[email] = 0

        # Update the user's hashed_password with the hashed OTP
        statement = (
            update(User).where(User.email == email).values(hashed_password=hashed_otp)
        )
        self.db.exec(statement)
        self.db.commit()

    async def verify_otp(self, email: str, otp: str) -> bool:
        """Verify if the provided OTP matches the stored hash."""
        # Get current attempt count
        attempts = self._attempt_store.get(email, 0)

        if attempts >= MAX_OTP_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Maximum attempts exceeded. "
                    "Please request a new OTP by calling /auth/request-otp"
                ),
            )

        user = self.db.exec(select(User).where(User.email == email)).first()
        if not user:
            return False

        # Verify the OTP against the stored hash
        is_valid = pwd_context.verify(otp, user.hashed_password)

        if is_valid:
            # Clear attempt counter and invalidate OTP after successful verification
            if email in self._attempt_store:
                del self._attempt_store[email]
            statement = (
                update(User)
                .where(User.email == email)
                .values(hashed_password=pwd_context.hash(secrets.token_hex(32)))
            )
            self.db.exec(statement)
            self.db.commit()
        else:
            # Increment attempt counter
            self._attempt_store[email] = attempts + 1
            remaining_attempts = MAX_OTP_ATTEMPTS - (attempts + 1)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid OTP. {remaining_attempts} attempts remaining. "
                    f"After {MAX_OTP_ATTEMPTS} failed attempts, you'll need to request a new OTP."
                ),
            )

        return is_valid

    async def send_otp_email(self, email: str, otp: str) -> None:
        """Send OTP via email."""
        message = MessageSchema(
            subject="Your Login Code",
            recipients=[email],
            body=f"""
            <html>
                <body>
                    <h2>Your Login Code</h2>
                    <p>Your temporary login code is: <strong>{otp}</strong></p>
                    <p>You have {MAX_OTP_ATTEMPTS} attempts to enter this code correctly.</p>
                    <p>If you exceed the maximum attempts, you can always request a new code.</p>
                    <p>If you didn't request this code, please ignore this email.</p>
                </body>
            </html>
            """,
            subtype="html",
        )
        await fastmail.send_message(message)

    async def handle_login_request(self, email: str) -> dict:
        """Handle the complete OTP login request flow."""
        # Verify user exists
        user = self.db.exec(select(User).where(User.email == email)).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Generate and store OTP
        otp = await self.generate_otp()
        await self.store_otp(email, otp)

        # Send OTP email
        await self.send_otp_email(email, otp)

        return {
            "message": "OTP sent successfully",
            "note": f"You have {MAX_OTP_ATTEMPTS} attempts to enter the code correctly. If you exceed this, you can request a new code.",
        }
