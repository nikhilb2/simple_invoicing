import axios from 'axios';
import api from '../../api/client';
import type {
  OAuthAuthorizationRequest,
  OAuthDecisionResponse,
  OAuthGrant,
} from './types';

/**
 * Everything goes through api/client so the JWT interceptor and the
 * X-Company-Id header apply — these are app-authed endpoints, not part of the
 * OAuth machinery a connector talks to.
 */

/**
 * A parked /authorize request has already expired, or never existed.
 *
 * The backend answers 410 for the first and 404 for the second, and the
 * consent screen shows the same "start again from your app" state for both:
 * the user cannot act on the distinction, and either way the request_id in
 * their URL is spent. Distinguished from a network failure, which is worth
 * a retry button.
 */
export function isExpiredAuthorizationRequest(error: unknown): boolean {
  return axios.isAxiosError(error) && (error.response?.status === 404 || error.response?.status === 410);
}

export async function fetchAuthorizationRequest(requestId: string): Promise<OAuthAuthorizationRequest> {
  const res = await api.get<OAuthAuthorizationRequest>(
    `/oauth/authorize/request/${encodeURIComponent(requestId)}`,
  );
  return normalizeAuthorizationRequest(res.data);
}

export async function submitAuthorizationDecision(input: {
  requestId: string;
  approve: boolean;
  companyId: number;
}): Promise<OAuthDecisionResponse> {
  const res = await api.post<OAuthDecisionResponse>('/oauth/authorize/decision', {
    request_id: input.requestId,
    approve: input.approve,
    company_id: input.companyId,
  });
  return res.data;
}

export async function fetchGrants(): Promise<OAuthGrant[]> {
  const res = await api.get<OAuthGrant[]>('/oauth/grants');
  return (res.data ?? []).map(normalizeGrant);
}

export async function revokeGrant(clientId: string): Promise<void> {
  await api.delete(`/oauth/grants/${encodeURIComponent(clientId)}`);
}

/**
 * OAuth carries scopes on the wire as one space-delimited string, and both of
 * these endpoints hand back a list instead. Accepting either costs two lines
 * and keeps a plausible backend change from rendering "i n v o i c i n g" —
 * a string would otherwise map() one character at a time.
 */
function toScopeList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value === 'string') return value.split(/\s+/).filter(Boolean);
  return [];
}

function normalizeGrant(grant: OAuthGrant): OAuthGrant {
  return { ...grant, scopes: toScopeList(grant.scopes) };
}

function normalizeAuthorizationRequest(request: OAuthAuthorizationRequest): OAuthAuthorizationRequest {
  return {
    ...request,
    scopes: Array.isArray(request.scopes) ? request.scopes : [],
    companies: Array.isArray(request.companies) ? request.companies : [],
  };
}
