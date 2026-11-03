import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, describe, expect, it, vi } from 'vitest';
import api from './client';
import { fetchQuotationPdf } from './quotationPdf';

function failure(status: number, body: unknown) {
  const config = { headers: {} } as InternalAxiosRequestConfig;
  const response = {
    data: new Blob([JSON.stringify(body)], { type: 'application/json' }),
    status,
    statusText: '',
    headers: {},
    config,
  } as AxiosResponse;
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', config, null, response);
}

describe('fetchQuotationPdf', () => {
  afterEach(() => vi.restoreAllMocks());

  it('returns the PDF as a blob and asks for one', async () => {
    const pdf = new Blob(['%PDF'], { type: 'application/pdf' });
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: pdf });

    await expect(fetchQuotationPdf(7, 'Unable to load PDF preview')).resolves.toBe(pdf);
    expect(get).toHaveBeenCalledWith('/quotations/7/pdf', { responseType: 'blob' });
  });

  it("shows the server's reason, not the status code, when the PDF cannot be made", async () => {
    vi.spyOn(api, 'get').mockRejectedValue(failure(404, { detail: 'Quotation 7 not found' }));

    await expect(fetchQuotationPdf(7, 'Unable to load PDF preview')).rejects.toThrow('Quotation 7 not found');
  });

  it('falls back to the given text when the body is not a JSON detail', async () => {
    const config = { headers: {} } as InternalAxiosRequestConfig;
    const noBody = new AxiosError('', 'ERR_BAD_RESPONSE', config, null, {
      data: new Blob(['<html>'], { type: 'text/html' }),
      status: 502,
      statusText: '',
      headers: {},
      config,
    } as AxiosResponse);
    noBody.message = '';
    vi.spyOn(api, 'get').mockRejectedValue(noBody);

    await expect(fetchQuotationPdf(7, 'Unable to download PDF')).rejects.toThrow('Unable to download PDF');
  });
});
