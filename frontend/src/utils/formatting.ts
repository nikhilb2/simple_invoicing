export default function formatCurrency(value: number, currencyCode = 'USD') {
    const locale = currencyCode === 'INR' ? 'en-IN' : 'en-US';
    try {
        return new Intl.NumberFormat(locale, {
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
