import { afterEach, describe, expect, test, vi } from 'vitest';
import { copyTextToClipboard } from './clipboard';

afterEach(() => vi.unstubAllGlobals());

function stubSelectionCopy(result: boolean = true) {
  const removeChild = vi.fn();
  const field = {
    value: '',
    style: { position: '', opacity: '' },
    setAttribute: vi.fn(),
    select: vi.fn(),
    parentNode: { removeChild },
  };
  const createElement = vi.fn(() => field);
  const appendChild = vi.fn();
  const execCommand = vi.fn(() => result);
  vi.stubGlobal('document', {
    body: { appendChild },
    createElement,
    execCommand,
  });
  return { field, createElement, appendChild, execCommand, removeChild };
}

describe('copyTextToClipboard', () => {
  test('copies the supplied invoice number exactly', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const fallback = stubSelectionCopy();

    expect(await copyTextToClipboard('INV-0007/26')).toBe(true);
    expect(writeText).toHaveBeenCalledExactlyOnceWith('INV-0007/26');
    expect(fallback.createElement).not.toHaveBeenCalled();
  });

  test('falls back when the async clipboard API rejects', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) } });
    const fallback = stubSelectionCopy();

    await expect(copyTextToClipboard('INV-7')).resolves.toBe(true);
    expect(fallback.field.value).toBe('INV-7');
    expect(fallback.execCommand).toHaveBeenCalledExactlyOnceWith('copy');
    expect(fallback.removeChild).toHaveBeenCalledExactlyOnceWith(fallback.field);
  });

  test('copies via a hidden textarea on plain-http origins', async () => {
    vi.stubGlobal('navigator', {});
    const fallback = stubSelectionCopy();

    await expect(copyTextToClipboard('INV-0007/26')).resolves.toBe(true);
    expect(fallback.createElement).toHaveBeenCalledExactlyOnceWith('textarea');
    expect(fallback.field.value).toBe('INV-0007/26');
    expect(fallback.field.setAttribute).toHaveBeenCalledWith('readonly', '');
    expect(fallback.appendChild).toHaveBeenCalledExactlyOnceWith(fallback.field);
    expect(fallback.field.select).toHaveBeenCalledOnce();
    expect(fallback.execCommand).toHaveBeenCalledExactlyOnceWith('copy');
    expect(fallback.removeChild).toHaveBeenCalledExactlyOnceWith(fallback.field);
  });

  test('returns false and cleans up when selection copying fails', async () => {
    vi.stubGlobal('navigator', {});
    const fallback = stubSelectionCopy(false);

    await expect(copyTextToClipboard('INV-7')).resolves.toBe(false);
    expect(fallback.removeChild).toHaveBeenCalledExactlyOnceWith(fallback.field);
  });

  test('returns false and cleans up when selection copying throws', async () => {
    vi.stubGlobal('navigator', {});
    const fallback = stubSelectionCopy();
    fallback.execCommand.mockImplementation(() => { throw new Error('Unsupported'); });

    await expect(copyTextToClipboard('INV-7')).resolves.toBe(false);
    expect(fallback.removeChild).toHaveBeenCalledExactlyOnceWith(fallback.field);
  });

  test('returns false without clipboard APIs or a document', async () => {
    vi.stubGlobal('navigator', {});
    vi.stubGlobal('document', undefined);

    await expect(copyTextToClipboard('INV-7')).resolves.toBe(false);
  });

  test('uses selection copy when navigator is unavailable', async () => {
    vi.stubGlobal('navigator', undefined);
    const fallback = stubSelectionCopy();

    await expect(copyTextToClipboard('INV-7')).resolves.toBe(true);
    expect(fallback.execCommand).toHaveBeenCalledExactlyOnceWith('copy');
  });

  test('handles environments with no navigator or document', async () => {
    vi.stubGlobal('navigator', undefined);
    vi.stubGlobal('document', undefined);

    await expect(copyTextToClipboard('INV-7')).resolves.toBe(false);
  });
});
