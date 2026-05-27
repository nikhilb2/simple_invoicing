from datetime import datetime
from pydantic import BaseModel


class LedgerAddressCreate(BaseModel):
    label: str
    address: str
    is_default: bool = False


class LedgerAddressUpdate(BaseModel):
    label: str | None = None
    address: str | None = None
    is_default: bool | None = None


class LedgerAddressOut(BaseModel):
    id: int
    ledger_id: int
    company_id: int
    label: str
    address: str
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ShippingAddressInline(BaseModel):
    """Represents a new shipping address entered inline during invoicing.
    It will be auto-saved to ledger_addresses and snapshotted onto the invoice."""
    label: str
    address: str
