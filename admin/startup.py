from sqlmodel import Session, select
from models import User, AdminPrivilege
from database import engine
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)


async def setup_initial_admin():
    """
    Check if initial admin needs to be created based on environment variable.
    This should run during application startup.
    """
    load_dotenv()
    initial_admin_email = os.getenv("INITIAL_ADMIN_EMAIL")

    if not initial_admin_email:
        logger.info("No INITIAL_ADMIN_EMAIL set, skipping admin setup")
        return

    with Session(engine) as db:
        # Check if any admins exist
        existing_admin = db.exec(select(AdminPrivilege)).first()
        if existing_admin:
            logger.info("Admins already exist, skipping initial admin setup")
            return

        # Find user with matching email
        user = db.exec(select(User).where(User.email == initial_admin_email)).first()
        if not user:
            logger.warning(
                f"Initial admin email {initial_admin_email} not found in users"
            )
            return

        # Create admin privilege
        try:
            admin = AdminPrivilege(
                user_id=user.id,
                grant_reason="Initial system administrator (environment configuration)",
            )
            db.add(admin)
            db.commit()
            logger.info(f"Successfully created initial admin: {user.email}")

        except Exception as e:
            logger.error(f"Failed to create initial admin: {str(e)}")
            db.rollback()
