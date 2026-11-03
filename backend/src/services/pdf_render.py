"""What a PDF being rendered may load.

Documents are built from tenant-supplied text, so a stray tag in one must not be able
to pull a server file or an internal URL into the PDF. Everything a template legitimately
embeds (logos, QR codes) is already a data: URI, so nothing else is ever fetched.
"""

from weasyprint.urls import default_url_fetcher


def safe_url_fetcher(url: str, *args, **kwargs):
    if url.startswith("data:"):
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError("PDF rendering only loads data: URLs")
