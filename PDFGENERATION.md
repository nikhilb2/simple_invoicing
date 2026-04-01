# PDF Invoice Generation

The backend generates downloadable PDF invoices using **WeasyPrint**, an HTML/CSS-to-PDF rendering library. The PDF layout mirrors the frontend invoice preview template exactly.

## How it works

1. The frontend sends `GET /api/invoices/{id}/pdf` with the auth token.
2. The backend builds a self-contained HTML document with inline CSS that matches the invoice preview layout (company header, bill-to section, line items table, payment details, tax breakup).
3. WeasyPrint renders the HTML to a PDF on A4 paper.
4. The PDF is returned as a streaming download (`Content-Disposition: attachment`).
5. The frontend creates a temporary blob URL and triggers the browser download.

## API endpoint

```
GET /api/invoices/{invoice_id}/pdf
Authorization: Bearer <token>
```

Returns `application/pdf` with filename `invoice_INV-XXXXXX.pdf`.

## System requirements

WeasyPrint depends on Pango and GLib system libraries for text layout and font rendering.

### macOS (local development)

```bash
brew install pango
```

This pulls in all required dependencies (GLib, HarfBuzz, FreeType, Cairo, etc.).

### Ubuntu / Debian (Docker, CI)

The Dockerfile already includes the required packages:

```bash
apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev
```

### Alpine Linux

```bash
apk add --no-cache pango fontconfig ttf-freefont
```

## Python dependency

Defined in `backend/requirements.txt`:

```
weasyprint==63.1
```

Install in the virtual environment:

```bash
cd backend
.venv/bin/pip install -r requirements.txt
```

## Docker

The backend Dockerfile (`backend/Dockerfile`) already installs the system libraries. No extra steps are needed — just build normally:

```bash
docker build -t simple-backend ./backend
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `OSError: cannot load library 'libgobject-2.0-0'` | Install Pango system libraries (see above) |
| `OSError: cannot load library 'libpango-1.0-0'` | Same — `brew install pango` on macOS |
| Fonts look wrong or use fallback glyphs | Install a font package (`ttf-freefont` on Alpine, `fonts-liberation` on Debian) |
| Currency symbols (₹, €, £) missing | Ensure a Unicode-capable font is available on the system |
| PDF is blank | Check WeasyPrint logs for CSS parsing errors — run the backend with `LOG_LEVEL=debug` |

## Customising the template

The HTML template is defined in `backend/src/api/routes/invoices.py` in the `_build_invoice_html()` function. It uses inline CSS and mirrors the structure of the frontend's `previewInvoice` modal in `frontend/src/pages/InvoicesPage.tsx`. To change the PDF layout, edit the HTML/CSS in that function.
