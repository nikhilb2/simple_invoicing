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
