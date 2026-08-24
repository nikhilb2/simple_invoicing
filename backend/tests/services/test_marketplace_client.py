"""Unit tests for the outbound HTTP client — retry policy, error mapping, SSRF.

Pure unit: every case drives ``httpx.MockTransport``, so nothing here opens a
socket or depends on the fake marketplace.
"""

import httpx
import pytest

from src.core.config import settings
from src.services.marketplace.client import (
    CLIENT_VERSION,
    MarketplaceAuthError,
    MarketplaceClient,
    MarketplaceConflict,
    MarketplaceError,
    MarketplaceUnavailable,
    validate_base_url,
)


class Recorder:
    """Counts attempts and replays a scripted sequence of outcomes."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.outcomes[min(len(self.requests) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def attempts(self) -> int:
        return len(self.requests)


def make_client(handler, sleeps=None, **kwargs):
    return MarketplaceClient(
        "http://marketplace.test",
        "mk_live_deadbeef",
        instance_uuid="inst-1",
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        **kwargs,
    )


def ok(payload=None, status=200):
    return httpx.Response(status, json=payload if payload is not None else {"ok": True})


def err(status, code, **extra):
    return httpx.Response(status, json={"error": code, "detail": code, **extra})


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

class TestRetries:
    def test_connect_error_retries_twice_then_succeeds(self):
        recorder = Recorder(
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            ok({"status": "ok"}),
        )
        sleeps = []
        client = make_client(recorder, sleeps)
        assert client.get_health() == {"status": "ok"}
        assert recorder.attempts == 3
        assert sleeps == [0.5, 1.5]

    def test_connect_error_exhausted_raises_unavailable(self):
        recorder = Recorder(httpx.ConnectError("refused"))
        client = make_client(recorder, [])
        with pytest.raises(MarketplaceUnavailable):
            client.get_health()
        assert recorder.attempts == 3

    def test_read_timeout_is_retried(self):
        recorder = Recorder(httpx.ReadTimeout("slow"), ok({"status": "ok"}))
        client = make_client(recorder, [])
        client.get_health()
        assert recorder.attempts == 2

    def test_server_error_is_retried(self):
        recorder = Recorder(err(503, "boom"), err(500, "boom"), ok({"status": "ok"}))
        sleeps = []
        client = make_client(recorder, sleeps)
        client.get_health()
        assert recorder.attempts == 3
        assert sleeps == [0.5, 1.5]

    def test_rate_limit_is_retried_and_honours_retry_after(self):
        responses = [
            httpx.Response(429, json={"error": "rate_limited"}, headers={"Retry-After": "2"}),
            ok({"status": "ok"}),
        ]
        recorder = Recorder(*responses)
        sleeps = []
        client = make_client(recorder, sleeps)
        client.get_health()
        assert sleeps == [2.0]

    def test_retry_after_is_capped_so_a_drain_cannot_stall(self):
        recorder = Recorder(
            httpx.Response(429, json={"error": "x"}, headers={"Retry-After": "600"}),
            ok(),
        )
        sleeps = []
        client = make_client(recorder, sleeps)
        client.get_health()
        assert sleeps == [5.0]

    def test_client_error_is_never_retried(self):
        recorder = Recorder(err(404, "not_found"))
        client = make_client(recorder, [])
        with pytest.raises(MarketplaceError):
            client.get_health()
        assert recorder.attempts == 1

    def test_post_without_idempotency_key_is_never_retried(self):
        """A replayed un-keyed POST can create a second seller/order — the server
        has no way to collapse it, so a 5xx must surface, not retry."""
        recorder = Recorder(err(503, "boom"))
        client = make_client(recorder, [])
        with pytest.raises(MarketplaceUnavailable):
            client.register_seller({"gstin": "27ABCDE1234F1Z5"})
        assert recorder.attempts == 1

    def test_post_with_idempotency_key_is_retried(self):
        recorder = Recorder(err(503, "boom"), ok({"order_id": "ord_1"}))
        client = make_client(recorder, [])
        assert client.create_order({"listing_id": "lst_1"})["order_id"] == "ord_1"
        assert recorder.attempts == 2
        assert "idempotency-key" in recorder.requests[0].headers


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

class TestErrorMapping:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_errors(self, status):
        client = make_client(Recorder(err(status, "seller_not_approved")), [])
        with pytest.raises(MarketplaceAuthError) as exc:
            client.get_me()
        assert exc.value.code == "seller_not_approved"
        assert exc.value.status_code == status

    def test_conflict_carries_the_payload(self):
        client = make_client(Recorder(err(409, "cursor_too_old", resync_from=900)), [])
        with pytest.raises(MarketplaceConflict) as exc:
            client.get_events(1)
        assert exc.value.code == "cursor_too_old"
        assert exc.value.payload["resync_from"] == 900

    def test_non_json_body_becomes_a_marketplace_error(self):
        client = make_client(Recorder(httpx.Response(200, content=b"<html>")), [])
        with pytest.raises(MarketplaceError) as exc:
            client.get_meta()
        assert exc.value.code == "bad_response"

    def test_204_decodes_to_none(self):
        client = make_client(Recorder(httpx.Response(204)), [])
        assert client.delete_me() is None


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_required_headers_are_sent(self):
        recorder = Recorder(ok())
        make_client(recorder, []).get_me()
        headers = recorder.requests[0].headers
        assert headers["authorization"] == "Bearer mk_live_deadbeef"
        assert headers["x-marketplace-client"] == f"respawn-invoicing/{CLIENT_VERSION}"
        assert headers["x-marketplace-instance"] == "inst-1"

    def test_v1_prefix_is_applied_once(self):
        recorder = Recorder(ok())
        make_client(recorder, []).get_meta()
        assert recorder.requests[0].url.path == "/v1/meta"

    def test_accept_sends_an_idempotency_key(self):
        recorder = Recorder(ok())
        make_client(recorder, []).accept_order("ord_1")
        assert recorder.requests[0].headers.get("idempotency-key")


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

class TestSsrfGuard:
    @pytest.fixture(autouse=True)
    def _strict(self, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_ALLOW_INSECURE_URL", False)
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:9000",
            "http://127.0.0.1:9000",
            "http://10.0.0.5",
            "http://192.168.1.10",
            "http://169.254.169.254",
        ],
    )
    def test_private_and_loopback_hosts_are_rejected(self, url):
        with pytest.raises(MarketplaceError) as exc:
            validate_base_url(url)
        assert exc.value.code == "blocked_base_url"

    def test_non_http_scheme_is_rejected(self):
        with pytest.raises(MarketplaceError) as exc:
            validate_base_url("file:///etc/passwd")
        assert exc.value.code == "invalid_base_url"

    def test_empty_url_is_rejected(self):
        with pytest.raises(MarketplaceError):
            validate_base_url("   ")

    def test_production_requires_https(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        with pytest.raises(MarketplaceError) as exc:
            validate_base_url("http://marketplace.example.com")
        assert exc.value.code == "insecure_base_url"

    def test_allow_insecure_opens_the_local_dev_escape_hatch(self, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_ALLOW_INSECURE_URL", True)
        assert validate_base_url("http://localhost:9000/") == "http://localhost:9000"

    def test_public_https_url_is_accepted(self, monkeypatch):
        # Stubbed so the guard is tested, not the sandbox's DNS.
        monkeypatch.setattr(
            "src.services.marketplace.client.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        assert (
            validate_base_url("https://marketplace.example.com/")
            == "https://marketplace.example.com"
        )

    def test_a_host_resolving_to_a_private_ip_is_rejected(self, monkeypatch):
        """DNS rebinding: a public-looking name pointed at 10.x is the whole
        reason the guard resolves rather than pattern-matching the hostname."""
        monkeypatch.setattr(
            "src.services.marketplace.client.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))],
        )
        with pytest.raises(MarketplaceError) as exc:
            validate_base_url("https://sneaky.example.com")
        assert exc.value.code == "blocked_base_url"

    def test_unresolvable_host_fails_closed(self, monkeypatch):
        def boom(*_a, **_k):
            raise OSError("no such host")

        monkeypatch.setattr("src.services.marketplace.client.socket.getaddrinfo", boom)
        with pytest.raises(MarketplaceError) as exc:
            validate_base_url("https://nope.example.com")
        assert exc.value.code == "unresolvable_base_url"


class TestSettings:
    def test_marketplace_settings_are_real_fields_not_getattr_holes(self):
        """Declared on Settings — `extra = "ignore"` means a getattr fallback
        would silently resolve to None forever."""
        assert "MARKETPLACE_ALLOW_INSECURE_URL" in type(settings).model_fields
        assert "MARKETPLACE_HTTP_TIMEOUT_SECONDS" in type(settings).model_fields
        assert isinstance(settings.MARKETPLACE_HTTP_TIMEOUT_SECONDS, int)
