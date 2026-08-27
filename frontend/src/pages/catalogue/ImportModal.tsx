/**
 * Bulk CSV import for the catalogue.
 *
 * Import is an upsert keyed on Item Code, so a careless file silently rewrites
 * prices and stock across the whole catalogue. That is why picking a file only
 * arms the import here — nothing is uploaded until the user confirms.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { CircleCheck, FileDown, FileSpreadsheet, TriangleAlert, Upload } from 'lucide-react';
import api, { getApiErrorMessage } from '../../api/client';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { track } from '../../lib/analytics';
import { exportCatalogueCsv } from './exports';

type ImportError = {
  row: number;
  message: string;
};

/** The shape POST /products/import-csv answers with. */
type ImportResult = {
  created: number;
  updated: number;
  errors: ImportError[];
};

type ImportModalProps = {
  onClose: () => void;
  /** Called after an import that changed anything, so the list can refetch. */
  onImported: () => void;
};

/**
 * The headers the backend actually reads, in export order.
 *
 * It lower-cases each header and turns spaces into underscores before matching,
 * so casing and spacing are forgiving but the words are not. `alt` is the other
 * spelling the same field answers to.
 */
const ACCEPTED_HEADERS: Array<{ label: string; alt?: string; required?: boolean }> = [
  { label: 'Item Name', alt: 'Name', required: true },
  { label: 'Item Code', alt: 'SKU', required: true },
  { label: 'Purchase Price' },
  { label: 'Selling Price' },
  { label: 'Current Stock', alt: 'Stock' },
  { label: 'Reorder Level' },
  { label: 'Description' },
  { label: 'HSN Code' },
  { label: 'Unit' },
  { label: 'Tax', alt: 'GST' },
];

const TITLE_ID = 'catalogue-import-title';

