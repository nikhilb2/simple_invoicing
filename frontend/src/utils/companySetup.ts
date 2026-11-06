import type { CompanyProfile } from '../types/api';

export function isCompanyConfigured(company: CompanyProfile | null | undefined): boolean {
  return Boolean(company?.name?.trim());
}

/**
 * The first-company form, kept for the tab while no company exists. Until one is
 * saved every other page sends you back to setup, so a refresh or a stray link
 * used to bring back an empty form and lose everything typed.
 */
const SETUP_DRAFT_PREFIX = 'company_setup_draft:';

type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function sessionStore(): DraftStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readSetupDraft<T extends object>(owner: string | null, storage: DraftStorage | null = sessionStore()): Partial<T> | null {
  if (!owner || !storage) return null;
  try {
    const raw = storage.getItem(SETUP_DRAFT_PREFIX + owner);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Partial<T>) : null;
  } catch {
    return null;
  }
}

export function writeSetupDraft(owner: string | null, draft: object, storage: DraftStorage | null = sessionStore()): void {
  if (!owner || !storage) return;
  try {
    storage.setItem(SETUP_DRAFT_PREFIX + owner, JSON.stringify(draft));
  } catch {
    /* Storage full or blocked: the form still works, it just isn't kept. */
  }
}

export function clearSetupDraft(owner: string | null, storage: DraftStorage | null = sessionStore()): void {
  if (!owner || !storage) return;
  try {
    storage.removeItem(SETUP_DRAFT_PREFIX + owner);
  } catch {
    /* Nothing to clear. */
  }
}
