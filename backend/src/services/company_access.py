"""Who may reach which company, and with what role.

The one place that knows the difference between the two deployment modes:

- single_tenant: every user reaches every company with their global
  ``User.role`` -- the behaviour from before memberships existed.
- shared_hosting: a user reaches only the companies they hold a
  ``CompanyMembership`` for, and the membership role is the one that counts.

Callers should ask these helpers rather than check ``settings.DEPLOYMENT_MODE``
themselves, so the rule stays in one file.
"""

from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.company_membership import CompanyMembership
from src.models.user import User, UserRole


def accessible_company_ids(db: Session, user: User) -> set[int] | None:
    """The ids of the companies ``user`` may reach, or ``None`` for "all of them"."""
    if not settings.is_shared_hosting:
        return None
    rows = (
        db.query(CompanyMembership.company_id)
        .filter(CompanyMembership.user_id == user.id)
        .all()
    )
    return {company_id for (company_id,) in rows}


def can_access_company(db: Session, user: User, company_id: int) -> bool:
    """Whether ``user`` may reach ``company_id``.

    In single tenant this is always True; whether the company exists at all is
    left to the caller, which already 404s on an unknown id.
    """
    if not settings.is_shared_hosting:
        return True
    return _membership(db, user, company_id) is not None


def company_role(db: Session, user: User, company_id: int) -> UserRole | None:
    """The role ``user`` acts with inside ``company_id``; ``None`` means no access."""
    if not settings.is_shared_hosting:
        return user.role
    membership = _membership(db, user, company_id)
    return membership.role if membership else None


def first_accessible_company(db: Session, user: User) -> CompanyProfile | None:
    """The company a shared-hosting user lands in when none is selected.

    Their oldest membership, so the answer is stable across logins. Never "the
    first company in the database" -- that is someone else's company.
    """
    return (
        db.query(CompanyProfile)
        .join(CompanyMembership, CompanyMembership.company_id == CompanyProfile.id)
        .filter(CompanyMembership.user_id == user.id)
        .order_by(CompanyMembership.id.asc())
        .first()
    )


def legacy_default_company(db: Session) -> CompanyProfile | None:
    """"The" company, for single-tenant callers that were handed none.

    A single-tenant database is one customer's, so its lowest-id company is a
    safe default. In shared hosting it is a stranger's: return None and let the
    caller fail rather than read or write another tenant's data.
    """
    if settings.is_shared_hosting:
        return None
    return db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()


def admin_company_count(db: Session, user: User) -> int:
    """How many companies ``user`` administers -- what MAX_COMPANIES_PER_USER caps."""
    return (
        db.query(CompanyMembership)
        .filter(
            CompanyMembership.user_id == user.id,
            CompanyMembership.role == UserRole.admin,
        )
        .count()
    )


def company_scope(column, company_id: int | None):
    """Filter clause restricting ``column`` (a ``company_id`` column) to one company.

    Single tenant keeps the historical ``company_id = :id OR company_id IS NULL``:
    rows written before company scoping existed carry NULL and still belong to
    the deployment's one owner. In shared hosting a NULL row belongs to nobody,
    so it is never shown -- and with no company at all, nothing matches.
    """
    if settings.is_shared_hosting:
        if company_id is None:
            return false()
        return column == company_id
    return or_(column == company_id, column.is_(None))


def is_platform_admin(user: User) -> bool:
    """Whether ``user`` operates the deployment itself, not just a company in it.

    Only meaningful in shared hosting, where the allowlist in
    PLATFORM_ADMIN_EMAILS is the sole way in: an empty list means nobody.
    """
    allowlist = {
        email.strip().lower()
        for email in (settings.PLATFORM_ADMIN_EMAILS or "").split(",")
        if email.strip()
    }
    return bool(user.email) and user.email.strip().lower() in allowlist


def add_membership(
    db: Session,
    user: User,
    company: CompanyProfile,
    role: UserRole,
) -> CompanyMembership:
    """Make ``user`` a member of ``company`` with ``role``.

    Idempotent: an existing membership is given the requested role rather than
    duplicated. Flushes but does not commit, so it joins the caller's transaction
    (e.g. creating a company and its first admin together).
    """
    membership = _membership(db, user, company.id)
    if membership is None:
        membership = CompanyMembership(user_id=user.id, company_id=company.id, role=role)
        db.add(membership)
    else:
        membership.role = role
    db.flush()
    return membership


def _membership(db: Session, user: User, company_id: int) -> CompanyMembership | None:
    return (
        db.query(CompanyMembership)
        .filter(
            CompanyMembership.user_id == user.id,
            CompanyMembership.company_id == company_id,
        )
        .first()
    )
