import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClipboardList, LoaderCircle, ScanLine, Volume2, VolumeX } from 'lucide-react';
import { getApiErrorMessage } from '../api/client';
import { scanCode } from '../features/serials/api';
import type { Serial } from '../features/serials/types';
import type { Product } from '../types/api';
import { readInvoiceComposerPrefs, updateInvoiceComposerPrefs } from '../utils/invoiceComposerPrefs.ts';

/**
 * What the backend made of a scanned code. `unknown` is a resolution, not a
 * failure: on a purchase it is the good case — a serial nobody has registered
 * yet — so the caller decides what each of the three means.
 */
export type ScanResolution =
  | { kind: 'serial'; code: string; serial: Serial }
  | { kind: 'product'; code: string; product: Product }
  | { kind: 'unknown'; code: string; detail: string };

/**
 * What the caller did with it, in the operator's words. `info` is for a scan
 * that changed nothing but is not a mistake — the same handset scanned twice.
 */
export type ScanOutcome = {
  status: 'ok' | 'info' | 'error';
  message: string;
  /** A sold serial names the invoice it went out on, and links to it. */
  link?: { to: string; label: string };
};

export type ScanTarget = {
  lineNumber: number;
  productName: string;
};

type ScanBarProps = {
  mode: 'sales' | 'purchase';
  /** Resolves one code into a line change; returns what the strip should say. */
  onResolve: (resolution: ScanResolution) => ScanOutcome;
  /** Purchase mode: the line serials register into. */
  target?: ScanTarget | null;
  /** Handed up so a keyboard shortcut elsewhere can put the cursor back here. */
  inputRef?: React.RefObject<HTMLInputElement>;
  disabled?: boolean;
};

type FeedbackEntry = ScanOutcome & { id: number };

type BulkResult = {
  code: string;
  ok: boolean;
  message: string;
};

/** A scanner types a whole code in a few milliseconds; a pause this long ends it. */
const SILENCE_MS = 120;
/** Below this a "quiet" burst is far more likely a human mid-word than a code. */
const MIN_AUTO_SUBMIT_LENGTH = 6;
const MAX_FEEDBACK_ENTRIES = 5;

