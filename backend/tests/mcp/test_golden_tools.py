"""The tool-name contract.

Tool names are a contract with already-connected clients: a user's saved prompt
says "use invoices_list". A route rename that shifts a name must surface here as
a reviewed diff, not as a silently broken connector.

Regenerate deliberately, never reflexively::

    DATABASE_URL=... SECRET_KEY=... .venv/bin/python -m tests.mcp.regenerate_golden
"""

from __future__ import annotations

from pathlib import Path

from app_main import app
from src.mcp_server.registry import get_registry

GOLDEN = Path(__file__).with_name("golden_tools.txt")


def format_triples(triples) -> str:
    return "".join(f"{name}\t{method}\t{path}\n" for name, method, path in triples)


def parse(text: str):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, method, path = line.split("\t")
        rows.append((name, method, path))
    return rows


def test_tool_names_match_the_golden_file():
    registry = get_registry(app)
    actual = registry.golden_triples()
    expected = parse(GOLDEN.read_text())

    actual_names = {name for name, _, _ in actual}
    expected_names = {name for name, _, _ in expected}

    added = sorted(actual_names - expected_names)
    removed = sorted(expected_names - actual_names)
    moved = sorted(
        (name, dict((n, (m, p)) for n, m, p in expected)[name], dict((n, (m, p)) for n, m, p in actual)[name])
        for name in actual_names & expected_names
        if dict((n, (m, p)) for n, m, p in expected)[name] != dict((n, (m, p)) for n, m, p in actual)[name]
    )

    assert (added, removed, moved) == ([], [], []), (
        "The MCP tool contract changed.\n"
        f"  new tools:     {added}\n"
        f"  removed tools: {removed}\n"
        f"  re-pointed:    {moved}\n"
        "Removing or re-pointing a tool breaks saved prompts in every connected client. "
        "If the change is intended, regenerate tests/mcp/golden_tools.txt and say so in the PR."
    )


def test_discovery_tools_are_not_in_the_golden_file():
    """`search`/`fetch` are hand-written, so they are not generated triples."""
    assert "search" not in {name for name, _, _ in parse(GOLDEN.read_text())}
