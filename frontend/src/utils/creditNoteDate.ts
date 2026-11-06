/**
 * What to remember when the user sets the date on a credit note. Picking today is
 * the same as leaving it alone: it keeps following the clock, and the form sends no
 * date, so a note can still follow a future-dated invoice.
 */
export function creditNoteDateChoice(value: string, today: string): string | null {
  return value === today ? null : value;
}

/** The date the form shows: what the user picked, else today. */
export function shownCreditNoteDate(choice: string | null, today: string): string {
  return choice ?? today;
}

function monthLabel(isoDate: string): string {
  const [year, month] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, 1).toLocaleString('en-IN', { month: 'long', year: 'numeric' });
}

/** A warning for a note dated in a month before the current one, or null. */
export function backdatedNoteWarning(noteDate: string, today: string): string | null {
  if (!noteDate || noteDate.slice(0, 7) >= today.slice(0, 7)) return null;
  const month = monthLabel(noteDate);
  return (
    `This note is dated ${month}. It changes the GSTR-1 for ${month}, and no later return will carry it. `
    + 'If that return is already filed, date the note this month instead.'
  );
}
