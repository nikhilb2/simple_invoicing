import argparse

from src.db.session import SessionLocal
from src.db.base import Base
from src.db.session import engine
from src.models.user import User, UserRole
from src.core.security import get_password_hash

EMAIL = "admin@simple.dev"
PASSWORD = "Admin@123"
NAME = "System Admin"


def parse_args():
    parser = argparse.ArgumentParser(description="Seed admin user")
    parser.add_argument("--email", default=EMAIL, help="Admin email")
    parser.add_argument("--password", default=PASSWORD, help="Admin password")
    parser.add_argument("--name", default=NAME, help="Admin full name")
    return parser.parse_args()


def main():
    args = parse_args()

    # Ensure core tables exist when running seed directly against a fresh database.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            print("Admin already exists")
            return
        user = User(
            email=args.email,
            full_name=args.name,
            hashed_password=get_password_hash(args.password),
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        print(f"Created admin: {args.email} / {args.password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
