"""Who may reach which company, and with what role.

The one place that knows the difference between the two deployment modes:

- single_tenant: every user reaches every company with their global
  ``User.role`` -- the behaviour from before memberships existed.
- shared_hosting: a user reaches only the companies they hold a
  ``CompanyMembership`` for, and the membership role is the one that counts.

Callers should ask these helpers rather than check ``settings.DEPLOYMENT_MODE``
themselves, so the rule stays in one file.
"""

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
