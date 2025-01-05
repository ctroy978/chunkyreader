from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List
from pydantic import BaseModel
from database import get_session
from models import User, AdminPrivilege, Text
from auth.dependencies import get_current_user
from datetime import datetime, timezone

router = APIRouter(prefix="/admin", tags=["admin"])


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_teacher: bool
    is_admin: bool


class PrivilegeRequest(BaseModel):
    user_id: int
    reason: str


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    """List all users with their roles and privileges"""
    # Check if current user is admin
    admin_check = db.exec(
        select(AdminPrivilege).where(
            AdminPrivilege.user_id == current_user.id, AdminPrivilege.is_active == True
        )
    ).first()

    if not admin_check:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can list users"
        )

    # Get all users with their admin status
    statement = select(User, AdminPrivilege).outerjoin(
        AdminPrivilege,
        (User.id == AdminPrivilege.user_id) & (AdminPrivilege.is_active == True),
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
    """Delete a user from the system"""
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

    # Delete associated records first (AdminPrivilege, ReadingSession, etc.)
    # Then delete the user
    try:
        # Delete AdminPrivilege records
        admin_privs = select(AdminPrivilege).where(AdminPrivilege.user_id == user_id)
        for priv in db.exec(admin_privs):
            db.delete(priv)

        # Delete the user
        db.delete(user)
        db.commit()
        return {"message": f"User {user.username} deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {str(e)}",
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
