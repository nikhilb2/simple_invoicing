# Simple Invoicing Frontend

React single-page app for the Simple Invoicing accounting system. The frontend provides the browser UI for authentication, products, invoices, ledgers, inventory, payments, and Playwright-tested user workflows.

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- TanStack Query
- Axios
- Zustand
- Framer Motion
- Vitest
- Playwright

## Prerequisites

- Node.js 20 or newer
- npm
- A running Simple Invoicing backend on `http://localhost:8000`

## Local Setup

From the repository root:

```bash
cd frontend
npm install
cp .env.example .env.development
npm run dev
```

The Vite dev server runs at `http://localhost:5173`.

The default `VITE_API_BASE_URL=/api` setting lets Vite proxy API requests to the backend. By default, the proxy target is `http://localhost:8000`.

If your backend runs on a different URL, start the dev server with:

```bash
API_PROXY_TARGET=http://localhost:8001 npm run dev
```

## Environment Variables

Create `frontend/.env.development` from `frontend/.env.example`.

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api` | API base path used by the Axios client. |
| `VITE_APP_NAME` | `Simple Invoicing` | Display name for the app. |
| `VITE_LOG_LEVEL` | `debug` | Client logging level. |
| `API_PROXY_TARGET` | `http://localhost:8000` | Optional dev-server proxy target. Set this when running the backend on a different port. |

## Available Scripts

Run these commands from the `frontend/` directory.

```bash
npm run dev
```

Start the Vite development server.

```bash
npm run build
```

Type-check the project and build the production bundle.

```bash
npm run preview
```

Preview the production build locally.

```bash
npm run lint
```

Lint files under `src/`.

```bash
npm run test
```

Run the Vitest test suite.

```bash
npm run test:e2e
```

Run Playwright end-to-end tests. Playwright starts the Vite dev server automatically unless `CI=true`.

```bash
npm run test:e2e:ui
npm run test:e2e:headed
npm run test:e2e:report
```

Open the Playwright UI, run headed browser tests, or view the HTML report.

## Running Against the Local Backend

1. Start the backend from the repository root or `backend/` directory.
2. Confirm the backend API is available at `http://localhost:8000`.
3. Start the frontend with `npm run dev`.
4. Open `http://localhost:5173` in the browser.

For a full local stack, follow the Docker or manual setup steps in the root `README.md`.

## End-to-End Tests

Playwright tests live in `frontend/e2e/`.

By default, tests use:

- `E2E_BASE_URL=http://localhost:5173`
- `E2E_EXPECT_TIMEOUT_MS=5000`
- `E2E_TEST_TIMEOUT_MS=30000`

Override them when needed:

```bash
E2E_BASE_URL=http://localhost:5173 npm run test:e2e
```
