"""Response headers built from text a user typed."""

import os
import re
import unicodedata
from urllib.parse import quote


def content_disposition(disposition: str, filename: str) -> str:
    """A Content-Disposition header that any filename can go in.

    Headers are Latin-1 and a double quote ends the filename, but a document number
    comes from a series prefix, which can be anything: Devanagari would raise when the
    response is built, and a quote mark would cut the name short. Those get RFC 5987's
    ``filename*`` with an ASCII ``filename`` for clients that do not read it. A name
    with nothing to escape stays exactly as it always was.
    """
    if filename.isascii() and filename.isprintable() and not set(filename) & {'"', "\\"}:
        return f'{disposition}; filename="{filename}"'

    stem, extension = os.path.splitext(filename)
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip("_")
    fallback = f"{ascii_stem or 'document'}{re.sub(r'[^A-Za-z0-9.]', '', extension)}"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
