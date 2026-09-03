"""Wire shapes for share-link management.

Note what is NOT here: nothing that describes the document itself. The management
API hands the owner a token and some counters; the *public* page renders a
deliberately narrow ``ShareSummary`` (see ``src.services.share_documents``) rather
than any of the richer Out schemas, which carry payment history and internal ids.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ShareResourceType = Literal["invoice", "ledger_statement", "payment"]


class ShareLinkCreate(BaseModel):
    resource_type: ShareResourceType
    resource_id: int
    # Statements only. Ignored (and stored as NULL) for invoices and receipts.
    from_date: date | None = None
    to_date: date | None = None


class ShareLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    url: str
    resource_type: str
    resource_id: int
    from_date: date | None = None
    to_date: date | None = None
    view_count: int
    last_viewed_at: datetime | None = None
    created_at: datetime | None = None
