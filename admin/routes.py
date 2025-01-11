from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select, and_
from typing import List, Optional
from pydantic import BaseModel
from database import get_session
from models import User, AdminPrivilege, Text, ReadingSession
from auth.dependencies import get_current_user
from datetime import datetime, timezone

router = APIRouter(prefix="/admin", tags=["admin"])


class PrivilegeRequest(BaseModel):
    user_id: int
    reason: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_teacher: bool
    is_admin: bool
    is_deleted: bool  # Added this field
    deleted_at: Optional[datetime]  # Added this field


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    """List all users with their roles and privileges, including deleted ones"""
    # Check if current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            and_(
                AdminPrivilege.user_id == current_user.id,
                AdminPrivilege.is_active == True,
            )
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can list users"
        )

    # Get all users with their admin status - removed the is_deleted filter
    statement = select(User, AdminPrivilege).outerjoin(
        AdminPrivilege,
        and_(User.id == AdminPrivilege.user_id, AdminPrivilege.is_active == True),
    )
    results = db.exec(statement).all()

    return [
        UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_teacher=user.is_teacher,
            is_admin=admin is not None,
            is_deleted=user.is_deleted,  # Added this field
            deleted_at=user.deleted_at,  # Added this field
        )
        for user, admin in results
    ]


@router.post("/grant-admin")
async def grant_admin_privileges(
    request: PrivilegeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Grant admin privileges to a user"""
    # Verify current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can grant admin privileges",
        )

    # Get target user
    user = db.get(User, request.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Check if already admin
    existing_admin = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == request.user_id, AdminPrivilege.is_active == True
        )
    ).first()

    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is already an admin"
        )

    # Create new admin privilege
    new_admin = AdminPrivilege(
        user_id=request.user_id,
        granted_by_id=current_user.id,
        grant_reason=request.reason,
        granted_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db.add(new_admin)
    db.commit()

    return {"message": "Admin privileges granted successfully"}


@router.post("/revoke-admin/{user_id}")
async def revoke_admin_privileges(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Revoke admin privileges from a user"""
    # Verify current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can revoke admin privileges",
        )

    # Cannot revoke own admin privileges
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke your own admin privileges",
        )

    # Get target admin privilege
    admin_privilege = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == user_id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_privilege:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User is not an active admin"
        )

    # Deactivate admin privilege
    admin_privilege.is_active = False
    db.commit()

    return {"message": "Admin privileges revoked successfully"}


@router.post("/toggle-teacher/{user_id}")
async def toggle_teacher_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Toggle teacher status for a user"""
    # Verify current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can modify teacher status",
        )

    # Get target user
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Toggle teacher status
    user.is_teacher = not user.is_teacher
    db.commit()

    return {
        "message": f"Teacher status {'granted' if user.is_teacher else 'revoked'} successfully",
        "is_teacher": user.is_teacher,
    }


# delete user
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Soft delete a user and associated records"""
    # Verify current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete users"
        )

    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    # Get user to delete
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    try:
        current_time = datetime.now(timezone.utc)

        # Deactivate any admin privileges
        admin_privs = select(AdminPrivilege).where(
            AdminPrivilege.user_id == user_id, AdminPrivilege.is_active == True
        )
        for priv in db.exec(admin_privs):
            priv.is_active = False

        # Mark sessions as completed
        sessions = select(ReadingSession).where(
            ReadingSession.user_id == user_id, ReadingSession.is_completed == False
        )
        for session in db.exec(sessions):
            session.is_completed = True

        # If user is a teacher, soft delete their texts
        if user.is_teacher:
            texts = select(Text).where(
                Text.teacher_id == user_id, Text.is_deleted == False
            )
            for text in db.exec(texts):
                text.is_deleted = True
                text.deleted_at = current_time

        # Add soft delete fields to User model if they don't exist
        # (You'll need to add these to your User model)
        if hasattr(user, "is_deleted"):
            user.is_deleted = True
        if hasattr(user, "deleted_at"):
            user.deleted_at = current_time

        # We can also optionally mark the email as deleted
        # to allow the same email to be used again
        user.email = f"DELETED_{user.email}_{current_time.timestamp()}"

        db.commit()
        return {
            "message": f"User {user.username} and associated data marked as deleted"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {str(e)}",
        )


@router.post("/users/{user_id}/restore")
async def restore_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Restore a soft-deleted user"""
    # Verify current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can restore users",
        )

    # Get user to restore
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not deleted"
        )

    try:
        # Restore the user's email to its original form
        if user.email.startswith("DELETED_"):
            # Extract original email from the deletion format
            email_parts = user.email.split("_")
            if len(email_parts) >= 3:
                user.email = "_".join(
                    email_parts[1:-1]
                )  # Remove DELETED_ prefix and timestamp

        # Restore user and their data
        user.is_deleted = False
        user.deleted_at = None

        # If user was a teacher, restore their texts
        if user.is_teacher:
            texts = select(Text).where(Text.teacher_id == user_id)
            for text in db.exec(texts):
                if (
                    text.is_deleted and text.deleted_at
                ):  # Only restore texts deleted when user was deleted
                    if (
                        abs((text.deleted_at - user.deleted_at).total_seconds()) < 1
                    ):  # Within 1 second
                        text.is_deleted = False
                        text.deleted_at = None

        db.commit()
        return {
            "message": f"User {user.username} and associated data restored successfully"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error restoring user: {str(e)}",
        )


@router.delete("/texts/{text_id}")
async def admin_delete_text(
    text_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Admin soft delete for texts"""
    # Verify current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete texts"
        )

    # Get text
    text = db.get(Text, text_id)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Text not found"
        )

    # Implement soft delete
    text.is_deleted = True
    text.deleted_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Text successfully deleted", "text_id": text_id}
