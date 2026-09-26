import { describe, it, expect, vi, beforeAll } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '@/test/setup';
import type { PipelineItem } from '@/types/pipeline';
import { PipelineBuilderCanvas } from '../PipelineBuilderCanvas';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  (globalThis as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly ??= class {
    m22 = 1;
  };
});

const PIPELINE: PipelineItem = {
  id: 'p1',
  name: 'Release',
  status: 'idle',
  success_rate: 1,
  trigger: 'manual',
  stages: [],
  canvas_nodes: [
    { id: 'n1', type: 'agent_task', label: 'Kickoff', x: 0, y: 0, category: 'trigger' },
    { id: 'n2', type: 'agent_task', label: 'Summarize', x: 280, y: 0, category: 'ai', agent: 'Ada' },
  ],
  canvas_edges: [{ id: 'e1', from: 'n1', to: 'n2' }],
};

// The Canvas reuses this builder's node components; its own behavior must not change.
describe('PipelineBuilderCanvas', () => {
  it('draws the saved graph and saves it back unchanged', () => {
    server.use(http.get('*/api/v1/nodes', () => HttpResponse.json({ items: [] })));
    const onSave = vi.fn();
    render(<PipelineBuilderCanvas pipeline={PIPELINE} onSave={onSave} onClose={() => {}} />);

    expect(screen.getByText('Kickoff')).toBeTruthy();
    expect(screen.getByText('Summarize')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Save Pipeline/ }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const [nodes, edges, name] = onSave.mock.calls[0]!;
    expect(name).toBe('Release');
    expect(nodes.map((n: { id: string; label: string; category: string }) => [n.id, n.label, n.category])).toEqual([
      ['n1', 'Kickoff', 'trigger'],
      ['n2', 'Summarize', 'ai'],
    ]);
    expect(edges).toEqual([{ id: 'e1', from: 'n1', to: 'n2' }]);
  });
});
