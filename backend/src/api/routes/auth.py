from fastapi import APIRouter, Depends, HTTPException, Response
from jose import JWTError
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.models.user import User
from src.schemas.auth import ChangePasswordRequest, ChangePasswordResponse, LoginRequest, RefreshRequest, Token
from src.schemas.user import UserOut
from src.core.security import verify_password, create_access_token, create_refresh_token, decode_token, get_password_hash
from src.api.deps import get_current_user
from src.core.analytics import distinct_id_for, track

router = APIRouter()


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        # Without this, a spike in failed sign-ins looks exactly like people
        # simply not showing up. The reason separates "wrong password, tell
        # support to reset it" from "typed the wrong address" -- and for an
        # address that is not an account, $process_person_profile keeps PostHog
        # from minting a person out of a stranger's typo or an enumeration probe.
        track(
            "login_failed",
            payload.email,
            {
                "reason": "unknown_email" if not user else "bad_password",
                **({} if user else {"$process_person_profile": False}),
            },
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(subject=user.email)
    refresh_token = create_refresh_token(subject=user.email)

    # $set rides along on the event rather than going out as its own person
    # update: role and active company are wanted for segmenting, and login is
    # the moment they are known to be current.
    track(
        "user_logged_in",
        distinct_id_for(user),
        {
            "$set": {
                "email": user.email,
                "role": getattr(user.role, "value", user.role),
                "active_company_id": user.active_company_id,
            },
        },
    )
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


# Deliberately out of the OpenAPI schema: the MCP registry turns every documented
# operation into a callable tool (src/mcp_server/registry.py), and "log the user
# out" is not an action an LLM should be able to take. The browser calls it so
# that signing out is counted where every other event is counted -- on the
# server -- rather than being the one event left behind in the bundle.
@router.post("/logout", status_code=204, include_in_schema=False)
def logout(current_user: User = Depends(get_current_user)):
    track("user_logged_out", distinct_id_for(current_user))
    return Response(status_code=204)


@router.post("/refresh", response_model=Token)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        decoded = decode_token(payload.refresh_token)
    except JWTError:
        raise credentials_exception

    if decoded.get("type") != "refresh":
        raise credentials_exception

    email = decoded.get("sub")
    if not email:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise credentials_exception

    access_token = create_access_token(subject=user.email)
    new_refresh_token = create_refresh_token(subject=user.email)
    return {"access_token": access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.email == current_user.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    user.hashed_password = get_password_hash(payload.new_password)
    db.add(user)
    db.commit()

    return {"detail": "Password updated successfully"}
