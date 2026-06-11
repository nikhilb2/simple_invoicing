"""Tests for Company Settings Enhancements (#370):
- Logo upload / remove / optimization
- Terms & Conditions CRUD + serial numbering re-sequencing
- Additional company info
"""
import base64
import struct
import zlib

from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.db.session import get_db
from src.models.user import User, UserRole
from src.models.global_settings import GlobalSettings
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _company_payload(name: str, gst: str = ""):
    return {
        "name": name,
        "address": "",
        "gst": gst,
        "phone_number": "",
        "currency_code": "USD",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _ensure_admin_user(db: Session) -> User:
    user = db.query(User).filter(User.email == "test@example.com").first()
    if user:
        user.role = UserRole.admin
        db.commit()
        db.refresh(user)
        return user

    user = User(
        email="test@example.com",
        full_name="Test Admin",
        hashed_password="test-hash",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _override_persistent_current_user(db: Session = Depends(get_db)) -> User:
    return _ensure_admin_user(db)


def _with_persistent_user_override():
    old_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_persistent_current_user
    return old_override


def _restore_user_override(old_override):
    if old_override is None:
        app.dependency_overrides.pop(get_current_user, None)
        return
    app.dependency_overrides[get_current_user] = old_override


def _create_company(client, name: str, gst: str = "") -> int:
    response = client.post("/api/company/companies", json=_company_payload(name, gst))
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _make_minimal_png_bytes(width=2, height=2, r=255, g=0, b=0) -> bytes:
    """Create a tiny valid PNG in memory (no PIL needed)."""
    def _chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw = b''
    for _ in range(height):
        raw += b'\x00'  # filter none
        for _ in range(width):
            raw += bytes([r, g, b])
    idat = zlib.compress(raw)
    return b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', idat) + _chunk(b'IEND', b'')


def _make_large_png_bytes() -> bytes:
    """Create a PNG over 100 KB to test upload size rejection."""
    return _make_minimal_png_bytes(width=400, height=200, r=0, g=0,  b=255)


def _make_logo_upload_payload(size_kb: float = 0.5) -> dict:
    """Create a small logo upload payload within the 100 KB limit."""
    # Build a payload that's approx size_kb KB
    if size_kb <= 1:
        png = _make_minimal_png_bytes(width=10, height=10, r=0, g=128,  b=255)
    else:
        # Create proportionally bigger image to hit desired size
        dim = int((size_kb * 1024 / 100) ** 0.5) + 1  # rough estimate
        png = _make_minimal_png_bytes(width=dim, height=dim, r=0, g=128, b=255)

    return {
        "data": base64.b64encode(png).decode(),
        "mime_type": "image/png",
    }


def _make_oversized_logo_payload() -> dict:
    """Create a logo upload payload exceeding 100 KB."""
    # 105 KB of raw bytes (well over the 100 KB limit)
    junk = b'x' * (105 * 1024)
    return {
        "data": base64.b64encode(junk).decode(),
        "mime_type": "image/png",
    }


# ---------------------------------------------------------------------------
# Fixture: set default test company cap
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_default_company_cap(db_session: Session):
    settings_row = db_session.query(GlobalSettings).filter(GlobalSettings.id == 1).first()
    if not settings_row:
        settings_row = GlobalSettings(id=1, max_companies=10)
        db_session.add(settings_row)
    else:
        settings_row.max_companies = 10
    db_session.commit()


# ===========================================================================
# Logo Tests
# ===========================================================================


class TestLogoUpload:
    def test_upload_valid_logo(self, client, db_session):
        """Upload a small PNG logo successfully."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Logo Test Co")
            payload = _make_logo_upload_payload(0.5)
            resp = client.put("/api/company/logo", json=payload)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["logo_data"] is not None
            assert data["logo_mime_type"] is not None
            # Should be optimized to JPEG by Pillow
            assert data["logo_mime_type"] == "image/jpeg"
        finally:
            _restore_user_override(old_override)

    def test_remove_logo(self, client, db_session):
        """Upload then remove logo, verify it's cleared."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Logo Remove Co")
            # Upload first
            upload_resp = client.put("/api/company/logo", json=_make_logo_upload_payload(0.5))
            assert upload_resp.status_code == 200
            assert upload_resp.json()["logo_data"] is not None

            # Remove
            remove_resp = client.delete("/api/company/logo")
            assert remove_resp.status_code == 200, remove_resp.text
            data = remove_resp.json()
            assert data["logo_data"] is None
            assert data["logo_mime_type"] is None
        finally:
            _restore_user_override(old_override)

    def test_upload_logo_exceeding_100kb_rejected(self, client, db_session):
        """Upload a logo larger than 100 KB should be rejected with 400."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Logo Big Co")

            payload = _make_oversized_logo_payload()
            raw_bytes = base64.b64decode(payload["data"])
            file_size_kb = len(raw_bytes) / 1024
            assert file_size_kb > 100, f"Need >100 KB payload, got {file_size_kb:.1f} KB"

            resp = client.put("/api/company/logo", json=payload)
            assert resp.status_code == 400, resp.text
            assert "Logo size cannot exceed 100 KB" in resp.text
        finally:
            _restore_user_override(old_override)

    def test_logo_optimization_resizes_large_image(self, client, db_session):
        """A large image should be resized down and converted to JPEG."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Logo Resize Co")
            # Create a PNG that's wider than 400px
            big_png = _make_minimal_png_bytes(width=800, height=200, r=0, g=200, b=100)
            payload = {
                "data": base64.b64encode(big_png).decode(),
                "mime_type": "image/png",
            }
            resp = client.put("/api/company/logo", json=payload)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["logo_mime_type"] == "image/jpeg", (
                f"Expected JPEG after optimization, got {data['logo_mime_type']}"
            )
            # Verify the data decoded is a JPEG (starts with FF D8)
            optimized_bytes = base64.b64decode(data["logo_data"])
            assert optimized_bytes[:2] == b'\xff\xd8', (
                "Optimized image should be JPEG format (FF D8 header)"
            )
        finally:
            _restore_user_override(old_override)


# ===========================================================================
# Terms & Conditions Tests
# ===========================================================================


class TestTermsCRUD:
    def test_list_terms_empty(self, client, db_session):
        """A newly created company should have no terms."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms Empty Co")
            resp = client.get("/api/company/terms")
            assert resp.status_code == 200, resp.text
            assert resp.json() == []
        finally:
            _restore_user_override(old_override)

    def test_create_term_assigns_serial_number(self, client, db_session):
        """Creating a term should auto-assign serial_number=1."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms Create Co")
            resp = client.post("/api/company/terms", json={"content": "No Return"})
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["serial_number"] == 1
            assert data["content"] == "No Return"
            assert data["company_id"] == company_id
            assert data["id"] > 0
        finally:
            _restore_user_override(old_override)

    def test_create_multiple_terms_serials_increment(self, client, db_session):
        """Creating terms sequentially should auto-increment serial numbers."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms Multi Co")
            terms = [
                "Goods once sold will not be taken back",
                "Payment due within 30 days from invoice date",
                "Subject to Delhi jurisdiction only",
            ]
            for i, content in enumerate(terms, start=1):
                resp = client.post("/api/company/terms", json={"content": content})
                assert resp.status_code == 200, resp.text
                assert resp.json()["serial_number"] == i
                assert resp.json()["content"] == content

            # Verify list returns all three in order
            list_resp = client.get("/api/company/terms")
            assert list_resp.status_code == 200
            items = list_resp.json()
            assert len(items) == 3
            for i, item in enumerate(items, start=1):
                assert item["serial_number"] == i
        finally:
            _restore_user_override(old_override)

    def test_update_term(self, client, db_session):
        """Updating a term should change its content and keep serial."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms Update Co")
            created = client.post("/api/company/terms", json={"content": "Old term"}).json()
            term_id = created["id"]

            resp = client.put(f"/api/company/terms/{term_id}", json={"content": "Updated term"})
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["content"] == "Updated term"
            assert data["serial_number"] == created["serial_number"]
            assert data["id"] == term_id
        finally:
            _restore_user_override(old_override)

    def test_update_nonexistent_term_returns_404(self, client, db_session):
        """Updating a term that doesn't exist should return 404."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms 404 Co")
            resp = client.put("/api/company/terms/99999", json={"content": "Ghost"})
            assert resp.status_code == 404, resp.text
        finally:
            _restore_user_override(old_override)

    def test_delete_term_resequences_serials(self, client, db_session):
        """Deleting a term should re-sequence remaining serial numbers."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms Reseq Co")
            # Create 4 terms
            term_ids = []
            for content in ["A", "B", "C", "D"]:
                created = client.post("/api/company/terms", json={"content": content}).json()
                term_ids.append(created["id"])

            # Verify initial serials: 1,2,3,4
            items = client.get("/api/company/terms").json()
            assert [i["serial_number"] for i in items] == [1, 2, 3, 4]

            # Delete term at serial 2 (the "B" term)
            resp = client.delete(f"/api/company/terms/{term_ids[1]}")
            assert resp.status_code == 200, resp.text
            remaining = resp.json()
            # Should now be 3 terms with serials 1,2,3
            assert len(remaining) == 3
            assert [t["serial_number"] for t in remaining] == [1, 2, 3]
            assert [t["content"] for t in remaining] == ["A", "C", "D"]

            # Delete first term (was "A", now serial 1)
            resp = client.delete(f"/api/company/terms/{term_ids[0]}")
            assert resp.status_code == 200, resp.text
            remaining = resp.json()
            assert len(remaining) == 2
            assert [t["serial_number"] for t in remaining] == [1, 2]
            assert [t["content"] for t in remaining] == ["C", "D"]

            # Delete last term
            resp = client.delete(f"/api/company/terms/{term_ids[3]}")
            assert resp.status_code == 200, resp.text
            remaining = resp.json()
            assert len(remaining) == 1
            assert remaining[0]["serial_number"] == 1
            assert remaining[0]["content"] == "C"
        finally:
            _restore_user_override(old_override)

    def test_delete_nonexistent_term_returns_404(self, client, db_session):
        """Deleting a term that doesn't exist should return 404."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Terms Del 404 Co")
            resp = client.delete("/api/company/terms/99999")
            assert resp.status_code == 404, resp.text
        finally:
            _restore_user_override(old_override)

    def test_terms_scoped_by_company(self, client, db_session):
        """Multiple companies should have independent term lists."""
        old_override = _with_persistent_user_override()
        try:
            co_a_id = _create_company(client, "Terms Scope A")
            co_b_id = _create_company(client, "Terms Scope B")

            # Switch to company A and add a term
            client.post("/api/company/select/{co_a_id}".format(co_a_id=co_a_id))
            client.post("/api/company/terms", json={"content": "Term for A"})

            # Switch to company B and add a different term
            client.post("/api/company/select/{co_b_id}".format(co_b_id=co_b_id))
            client.post("/api/company/terms", json={"content": "Term for B"})

            # Switch back to A and verify only A's term is visible
            client.post("/api/company/select/{co_a_id}".format(co_a_id=co_a_id))
            terms_a = client.get("/api/company/terms").json()
            assert len(terms_a) == 1
            assert terms_a[0]["content"] == "Term for A"

            # List B's terms
            client.post("/api/company/select/{co_b_id}".format(co_b_id=co_b_id))
            terms_b = client.get("/api/company/terms").json()
            assert len(terms_b) == 1
            assert terms_b[0]["content"] == "Term for B"
        finally:
            _restore_user_override(old_override)


# ===========================================================================
# Additional Company Info Tests
# ===========================================================================


class TestAdditionalCompanyInfo:
    def test_update_additional_info_via_company_upsert(self, client, db_session):
        """Setting additional_company_info via PUT /company should persist."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "AddInfo Co")

            update_payload = _company_payload("AddInfo Co")
            update_payload["additional_company_info"] = (
                "ABC Enterprises Pvt. Ltd.\n"
                "Authorized Distributor of Industrial Products\n"
                "GSTIN: 07ABCDE1234F1Z5"
            )
            resp = client.put("/api/company/", json=update_payload)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["additional_company_info"] == update_payload["additional_company_info"]

            # Verify it persists on GET
            get_resp = client.get("/api/company/")
            assert get_resp.status_code == 200
            assert get_resp.json()["additional_company_info"] == update_payload["additional_company_info"]
        finally:
            _restore_user_override(old_override)

    def test_additional_info_defaults_to_null(self, client, db_session):
        """A new company should have additional_company_info=None."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "AddInfo Null Co")
            resp = client.get("/api/company/")
            assert resp.status_code == 200, resp.text
            assert resp.json()["additional_company_info"] in (None, "")
        finally:
            _restore_user_override(old_override)

    def test_clear_additional_info(self, client, db_session):
        """Setting additional_company_info back to None should clear it."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "AddInfo Clear Co")

            # Set it
            update_payload = _company_payload("AddInfo Clear Co")
            update_payload["additional_company_info"] = "Some info here"
            client.put("/api/company/", json=update_payload)

            # Clear it
            update_payload["additional_company_info"] = None
            resp = client.put("/api/company/", json=update_payload)
            assert resp.status_code == 200, resp.text
            assert resp.json()["additional_company_info"] is None
        finally:
            _restore_user_override(old_override)


# ===========================================================================
# Combined: Logo + Terms + Additional Info appear in company profile
# ===========================================================================


class TestCompanyProfileOutput:
    def test_company_profile_includes_all_new_fields(self, client, db_session):
        """The company profile response should include logo, terms, additional_info."""
        old_override = _with_persistent_user_override()
        try:
            company_id = _create_company(client, "Full Profile Co")

            # Add logo
            client.put("/api/company/logo", json=_make_logo_upload_payload(0.5))

            # Add terms
            client.post("/api/company/terms", json={"content": "Term 1"})
            client.post("/api/company/terms", json={"content": "Term 2"})

            # Add additional info
            update_payload = _company_payload("Full Profile Co")
            update_payload["additional_company_info"] = "Company tagline"
            client.put("/api/company/", json=update_payload)

            # Verify all fields in profile
            resp = client.get("/api/company/")
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["logo_data"] is not None
            assert data["logo_mime_type"] is not None
            assert len(data["terms"]) == 2
            assert data["terms"][0]["serial_number"] == 1
            assert data["terms"][1]["serial_number"] == 2
            assert data["additional_company_info"] == "Company tagline"
        finally:
            _restore_user_override(old_override)
