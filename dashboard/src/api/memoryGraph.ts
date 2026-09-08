/**
 * Memory graph API.
 *
 * The graph is derived on read by the backend from memory records and, for a
 * company with an Obsidian vault, from that vault's notes and their wikilinks.
 * There is no edge table on either side, so nothing here caches or reconciles:
 * one request returns the whole current graph.
 */

import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import { MemoryGraphData } from '@/types/memoryGraph';

/**
 * Fetch the active company's graph.
 *
 * The company comes from the session, the same way every other page resolves
 * it. Putting a different UUID in the path does not widen access: the API
 * validates it against the authenticated principal and answers 403, so this is
 * addressing, not authorization.
 */
export async function fetchMemoryGraph(): Promise<MemoryGraphData> {
  return apiClient.get<MemoryGraphData>(
    `/api/v1/companies/${getActiveCompanyId()}/memory/graph`
  );
}
