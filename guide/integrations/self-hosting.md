---
title: "Self-host free GST billing software"
description: "Run your own copy of Simple Invoicing, the open-source GST billing software, with Docker: try it locally, then run it in production free."
---

# Run your own copy

Simple Invoicing is open source under the MIT licence. If you would rather not run a server, use the [hosted version](https://app.simpleinvoicings.com/register). This page is for people comfortable with Docker and server administration.

## Try it locally

You need [Docker](https://docs.docker.com/get-docker/) with Docker Compose.

```bash
git clone https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software.git
cd simple-invoicing-free-gst-billing-software

cp .env.example .env
cp backend/.env.example backend/.env.development
cp frontend/.env.example frontend/.env.development

make dev
make seed
```

Then open:

- App: `http://localhost:5173`
- API: `http://localhost:8000`, with docs at `/docs`

`make seed` creates the admin login `admin@simple.dev` with password `Admin@123`. **Change it straight away** in **Settings → Security**. Database changes are applied automatically when the backend starts.

## Run it in production

Use `make prod`, or `docker compose --profile prod up -d`, behind a reverse proxy with HTTPS. See [DOCKER.md](https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software/blob/main/DOCKER.md) for the details.

**Required** in `backend/.env.production`:

| Setting | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `SECRET_KEY` | A strong random value of at least 32 characters. |
| `SMTP_ENCRYPTION_KEY` | Required in production, or the backend refuses to start. |
| `DATABASE_URL` | Your PostgreSQL database, with strong credentials. |
| `DEBUG` | `false` |

In the frontend, set `VITE_API_BASE_URL=/api`.

**Usually also set:**

| Setting | Why |
|---|---|
| `PUBLIC_API_BASE_URL`, `PUBLIC_APP_BASE_URL` | Your `https://` addresses. Needed for email links, Google sign-in and AI assistants. |
| `BACKUP_ENCRYPTION_KEY`, and a volume at `BACKUP_DIR` | Keep the key safe, and let backups survive restarts. |
| `MCP_WRITE_ENABLED=true` | Only if assistants should be able to change data. |
| `PLATFORM_SMTP_*` | Turns on **Forgot password?** emails. |
| `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_GOOGLE_CLIENT_SECRET` | Turns on Google sign-in. |

[ENV.md](https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software/blob/main/ENV.md) documents every setting.

## How a self-hosted copy differs

By default a copy runs as one organisation (`DEPLOYMENT_MODE=single_tenant`):

- There is no public sign-up. Create users through the [API](../getting-started/team#add-team-members).
- Every user reaches every company with one role.
- You can have one company until `global_settings.max_companies` is raised in the database.
- Sending email needs an [SMTP configuration](../settings/email#on-a-self-hosted-copy).
- [Backups](../settings/backups) are yours to run and keep.

Running a public multi-user site needs `DEPLOYMENT_MODE=shared_hosting` and more setup. See ENV.md first.

## Get involved

Bug reports and pull requests are welcome on [GitHub](https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software). See [CONTRIBUTING.md](https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software/blob/main/CONTRIBUTING.md).
