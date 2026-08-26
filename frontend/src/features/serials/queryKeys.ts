export const serialQueryKeys = {
  all: ['serials'] as const,
  available: (productId: number, search: string, page: number) =>
    ['serials', 'available', productId, search, page] as const,
};
