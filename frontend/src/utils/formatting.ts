function localeFor(currencyCode: string) {
    return currencyCode === 'INR' ? 'en-IN' : 'en-US';
}

export default function formatCurrency(value: number, currencyCode = 'USD') {
    try {
        return new Intl.NumberFormat(localeFor(currencyCode), {
            style: 'currency',
            currency: currencyCode,
            maximumFractionDigits: 2,
        }).format(value);
    } catch {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 2,
        }).format(value);
    }
}

/**
 * Compact currency for tight spaces (e.g. dashboard KPI cards) so large
 * figures don't overflow. INR renders lakh/crore (₹1.2Cr), others use M/K.
 * Values under 1,000 fall back to the full format to stay precise.
 */
export function formatCompactCurrency(value: number, currencyCode = 'USD') {
    if (Math.abs(value) < 1000) {
        return formatCurrency(value, currencyCode);
    }
    try {
        return new Intl.NumberFormat(localeFor(currencyCode), {
            style: 'currency',
            currency: currencyCode,
            notation: 'compact',
            maximumFractionDigits: 1,
        }).format(value);
    } catch {
        return formatCurrency(value, currencyCode);
    }
}

type DisplayDate = string | Date | null | undefined;

/** Calendar-only values are local dates, not UTC midnight timestamps. */
function displayDate(value: DisplayDate): Date | null {
    if (!value) return null;
    if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : value;
    }
    const calendar = /^(\d{4})-(\d{2})-(\d{2})(?=$|T)/.exec(value);
    if (calendar) {
        const [, year, month, day] = calendar.map(Number);
        const date = new Date(0);
        date.setFullYear(year, month - 1, day);
        date.setHours(0, 0, 0, 0);
        // Date normalizes impossible dates (e.g. 30 February) into another month.
        if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
            return null;
        }
        if (value.length === 10) return date;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function calendarLabel(date: Date): string {
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    return `${day}-${month}-${String(date.getFullYear()).padStart(4, '0')}`;
}

/** A display-only DD-MM-YYYY label, independent of the browser's locale. */
export function formatDate(value: DisplayDate): string {
    const date = displayDate(value);
    return date ? calendarLabel(date) : '—';
}

/** A local DD-MM-YYYY HH:mm label; timestamp offsets still describe instants. */
export function formatDateTime(value: DisplayDate): string {
    const date = displayDate(value);
    if (!date) return '—';
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${calendarLabel(date)} ${hours}:${minutes}`;
}
