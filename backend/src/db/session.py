from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from src.core.config import settings
# Registers the after_begin hook that re-applies the tenant context per transaction.
import src.db.tenant_context  # noqa: F401,E402

# The application's connection. In shared hosting this is the non-owner
# invoicing_app role, so Postgres row-level security applies to every query it
# runs (see src/db/rls.py and src/db/tenant_context.py).
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# The owner's connection, for what must not be filtered by row-level security:
# DDL (create_all and migrations on boot), pg_dump and restore, and the backup
# email. A dump taken through the policies would succeed and silently omit every
# row outside the (empty) tenant context. Without MIGRATION_DATABASE_URL it is
# simply the application engine, which is what every single-tenant deployment
# has always used for all of the above.
migration_engine = (
    create_engine(settings.MIGRATION_DATABASE_URL)
    if settings.MIGRATION_DATABASE_URL
    else engine
)
OwnerSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=migration_engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except SQLAlchemyError:
            # During restore the underlying connection may be invalidated; avoid
            # converting cleanup errors into endpoint failures.
            pass
