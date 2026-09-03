import type { ShareResourceType } from '../../types/api';

export const shareQueryKeys = {
  all: ['share-links'] as const,
  /**
   * The live link for one document. The period is part of the key because a
   * statement link is scoped to its dates — April's link and May's link are
   * different rows and must not share a cache entry.
   */
  link: (
    resourceType: ShareResourceType,
    resourceId: number,
    fromDate?: string,
    toDate?: string,
  ) => ['share-links', 'link', resourceType, resourceId, fromDate ?? 'none', toDate ?? 'none'] as const,
  list: (resourceType: ShareResourceType, resourceId: number) =>
    ['share-links', 'list', resourceType, resourceId] as const,
};
