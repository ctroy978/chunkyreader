from fastapi import HTTPException, Depends, status
from sqlmodel import Session, select
from models import User, AdminPrivilege
from typing import Optional
from datetime import datetime, timezone


class AdminManager:
    def __init__(self, db: Session):
        self.db = db

    async def is_admin(self, user_id: int) -> bool:
        """Check if a user has active admin privileges."""
        statement = select(AdminPrivilege).where(
            AdminPrivilege.user_id == user_id, AdminPrivilege.is_active == True
        )
        result = self.db.exec(statement).first()
        return result is not None

    async def create_first_admin(self, user_id: int) -> AdminPrivilege:
        """Create the first admin in the system. Should only be used during setup."""
        # Check if any admins exist
        statement = select(AdminPrivilege)
        existing_admin = self.db.exec(statement).first()
        if existing_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create first admin: admins already exist",
            )

        admin = AdminPrivilege(
            user_id=user_id, grant_reason="Initial system administrator"
        )
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)
        return admin

    async def grant_admin(
        self, user_id: int, granting_admin_id: int, reason: str
    ) -> AdminPrivilege:
        """Grant admin privileges to a user."""
        # Verify granting user is an admin
        if not await self.is_admin(granting_admin_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can grant admin privileges",
            )

        # Check if user exists
        user = self.db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Check if user is already an admin
        existing_admin = self.db.exec(
            select(AdminPrivilege).where(AdminPrivilege.user_id == user_id)
        ).first()
        if existing_admin:
            if existing_admin.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User is already an admin",
                )
            # Reactivate if inactive
            existing_admin.is_active = True
            existing_admin.granted_by_id = granting_admin_id
            existing_admin.granted_at = datetime.now(timezone.utc)
            existing_admin.grant_reason = reason
            self.db.commit()
            self.db.refresh(existing_admin)
            return existing_admin

        # Create new admin privilege
        admin = AdminPrivilege(
            user_id=user_id, granted_by_id=granting_admin_id, grant_reason=reason
        )
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)
        return admin

    async def revoke_admin(self, user_id: int, revoking_admin_id: int) -> bool:
        """Revoke admin privileges from a user."""
        # Verify revoking user is an admin
        if not await self.is_admin(revoking_admin_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can revoke admin privileges",
            )

        # Cannot revoke your own admin privileges
        if user_id == revoking_admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot revoke your own admin privileges",
            )

        admin = self.db.exec(
            select(AdminPrivilege).where(
                AdminPrivilege.user_id == user_id, AdminPrivilege.is_active == True
            )
        ).first()

        if not admin:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User is not an active admin",
            )

        admin.is_active = False
        self.db.commit()
        return True

    async def get_admin_details(self, user_id: int) -> Optional[dict]:
        """Get detailed information about a user's admin status."""
        statement = (
            select(AdminPrivilege, User)
            .join(User, AdminPrivilege.granted_by_id == User.id, isouter=True)
            .where(AdminPrivilege.user_id == user_id)
        )

        result = self.db.exec(statement).first()
        if not result:
            return None

        admin_privilege, granting_admin = result
        return {
            "is_active": admin_privilege.is_active,
            "granted_at": admin_privilege.granted_at,
            "granted_by": granting_admin.full_name if granting_admin else "System",
            "reason": admin_privilege.grant_reason,
        }


# Dependency for FastAPI
async def get_admin_manager(db: Session = Depends(get_session)) -> AdminManager:
    return AdminManager(db)
