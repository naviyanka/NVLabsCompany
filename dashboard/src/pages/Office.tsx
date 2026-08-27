import { useState, useCallback, useEffect } from 'react';
import { OpenOffice2DView } from '@/components/office2d/OpenOffice2DView';
import { listAgents } from '@/api/agents';
import type { Agent } from '@/types/agent';

/**
 * Office page - 2D OpenOffice pixel floor with autonomous roaming agents,
 * wired to the live backend workforce.
 *
 * A 3D isometric view built on Three.js was removed: it rendered from static
 * layout config rather than live state, so it read as a product feature that
 * was permanently stale. Rebuild it against real agent positions if it returns.
 */
export function Office() {
  const [realAgents, setRealAgents] = useState<Agent[]>([]);

  const loadAgents = useCallback(async () => {
    try {
      const agents = await listAgents();
      setRealAgents(agents);
    } catch (err) {
      console.warn('Failed to load real backend agents for Office view:', err);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  return <OpenOffice2DView realAgents={realAgents} />;
}
