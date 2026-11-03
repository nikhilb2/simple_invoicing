export const gstr3bQueryKeys = {
  all: ['gstr3b'] as const,
  // The period is in the key so a worksheet can never be shown under another
  // period's heading, which is the bug GSTR-1 still has open as #612.
  worksheet: (fromDate: string, toDate: string) => ['gstr3b', 'worksheet', fromDate, toDate] as const,
};
