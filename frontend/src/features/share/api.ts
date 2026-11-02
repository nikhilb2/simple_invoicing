import api from '../../api/client';
import type { ShareLink, ShareResourceType } from '../../types/api';

export type ShareLinkInput = {
  resourceType: ShareResourceType;
  resourceId: number;
  /** `YYYY-MM-DD`. Statements only — the backend ignores them elsewhere. */
  fromDate?: string;
  toDate?: string;
};

type ShareLinkPayload = {
  resource_type: ShareResourceType;
  resource_id: number;
  from_date?: string;
  to_date?: string;
};

function buildPayload(input: ShareLinkInput): ShareLinkPayload {
  const payload: ShareLinkPayload = {
    resource_type: input.resourceType,
    resource_id: input.resourceId,
  };

  // Only a statement carries a period. Sending `from_date` for an invoice would
  // be noise the backend has to decide what to do with.
  if (input.resourceType === 'ledger_statement') {
    if (input.fromDate) payload.from_date = input.fromDate;
    if (input.toDate) payload.to_date = input.toDate;
  }

  return payload;
}

/**
 * Creates the public link, or returns the one already live for this document.
 *
 * The endpoint is idempotent, which is what lets the share dialog call it on
 * open with no "do you already have one?" round-trip first — and why it is read
 * through `useQuery` despite being a POST.
 */
export async function ensureShareLink(input: ShareLinkInput): Promise<ShareLink> {
  const res = await api.post<ShareLink>('/share/', buildPayload(input));
  return res.data;
}

/** Every live link for one document. */
export async function listShareLinks(
  resourceType: ShareResourceType,
  resourceId: number,
): Promise<ShareLink[]> {
  const res = await api.get<ShareLink[]>('/share/', {
    params: { resource_type: resourceType, resource_id: resourceId },
  });
  return res.data;
}

/** Kills the link. The URL 404s from here on; a new share creates a new token. */
export async function revokeShareLink(id: number): Promise<void> {
  await api.delete(`/share/${id}`);
}
