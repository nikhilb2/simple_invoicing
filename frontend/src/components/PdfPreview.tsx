import { MutableRefObject, useCallback, useEffect, useRef, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';

export type PdfPreviewParams = Record<string, string | number | boolean | undefined>;

type UsePdfPreviewOptions = {
  /** API path the PDF is fetched from, e.g. `/ledgers/9/statement/pdf`. */
  path: string;
  /**
   * Query string for the request. Also the cache key: change a value and the
   * PDF is re-fetched, which is how the invoice preview reacts to the copies
   * stepper and the statement preview to a new From/To period.
   */
  params?: PdfPreviewParams;
  /** Shown when the request fails without a message of its own. */
  errorMessage?: string;
  /** Surfaces the same failure on the page behind the preview. */
  onError?: (message: string) => void;
};

export type PdfPreviewController = {
  pdfUrl: string | null;
  loading: boolean;
  error: string;
  /** The browser could not render the PDF inline; only the fallback is left. */
  previewFailed: boolean;
  /** False while there is no rendered document to print. */
  canPrint: boolean;
  iframeRef: MutableRefObject<HTMLIFrameElement | null>;
  print: () => void;
  openInNewTab: () => void;
  markPreviewFailed: () => void;
};

/**
 * Fetches a PDF the API only serves to an authenticated request, and hands back
 * everything needed to show and act on it.
 *
 * The blob has to be fetched rather than pointed at, because an <iframe src>
 * carries no Authorization header — so the object URL is ours to clean up, on
 * unmount and before every re-fetch.
 */
export function usePdfPreview({ path, params, errorMessage, onError }: UsePdfPreviewOptions): PdfPreviewController {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // Callers pass an inline arrow, so depending on it directly would re-fetch on
  // every render of the parent.
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  // The request identity. Serialising it is what lets callers pass an object
  // literal without the effect firing on every render; the effect reads the
  // params back out of it, so the two can never drift apart.
  const paramsKey = JSON.stringify(params ?? {});

  useEffect(() => {
    let isMounted = true;
    let objectUrlToRevoke: string | null = null;

    const loadPdf = async () => {
      setLoading(true);
      setError('');
      setPdfUrl(null);
      setPreviewFailed(false);

      try {
        const response = await api.get(path, {
          params: JSON.parse(paramsKey) as PdfPreviewParams,
          responseType: 'blob',
        });
        const nextUrl = window.URL.createObjectURL(response.data as Blob);
        objectUrlToRevoke = nextUrl;

        if (!isMounted) {
          window.URL.revokeObjectURL(nextUrl);
          return;
        }
        setPdfUrl(nextUrl);
      } catch (err) {
        if (!isMounted) return;
        const message = getApiErrorMessage(err, errorMessage ?? 'Unable to load PDF preview');
        setError(message);
        onErrorRef.current?.(message);
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    loadPdf();

    return () => {
      isMounted = false;
      if (objectUrlToRevoke) {
        window.URL.revokeObjectURL(objectUrlToRevoke);
      }
    };
  }, [path, paramsKey, errorMessage]);

  const print = useCallback(() => {
    iframeRef.current?.contentWindow?.focus();
    iframeRef.current?.contentWindow?.print();
  }, []);

  const openInNewTab = useCallback(() => {
    if (!pdfUrl) return;
    window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  }, [pdfUrl]);

  const markPreviewFailed = useCallback(() => {
    setPreviewFailed(true);
    onErrorRef.current?.('PDF preview failed. Open the PDF in a new tab.');
  }, []);

  return {
    pdfUrl,
    loading,
    error,
    previewFailed,
    canPrint: Boolean(pdfUrl) && !loading && !previewFailed,
    iframeRef,
    print,
    openInNewTab,
    markPreviewFailed,
  };
}

type PdfPreviewProps = {
  /** The controller returned by `usePdfPreview`. */
  preview: PdfPreviewController;
  /** Accessible name of the frame, e.g. `Statement for Acme PDF preview`. */
  title: string;
};

/**
 * The body of a document preview: the fetched PDF in a frame, or whichever of
 * loading / failed / unrenderable state it is in.
 *
 * Deliberately presentational — the toolbar above it stays with the caller,
 * because what you can do with an invoice is not what you can do with a
 * statement, and only the caller knows.
 */
export default function PdfPreview({ preview, title }: PdfPreviewProps) {
  const { pdfUrl, loading, error, previewFailed, iframeRef, openInNewTab, markPreviewFailed } = preview;

  return (
    <div className="invoice-pdf-viewer" aria-live="polite">
      {loading ? <p className="muted-text">Loading PDF preview...</p> : null}
      {!loading && error ? <p className="error-text">{error}</p> : null}
      {!loading && previewFailed && pdfUrl ? (
        <div style={{ display: 'grid', gap: '10px', justifyItems: 'center', textAlign: 'center', padding: '16px' }}>
          <p className="muted-text">PDF preview is unavailable in this browser.</p>
          <button
            type="button"
            className="button button--primary"
            onClick={openInNewTab}
            title="Open PDF in a new browser tab"
            aria-label="Open PDF in a new browser tab"
          >
            Open in New Tab
          </button>
        </div>
      ) : null}
      {!loading && pdfUrl && !previewFailed ? (
        <iframe
          ref={iframeRef}
          title={title}
          src={`${pdfUrl}#navpanes=0&toolbar=1&statusbar=0&messages=0`}
          className="invoice-pdf-viewer__frame"
          onError={markPreviewFailed}
        />
      ) : null}
    </div>
  );
}
