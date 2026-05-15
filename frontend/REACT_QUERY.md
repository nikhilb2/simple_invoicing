# React Query conventions

All network requests in this frontend must go through **TanStack React Query** (`@tanstack/react-query`). Do not use bare `useEffect` + `useState` to fetch data.

---

## Why

- Automatic caching, deduplication, and background refetch
- `keepPreviousData` / `placeholderData` prevents pagination flicker
- `invalidateQueries` is the single, consistent way to refresh stale data after a mutation
- No more boilerplate `loading`, `error`, and `data` state variables per page

---

## The query client

Configured in [`src/lib/queryClient.ts`](src/lib/queryClient.ts):

```ts
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,         // data is fresh for 30 s; no refetch during this window
      gcTime: 5 * 60_000,        // keep unused cache for 5 min
      refetchOnWindowFocus: false,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
});
```

Mounted once at the root in [`src/main.tsx`](src/main.tsx) via `<QueryClientProvider client={queryClient}>`.

---

## Reading data — `useQuery`

```tsx
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { listEmailLogs } from '../api/emailLogs';

const { data, isLoading, error } = useQuery({
  queryKey: ['email-logs', page, fromDate, emailType],
  queryFn: () => listEmailLogs({ page, from_date: fromDate, email_type: emailType }),
  placeholderData: keepPreviousData,   // keep previous page visible during page change
});
```

**Rules:**

1. The `queryFn` must call a typed function from `src/api/`. Never call `api.get(...)` directly inside `queryFn`.
2. Always pass `placeholderData: keepPreviousData` on paginated queries to prevent the flash of empty state on page change.
3. Consume `isLoading`, `error`, and `data` from the hook — never add separate `useState` for these.
4. Display errors via `<StatusToasts error={error ? getApiErrorMessage(error) : ''} ... />`.

---

## Mutating data — `useMutation`

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query';
import api, { getApiErrorMessage } from '../api/client';

const queryClient = useQueryClient();

const restoreMutation = useMutation({
  mutationFn: (invoiceId: number) => api.post(`/invoices/${invoiceId}/restore`),
  onSuccess: () => {
    setSuccess('Invoice restored.');
    void queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.all });
  },
  onError: (err) => setError(getApiErrorMessage(err)),
});

// Trigger with:
restoreMutation.mutate(invoiceId);
```

**Rules:**

1. Always `invalidateQueries` (or `refetchQueries`) in `onSuccess` for every resource the mutation touches.
2. One-off actions that don't need caching (e.g. send email, download PDF) are fine as plain `async` functions — they don't need `useMutation` unless you want `isPending` state.
3. Never manually splice/push into cached arrays. Invalidate and let React Query refetch.

---

## Query keys

Every distinct resource needs a stable, serialisable query key. Follow the factory pattern used in [`src/features/invoices/queryKeys.ts`](src/features/invoices/queryKeys.ts):

```ts
// src/api/emailLogs.ts  (or a dedicated queryKeys file)
export const emailLogQueryKeys = {
  all: ['email-logs'] as const,
  list: (page: number, pageSize: number, filters: object) =>
    ['email-logs', 'list', page, pageSize, filters] as const,
};
```

**Rules:**

1. Start the key with the resource noun: `['email-logs', ...]`, `['invoices', ...]`, `['ledgers', ...]`.
2. Include every variable that changes the response (page, search, filters, FY id) in the key.
3. Use `queryKeys.all` (top-level array) as the target for `invalidateQueries` after mutations — this invalidates all variants for that resource.

---

## API wrapper files

Every endpoint gets a typed wrapper in `src/api/`. The `queryFn` calls the wrapper, not raw `api.get`.

```ts
// src/api/emailLogs.ts
export async function listEmailLogs(filters: EmailLogFilters): Promise<PaginatedEmailLogs> {
  const res = await api.get<PaginatedEmailLogs>('/email-logs/', { params: filters });
  return res.data;
}
```

This keeps `queryFn` one-liners and makes the API surface easy to find and test.

---

## Pages that still use `useEffect` (legacy)

The following pages pre-date this convention and still use manual `useEffect` fetching:

- `DayBookPage.tsx`
- `LedgersPage.tsx`
- `ProductsPage.tsx`
- `CreditNotesPage.tsx`
- `CompanyPage.tsx`
- `ProduceItemsPage.tsx`

When making significant changes to any of these, migrate them to React Query as part of the work. Don't add new `useEffect` fetch patterns to them.

---

## Quick checklist for new pages

- [ ] `queryFn` calls a typed function from `src/api/`
- [ ] Query key includes all filter/pagination parameters
- [ ] Uses `keepPreviousData` for paginated lists
- [ ] Errors displayed via `<StatusToasts>`
- [ ] Mutations call `queryClient.invalidateQueries` on success
- [ ] No new `const [loading, setLoading] = useState(true)` for fetch state