export default function ImportModal({ onClose, onImported }: ImportModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState('');
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  // Closing mid-upload would leave the user with no idea whether the catalogue
  // was rewritten, so the request has to finish first.
  const requestClose = useCallback(() => {
    if (importing) return;
    onClose();
  }, [importing, onClose]);

  useEscapeClose(requestClose);

  useEffect(() => {
    fileInputRef.current?.focus();
  }, []);

  useEffect(() => {
    // The controls the user was on are replaced by the summary; without this
    // the focus ring lands back on <body> and keyboard users lose their place.
    if (result) resultRef.current?.focus();
  }, [result]);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0] ?? null;
    setFile(picked);
    setError('');
    setResult(null);
    // Clearing the value is what lets the SAME file be picked again — otherwise
    // re-selecting it fires no change event and a corrected retry does nothing.
    event.target.value = '';
  }

  async function handleDownloadTemplate() {
    try {
      setDownloadingTemplate(true);
      setError('');
      // The export is the template: same headers, same order, real rows to edit.
      await exportCatalogueCsv({
        search: '',
        status: '',
        lowStock: false,
        serials: '',
        sortBy: 'name',
        sortOrder: 'asc',
      });
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to download the template.'));
    } finally {
      setDownloadingTemplate(false);
    }
  }

  async function handleImport() {
    if (!file) return;
    try {
      setImporting(true);
      setError('');

      const formData = new FormData();
      formData.append('file', file);
      const res = await api.post<ImportResult>('/products/import-csv', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setResult(res.data);
      setFile(null);
      track('products_csv_imported', {
        created_count: res.data.created,
        updated_count: res.data.updated,
        error_count: res.data.errors.length,
      });

      // Only tell the list to refetch when something actually moved.
      if (res.data.created > 0 || res.data.updated > 0) {
        onImported();
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to import the CSV.'));
    } finally {
      setImporting(false);
    }
  }

  /** Back to the picker, so a corrected file can go up without reopening. */
  function handleImportAnother() {
    setResult(null);
    setFile(null);
    setError('');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
      fileInputRef.current.focus();
    }
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby={TITLE_ID}
      onClick={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <h2 id={TITLE_ID} className="nav-panel__title">Import catalogue from CSV</h2>
        </div>

        <div className="catalogue-import__body">
          {result ? (
            <ImportSummary result={result} resultRef={resultRef} />
          ) : (
            <>
              <p className="field-hint">
                Rows are matched on <strong>Item Code</strong>. A matching item is overwritten with the
                values in the file; anything else is created. Serial-tracked items keep their stock —
                a CSV cannot carry the serial numbers that stock has to be backed by.
              </p>

              <div className="field">
                <span className="catalogue-import__label">Accepted column headers</span>
                <ul className="catalogue-import__headers">
                  {ACCEPTED_HEADERS.map((header) => (
                    <li
                      key={header.label}
                      className={`catalogue-import__header-chip${header.required ? ' catalogue-import__header-chip--required' : ''}`}
                    >
                      <code>{header.label}</code>
                      {header.alt ? <span className="catalogue-import__header-alt"> or <code>{header.alt}</code></span> : null}
                    </li>
                  ))}
                </ul>
                <p className="field-hint">
                  Item Name and Item Code are required on every row. Headers are matched without regard
                  to case or spacing, extra columns (including <code>Category</code>) are ignored, and
                  any missing column falls back to its default.
                </p>
              </div>

              <div className="field">
                <label htmlFor="catalogue-import-file">CSV file</label>
                <input
                  id="catalogue-import-file"
                  ref={fileInputRef}
                  className="input"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileChange}
                  disabled={importing}
                />
                {file ? (
                  <p className="field-hint">
                    Ready to import <strong>{file.name}</strong>. Nothing is uploaded until you confirm.
                  </p>
                ) : (
                  <p className="field-hint">Start from an export of your current catalogue if you need the exact layout.</p>
                )}
              </div>
            </>
          )}

          {error ? (
            <p className="catalogue-import__alert" role="alert">
              <TriangleAlert size={16} aria-hidden="true" />
              <span>{error}</span>
            </p>
          ) : null}
        </div>

        <div className="form-action-bar">
          {result ? (
            <>
              <button
                type="button"
                className="button button--secondary"
                onClick={handleImportAnother}
                title="Import another CSV file"
                aria-label="Import another CSV file"
              >
                <Upload size={16} aria-hidden="true" />
                Import another file
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={onClose}
                title="Close"
                aria-label="Close"
              >
                Done
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => void handleDownloadTemplate()}
                disabled={downloadingTemplate || importing}
                title="Download the current catalogue as a CSV template"
                aria-label="Download the current catalogue as a CSV template"
              >
                <FileDown size={16} aria-hidden="true" />
                {downloadingTemplate ? 'Preparing…' : 'Download template'}
              </button>
              <button
                type="button"
                className="button button--secondary"
                onClick={requestClose}
                disabled={importing}
                title="Cancel"
                aria-label="Cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void handleImport()}
                disabled={!file || importing}
                title="Import the selected file"
                aria-label="Import the selected file"
              >
                <FileSpreadsheet size={16} aria-hidden="true" />
                {importing ? 'Importing…' : 'Import and update items'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ImportSummary({ result, resultRef }: { result: ImportResult; resultRef: React.RefObject<HTMLDivElement> }) {
  const changed = result.created + result.updated;
  const hasErrors = result.errors.length > 0;

  return (
    <div className="catalogue-import__result" ref={resultRef} tabIndex={-1}>
      <div className="catalogue-import__summary">
        <span className="status-chip status-chip--success">
          <CircleCheck size={14} aria-hidden="true" />
          {result.created} created
        </span>
        <span className="status-chip status-chip--success">
          <CircleCheck size={14} aria-hidden="true" />
          {result.updated} updated
        </span>
        <span className={`status-chip${hasErrors ? ' status-chip--error' : ''}`}>
          {hasErrors ? <TriangleAlert size={14} aria-hidden="true" /> : null}
          {result.errors.length} skipped
        </span>
      </div>

      {hasErrors ? (
        <>
          <p className="field-hint">
            {changed > 0
              ? `The ${changed} valid row${changed === 1 ? '' : 's'} were imported — only the rows below were skipped. Fix them and import the file again; re-importing rows that already went through simply updates them to the same values.`
              : 'No rows were imported. Fix the rows below and import the file again.'}
          </p>
          <ul className="catalogue-import__errors">
            {result.errors.map((err) => (
              <li className="catalogue-import__error" key={`${err.row}-${err.message}`}>
                <span className="catalogue-import__error-row">Row {err.row}</span>
                <span>{err.message}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="field-hint">
          {changed > 0
            ? 'Every row in the file was imported.'
            : 'The file held no rows, so nothing changed.'}
        </p>
      )}
    </div>
  );
}
