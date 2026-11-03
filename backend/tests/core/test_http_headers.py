"""Content-Disposition for a download whose name comes from user-editable text."""

from urllib.parse import unquote

import pytest

from src.core.http_headers import content_disposition


@pytest.mark.parametrize(
    "disposition, filename",
    [
        ("attachment", "quotation_QT-0001.pdf"),
        ("inline", "invoice_INV/25-26/1.pdf"),
        ("attachment", "credit note (final).pdf"),
    ],
)
def test_a_name_that_already_works_is_sent_exactly_as_before(disposition, filename):
    assert content_disposition(disposition, filename) == f'{disposition}; filename="{filename}"'


@pytest.mark.parametrize(
    "filename",
    ["quotation_कोट-0001.pdf", 'quotation_Q"T-0001.pdf', "quotation_Q\\T.pdf", "quotation_é.pdf", "a\r\nX-Evil: 1.pdf"],
)
def test_anything_else_gets_an_ascii_fallback_and_an_encoded_name(filename):
    header = content_disposition("attachment", filename)

    header.encode("latin-1")  # Would raise for the response, as the old header did.
    assert "\r" not in header and "\n" not in header

    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback.isascii()
    assert fallback.endswith(".pdf")
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == filename


def test_a_name_with_nothing_ascii_still_has_a_fallback():
    assert 'filename="document.pdf"' in content_disposition("inline", "कोट.pdf")
    assert 'filename="document"' in content_disposition("inline", "कोट")