function splitPastedCodes(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function ScanBar({ mode, onResolve, target = null, inputRef, disabled = false }: ScanBarProps) {
  const ownInputRef = useRef<HTMLInputElement>(null);
  const boxRef = inputRef ?? ownInputRef;

  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [queuedCount, setQueuedCount] = useState(0);
  const [focused, setFocused] = useState(false);
  const [shake, setShake] = useState(false);
  const [entries, setEntries] = useState<FeedbackEntry[]>([]);
  const [beep, setBeep] = useState(() => readInvoiceComposerPrefs().scanBeep);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const [pasteResults, setPasteResults] = useState<BulkResult[]>([]);
  const [pasteRunning, setPasteRunning] = useState(false);

  /* The scan loop reads these from refs rather than from state: a scanner can
     fire two codes inside one React render, and a stale closure would drop the
     second one. */
  const busyRef = useRef(false);
  const queueRef = useRef<string[]>([]);
  const captureRef = useRef('');
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const entryIdRef = useRef(0);
  const audioRef = useRef<AudioContext | null>(null);
  const onResolveRef = useRef(onResolve);
  const beepRef = useRef(beep);
  const selectAfterRenderRef = useRef(false);

  /* Re-pointed after every render rather than during it: the scan loop runs in
     promise callbacks, which is long after the effect has landed. */
  useEffect(() => {
    onResolveRef.current = onResolve;
    beepRef.current = beep;
  });

  /* Scan-first means the caret starts here: the shopkeeper's first action is a
     trigger pull, not a click. Only when nothing else is focused, and without
     scrolling the page to reach it. */
  useEffect(() => {
    if (disabled) return;
    if (document.activeElement && document.activeElement !== document.body) return;
    boxRef.current?.focus({ preventScroll: true });
  }, [boxRef, disabled]);

  /* Selecting has to wait for the render that puts the failed code back in the
     box — selecting the empty value it still holds would do nothing. */
  useEffect(() => {
    if (!selectAfterRenderRef.current) return;
    selectAfterRenderRef.current = false;
    if (document.activeElement === boxRef.current) {
      boxRef.current?.select();
    }
  });

  useEffect(() => () => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    if (shakeTimerRef.current) clearTimeout(shakeTimerRef.current);
    void audioRef.current?.close();
  }, []);

  /* Two tones, far enough apart to tell without looking: a short high blip for
     a scan that landed, a longer low one for a scan that did not. Every step is
     guarded — a browser with autoplay locked down must not break scanning. */
  const playTone = useCallback((ok: boolean) => {
    if (!beepRef.current) return;
    try {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return;
      const ctx = audioRef.current ?? new Ctor();
      audioRef.current = ctx;
      if (ctx.state === 'suspended') void ctx.resume();

      const now = ctx.currentTime;
      const duration = ok ? 0.09 : 0.22;
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(ok ? 1180 : 300, now);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.12, now + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start(now);
      oscillator.stop(now + duration + 0.02);
    } catch {
      // No audio in this browser or profile — the strip is the real feedback.
    }
  }, []);

  const pushEntry = useCallback((outcome: ScanOutcome) => {
    entryIdRef.current += 1;
    const entry: FeedbackEntry = { ...outcome, id: entryIdRef.current };
    setEntries((current) => [entry, ...current].slice(0, MAX_FEEDBACK_ENTRIES));
  }, []);

  const resolveOne = useCallback(async (raw: string): Promise<ScanOutcome> => {
    try {
      const lookup = await scanCode(raw);
      const resolution: ScanResolution = lookup.found
        ? lookup.result.kind === 'serial'
          ? { kind: 'serial', code: raw, serial: lookup.result.serial }
          : { kind: 'product', code: raw, product: lookup.result.product }
        : { kind: 'unknown', code: raw, detail: lookup.detail };
      return onResolveRef.current(resolution);
    } catch (err) {
      return { status: 'error', message: getApiErrorMessage(err, 'Scan failed — check the connection and scan again.') };
    }
  }, []);

  /* Only ever takes focus back when nothing else holds it. The operator may be
     typing a price two fields down while a lookup finishes, and a scan bar that
     grabs the caret mid-number is worse than one that misses a scan. */
  const keepFocus = useCallback(() => {
    const active = document.activeElement;
    if (active === boxRef.current) return;
    if (active && active !== document.body) return;
    boxRef.current?.focus();
  }, [boxRef]);

  const runScan = useCallback(
    async (raw: string) => {
      busyRef.current = true;
      setBusy(true);
      const outcome = await resolveOne(raw);
      pushEntry(outcome);
      playTone(outcome.status !== 'error');

      if (outcome.status === 'error') {
        /* Keep the code and select it, so the retype after a misread replaces
           it instead of appending to it. */
        setCode(raw);
        selectAfterRenderRef.current = true;
        setShake(true);
        if (shakeTimerRef.current) clearTimeout(shakeTimerRef.current);
        shakeTimerRef.current = setTimeout(() => setShake(false), 420);
      } else {
        // Also clears a code left in the box by an earlier failure, so the
        // next scan starts from an empty field however the last one ended.
        setCode('');
      }

      busyRef.current = false;
      setBusy(false);

      const next = queueRef.current.shift();
      setQueuedCount(queueRef.current.length);
      if (next) {
        void runScan(next);
        return;
      }

      keepFocus();
    },
    [keepFocus, playTone, pushEntry, resolveOne],
  );

  const submit = useCallback(
    (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed || disabled) return;
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

      if (busyRef.current) {
        /* A fast operator scans the next handset before the first answer lands.
           Dropping that code would cost a whole unit off the invoice, so it
           waits its turn instead. */
        queueRef.current.push(trimmed);
        setQueuedCount(queueRef.current.length);
        return;
      }

      setCode('');
      void runScan(trimmed);
    },
    [disabled, runScan],
  );

  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const value = event.target.value;
    setCode(value);
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    if (value.trim().length < MIN_AUTO_SUBMIT_LENGTH) return;
    // Fallback for scanners configured with no Enter suffix.
    silenceTimerRef.current = setTimeout(() => submit(value), SILENCE_MS);
  }

  function flushCapture() {
    const captured = captureRef.current.trim();
    captureRef.current = '';
    if (captured) submit(captured);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      captureRef.current = '';
      boxRef.current?.blur();
      return;
    }

    /* The box is readOnly while a lookup is in flight, so the browser will not
       put these characters anywhere — this handler is where a code scanned
       mid-request is caught. Without it the second handset of a burst would
       vanish silently. */
    if (busyRef.current) {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        flushCapture();
        return;
      }
      if (event.key === 'Backspace') {
        event.preventDefault();
        captureRef.current = captureRef.current.slice(0, -1);
        return;
      }
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        captureRef.current += event.key;
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        if (captureRef.current.trim().length >= MIN_AUTO_SUBMIT_LENGTH) {
          silenceTimerRef.current = setTimeout(flushCapture, SILENCE_MS);
        }
      }
      return;
    }

    if (event.key === 'Enter') {
      // The composer form must not submit an invoice because a scanner said Enter.
      event.preventDefault();
      submit(code);
    }
  }

  async function handlePasteSubmit() {
    const codes = splitPastedCodes(pasteText);
    if (codes.length === 0 || pasteRunning) return;

    setPasteRunning(true);
    setPasteResults([]);
    for (const entry of codes) {
      const outcome = await resolveOne(entry);
      setPasteResults((current) => [...current, { code: entry, ok: outcome.status === 'ok', message: outcome.message }]);
    }
    setPasteRunning(false);
    playTone(true);
  }

  const isPurchase = mode === 'purchase';
  const hintId = 'scan-bar-hint';

  return (
    <div className={`scan-bar${shake ? ' scan-bar--shake' : ''}`}>
      <div className="scan-bar__row">
        <div className="scan-bar__field">
          <label className="scan-bar__label" htmlFor="scan-bar-input">
            <ScanLine size={15} aria-hidden="true" />
            {isPurchase ? 'Scan to register serial / IMEI' : 'Scan serial / IMEI or product code'}
          </label>
          <div className="scan-bar__input-wrap">
            <input
              id="scan-bar-input"
              ref={boxRef}
              className="input scan-bar__input"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={code}
              readOnly={busy}
              disabled={disabled}
              aria-describedby={hintId}
              aria-busy={busy}
              placeholder={isPurchase ? 'Scan each handset…' : 'Scan or type a code, then Enter'}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
            />
            {busy ? (
              <span className="scan-bar__spinner" aria-hidden="true">
                <LoaderCircle size={16} />
              </span>
            ) : null}
          </div>
        </div>

        <div className="scan-bar__actions">
          {focused ? <span className="scan-bar__pill">Scan mode</span> : null}
          {queuedCount > 0 ? (
            <span className="scan-bar__pill scan-bar__pill--queue">{queuedCount} queued</span>
          ) : null}
          <button
            type="button"
            className="scan-bar__toggle"
            aria-pressed={beep}
            title={beep ? 'Beep on scan: on' : 'Beep on scan: off'}
            aria-label={beep ? 'Turn scan beep off' : 'Turn scan beep on'}
            onClick={() => {
              const next = !beep;
              setBeep(next);
              updateInvoiceComposerPrefs({ scanBeep: next });
            }}
          >
            {beep ? <Volume2 size={15} aria-hidden="true" /> : <VolumeX size={15} aria-hidden="true" />}
          </button>
          {isPurchase ? (
            <button
              type="button"
              className="link-button"
              aria-expanded={pasteOpen}
              onClick={() => setPasteOpen((current) => !current)}
            >
              <ClipboardList size={13} aria-hidden="true" />
              Paste list
            </button>
          ) : null}
        </div>
      </div>

      <p className="scan-bar__hint" id={hintId}>
        {isPurchase
          ? target
            ? `Scanning into: Line ${target.lineNumber} · ${target.productName}`
            : 'Add a serial-tracked product line first — or scan its product barcode.'
          : 'Enter submits. Esc leaves the box. Every scan lands on a line without touching the mouse.'}
      </p>

      {pasteOpen && isPurchase ? (
        <div className="scan-bar__paste">
          <label className="scan-bar__label" htmlFor="scan-bar-paste">Paste serials — one per line, or comma separated</label>
          <textarea
            id="scan-bar-paste"
            className="input"
            rows={4}
            value={pasteText}
            onChange={(event) => setPasteText(event.target.value)}
            placeholder={'356938035643809\n356938035643817'}
          />
          <div className="button-row">
            <button
              type="button"
              className="button button--ghost"
              onClick={() => { setPasteText(''); setPasteResults([]); }}
              disabled={pasteRunning}
            >
              Clear
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => { void handlePasteSubmit(); }}
              disabled={pasteRunning || splitPastedCodes(pasteText).length === 0}
            >
              {pasteRunning ? 'Checking…' : `Add ${splitPastedCodes(pasteText).length || ''} serials`.trim()}
            </button>
          </div>
          {pasteResults.length > 0 ? (
            <ul className="scan-bar__paste-results">
              {pasteResults.map((result, index) => (
                <li key={`${result.code}-${index}`} className={result.ok ? 'is-ok' : 'is-bad'}>
                  <span aria-hidden="true">{result.ok ? '✓' : '✗'}</span>
                  <span className="scan-bar__paste-code">{result.code}</span>
                  <span className="scan-bar__paste-reason">{result.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <ul className="scan-feedback" aria-live="polite" aria-label="Recent scans">
        {entries.map((entry) => (
          <li key={entry.id} className={`scan-feedback__item scan-feedback__item--${entry.status}`}>
            <span className="scan-feedback__glyph" aria-hidden="true">
              {entry.status === 'ok' ? '✓' : entry.status === 'info' ? '•' : '✗'}
            </span>
            <span className="scan-feedback__text">{entry.message}</span>
            {entry.link ? (
              <Link className="scan-feedback__link" to={entry.link.to}>{entry.link.label}</Link>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
