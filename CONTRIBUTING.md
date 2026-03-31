# Contributing to Respawn Invoicing

Thank you for your interest in contributing to Respawn Invoicing.

We welcome all kinds of contributions:
- Bug reports
- Feature requests
- Documentation improvements
- Code contributions (backend, frontend, tests, dev tooling)

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Branch Naming](#branch-naming)
- [Commit Messages](#commit-messages)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Good First Issues](#good-first-issues)

## Code of Conduct

By participating in this project, you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

1. Fork the repository.
2. Clone your fork:
   ```bash
   git clone https://github.com/<your-username>/simple_invoicing.git
   cd simple_invoicing
   ```
3. Add upstream remote:
   ```bash
   git remote add upstream https://github.com/nikhilb2/simple_invoicing.git
   ```
4. Create a feature branch.

## Development Setup

### Option A: Docker (recommended)

```bash
cp .env.example .env
cp backend/.env.example backend/.env.development
cp frontend/.env.example frontend/.env.development

make dev
make seed
```

### Option B: Manual setup

Backend:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.development
uvicorn app_main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
cp .env.example .env.development
npm run dev
```

## Branch Naming

Use descriptive branch names:
- `feat/<short-description>`
- `fix/<short-description>`
- `docs/<short-description>`
- `test/<short-description>`
- `chore/<short-description>`

Examples:
- `feat/add-recurring-invoice-endpoint`
- `fix/ledger-statement-date-filter`
- `docs/update-docker-setup`

## Commit Messages

We follow Conventional Commits:

- `feat: add invoice email sending`
- `fix: prevent negative stock on sales voucher`
- `docs: improve setup instructions`
- `test: add e2e for payment flow`
- `chore: bump fastapi to 0.115.x`

## Testing

Run tests before opening a PR.

### Frontend E2E
```bash
cd frontend
npm run test:e2e
```

### Backend tests
If backend tests are available in your branch:
```bash
cd backend
pytest
```

### Lint/type checks
```bash
cd frontend && npm run build
cd backend && python -m compileall .
```

## Pull Request Process

1. Ensure your branch is up to date with `main`:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```
2. Keep PRs focused and small when possible.
3. Fill out the PR template completely.
4. Include screenshots/videos for UI changes.
5. Add or update tests for behavior changes.
6. Update documentation when needed.
7. Wait for CI to pass.

## Good First Issues

Look for issues labeled:
- `good first issue`
- `help wanted`
- `documentation`

If you want to contribute but are unsure where to start, open a discussion or comment on an issue and ask for guidance.

## Questions

If you need help, please:
- Open a GitHub Discussion (recommended)
- Or open an issue with the `question` label

Thanks again for contributing.
