import api, { getBlobErrorMessage } from './client';

/**
 * The PDF of a quotation or proforma. A failure arrives as a Blob (the request is
 * `responseType: 'blob'`), so it is decoded here and thrown as an Error carrying the
 * server's own message instead of "Request failed with status code 404".
 */
export async function fetchQuotationPdf(quotationId: number, fallback: string): Promise<Blob> {
  try {
    const response = await api.get(`/quotations/${quotationId}/pdf`, { responseType: 'blob' });
    return response.data as Blob;
  } catch (err) {
    throw new Error(await getBlobErrorMessage(err, fallback));
  }
}
