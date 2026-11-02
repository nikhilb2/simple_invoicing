"""Behaviour of the server-side PostHog wrapper.

The point of these is the failure modes, not the happy path: analytics is
optional infrastructure, and the two ways it can hurt this app are booting
differently when it is unconfigured, and letting an ingestion problem take a
request down with it.
"""

import pytest

from src.core import analytics


class RecordingClient:
    """Stands in for posthog.Posthog and remembers what it was asked to send."""

    def __init__(self):
        self.captured = []
        self.person_updates = []
        self.exceptions = []
        self.shutdown_calls = 0

    def capture(self, event, distinct_id=None, properties=None, disable_geoip=None):
        self.captured.append((event, distinct_id, properties or {}))

    def set(self, distinct_id=None, properties=None):
        self.person_updates.append((distinct_id, properties or {}))

    def capture_exception(self, exc, distinct_id=None, properties=None, disable_geoip=None):
        self.exceptions.append((exc, distinct_id, properties or {}))

    def shutdown(self):
        self.shutdown_calls += 1


class ExplodingClient(RecordingClient):
    """An ingestion host having a bad day."""

    def capture(self, *args, **kwargs):
        raise RuntimeError("ingestion unreachable")

    def set(self, *args, **kwargs):
        raise RuntimeError("ingestion unreachable")

    def capture_exception(self, *args, **kwargs):
        raise RuntimeError("ingestion unreachable")

    def shutdown(self):
        raise RuntimeError("ingestion unreachable")


@pytest.fixture(autouse=True)
def reset_analytics_state():
    """Each test starts with no client and no bound request."""
    analytics._client = None
    analytics._init_attempted = False
    analytics.bind_request(None, "api", None)
    yield
    analytics._client = None
    analytics._init_attempted = False
    analytics.bind_request(None, "api", None)


@pytest.fixture
def client(monkeypatch):
    recorder = RecordingClient()
    monkeypatch.setattr(analytics, "_client", recorder)
    monkeypatch.setattr(analytics, "_init_attempted", True)
    return recorder


def test_unconfigured_is_a_silent_no_op(monkeypatch):
    monkeypatch.setattr(analytics.settings, "POSTHOG_PROJECT_API_KEY", None)

    assert analytics.is_analytics_ready() is False
    # None of these may raise, and none may need a key to be callable.
    analytics.track("invoice_created", "a@example.com", {"invoice_id": 1})
    analytics.set_person_properties("a@example.com", {"role": "admin"})
    analytics.track_exception(RuntimeError("boom"))
    analytics.shutdown_analytics()


def test_track_sends_event_with_properties(client):
    analytics.track("invoice_created", "a@example.com", {"invoice_id": 7})

    event, distinct_id, props = client.captured[0]
    assert (event, distinct_id) == ("invoice_created", "a@example.com")
    assert props["invoice_id"] == 7


def test_track_without_a_distinct_id_is_dropped(client):
    analytics.track("invoice_created", None, {"invoice_id": 7})

    assert client.captured == []


def test_bound_session_and_client_ride_along(client):
    analytics.bind_request("session-abc", "web")
    analytics.track("invoice_created", "a@example.com")

    _, _, props = client.captured[0]
    # $session_id is what puts this event on the browser's replay timeline.
    assert props["$session_id"] == "session-abc"
    assert props["client"] == "web"


def test_caller_supplied_client_property_wins(client):
    analytics.bind_request(None, "web")
    analytics.track("invoice_created", "a@example.com", {"client": "mcp"})

    _, _, props = client.captured[0]
    assert props["client"] == "mcp"


def test_session_id_is_absent_when_the_caller_sent_none(client):
    analytics.track("invoice_created", "a@example.com")

    _, _, props = client.captured[0]
    assert "$session_id" not in props


def test_exceptions_are_captured_without_a_distinct_id(client):
    analytics.bind_request("session-abc", "web")
    error = RuntimeError("boom")

    analytics.track_exception(error, properties={"request_url": "/api/invoices"})

    exc, distinct_id, props = client.exceptions[0]
    assert exc is error
    assert distinct_id is None
    assert props["request_url"] == "/api/invoices"
    assert props["$session_id"] == "session-abc"


def test_an_unreachable_ingestion_host_never_reaches_the_caller(monkeypatch):
    monkeypatch.setattr(analytics, "_client", ExplodingClient())
    monkeypatch.setattr(analytics, "_init_attempted", True)

    # A tenant's invoice does not fail to save because PostHog is down.
    analytics.track("invoice_created", "a@example.com")
    analytics.set_person_properties("a@example.com", {"role": "admin"})
    analytics.track_exception(RuntimeError("boom"))
    analytics.shutdown_analytics()


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"X-MCP-Tool": "list_invoices"}, "mcp"),
        ({"X-PostHog-Session-Id": "session-abc"}, "web"),
        ({"X-MCP-Tool": "list_invoices", "X-PostHog-Session-Id": "s"}, "mcp"),
        ({}, "api"),
        ({"X-PostHog-Session-Id": ""}, "api"),
    ],
)
def test_client_kind_from_headers(headers, expected):
    assert analytics.client_kind_from_headers(headers) == expected


def test_distinct_id_is_the_email():
    class FakeUser:
        email = "a@example.com"

    assert analytics.distinct_id_for(FakeUser()) == "a@example.com"
    assert analytics.distinct_id_for(None) is None


def test_a_bound_caller_ip_is_what_gets_geolocated(client):
    analytics.bind_request(None, "web", "49.36.183.12")

    analytics.track("invoice_created", "a@example.com")

    _, _, props = client.captured[0]
    assert props["$ip"] == "49.36.183.12"


def test_no_bound_ip_means_no_location_rather_than_this_servers(client):
    """The pod's own address is not where anything happened."""
    analytics.bind_request(None, "api", None)

    analytics.track("invoice_created", "a@example.com")

    _, _, props = client.captured[0]
    assert "$ip" not in props


def test_geoip_is_re_enabled_only_for_events_carrying_an_ip(monkeypatch):
    calls = []

    class GeoRecordingClient(RecordingClient):
        def capture(self, event, distinct_id=None, properties=None, disable_geoip=None):
            calls.append((event, disable_geoip))

    monkeypatch.setattr(analytics, "_client", GeoRecordingClient())
    monkeypatch.setattr(analytics, "_init_attempted", True)

    analytics.bind_request(None, "web", "49.36.183.12")
    analytics.track("with_ip", "a@example.com")
    analytics.bind_request(None, "api", None)
    analytics.track("without_ip", "a@example.com")

    # False overrides the client-wide default for this one event; None leaves the
    # default (disabled) in place, so a forgotten bind cannot geolocate the pod.
    assert calls == [("with_ip", False), ("without_ip", None)]


def test_the_forwarded_header_wins_over_the_proxy_socket():
    class FakeRequest:
        def __init__(self, headers, peer):
            self.headers = headers
            self.client = type("C", (), {"host": peer})()

    behind_proxy = FakeRequest(
        {"x-forwarded-for": "49.36.183.12, 10.0.0.1, 10.0.0.2"}, "10.0.0.9"
    )
    assert analytics.client_ip_from_request(behind_proxy) == "49.36.183.12"

    direct = FakeRequest({}, "203.0.113.7")
    assert analytics.client_ip_from_request(direct) == "203.0.113.7"

    assert analytics.client_ip_from_request(FakeRequest({}, None)) is None
