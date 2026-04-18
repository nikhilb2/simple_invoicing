from src.core.security import get_password_hash, verify_password
from src.models.user import User, UserRole
from tests.conftest import TestingSessionLocal


def _seed_user(email: str = "test@example.com", password: str = "OldPass@123") -> User:
    db = TestingSessionLocal()
    try:
        user = User(
            email=email,
            full_name="Test User",
            role=UserRole.admin,
            hashed_password=get_password_hash(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def test_change_password_success(client):
    seeded = _seed_user()

    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "OldPass@123", "new_password": "NewPass@456"},
    )

    assert response.status_code == 200
    assert response.json()["detail"] == "Password updated successfully"

    db = TestingSessionLocal()
    try:
        updated = db.query(User).filter(User.id == seeded.id).first()
        assert updated is not None
        assert verify_password("NewPass@456", str(updated.hashed_password))
    finally:
        db.close()


def test_change_password_rejects_wrong_current_password(client):
    _seed_user()

    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "WrongPass@000", "new_password": "NewPass@456"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect"


def test_change_password_rejects_same_password(client):
    _seed_user()

    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "OldPass@123", "new_password": "OldPass@123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "New password must be different from current password"
