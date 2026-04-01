from src.db.session import SessionLocal
from src.db.base import Base
from src.db.session import engine
from src.models.user import User, UserRole
from src.core.security import get_password_hash

EMAIL = "admin@simple.dev"
PASSWORD = "Admin@123"
NAME = "System Admin"


def main():
    # Ensure core tables exist when running seed directly against a fresh database.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == EMAIL).first()
        if existing:
            print("Admin already exists")
            return
        user = User(
            email=EMAIL,
            full_name=NAME,
            hashed_password=get_password_hash(PASSWORD),
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        print(f"Created admin: {EMAIL} / {PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
