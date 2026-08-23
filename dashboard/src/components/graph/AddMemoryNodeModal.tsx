import React, { useState } from 'react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import {
  MemoryNodeType,
  MemoryClusterId,
  MemoryGraphNode,
} from '@/types/memoryGraph';
import { MEMORY_CLUSTERS } from '@/lib/memoryGraphAdapter';

interface AddMemoryNodeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAddNode: (data: {
    label: string;
    type: MemoryNodeType;
    community: MemoryClusterId;
    agent_id: string;
    importance: number;
    confidence: number;
    summary: string;
    tags: string[];
    contradiction_target_id?: string;
    contradiction_reason?: string;
  }) => void;
  existingNodes: MemoryGraphNode[];
}

export function AddMemoryNodeModal({
  isOpen,
  onClose,
  onAddNode,
  existingNodes,
}: AddMemoryNodeModalProps) {
  const [label, setLabel] = useState('');
  const [type, setType] = useState<MemoryNodeType>('fact');
  const [community, setCommunity] = useState<MemoryClusterId>('systems_routing');
  const [agentId, setAgentId] = useState('agent-bolt');
  const [importance, setImportance] = useState(0.85);
  const [confidence, setConfidence] = useState(0.92);
  const [summary, setSummary] = useState('');
  const [tagsInput, setTagsInput] = useState('custom, verified');
  const [contradictionTarget, setContradictionTarget] = useState('');
  const [contradictionReason, setContradictionReason] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim()) return;

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);

    onAddNode({
      label,
      type,
      community,
      agent_id: agentId,
      importance: Number(importance),
      confidence: Number(confidence),
      summary: summary || label,
      tags,
      contradiction_target_id: type === 'contradiction' ? contradictionTarget : undefined,
      contradiction_reason: type === 'contradiction' ? contradictionReason : undefined,
    });

    onClose();
    setLabel('');
    setSummary('');
    setContradictionReason('');
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Inject Memory & Knowledge Node">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
            Node Label / Headline
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Fact: Redis Cluster p99 Roundtrip is 1.2ms"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Memory Node Type
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as MemoryNodeType)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="fact">Hard Fact</option>
              <option value="observation">Observation / Signal</option>
              <option value="decision">Architectural Decision</option>
              <option value="derived">Derived Knowledge / Rule</option>
              <option value="experience">Episodic Experience</option>
              <option value="tool_result">Tool Execution Result</option>
              <option value="knowledge">Standard / Policy</option>
              <option value="goal">Strategic Goal</option>
              <option value="contradiction">Contradiction / Conflict</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Semantic Cluster
            </label>
            <select
              value={community}
              onChange={(e) => setCommunity(e.target.value as MemoryClusterId)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              {MEMORY_CLUSTERS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Owner Agent
            </label>
            <select
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="agent-atlas">Atlas-01 (CEO)</option>
              <option value="agent-nova">Nova-02 (CTO)</option>
              <option value="agent-bolt">Bolt-03 (Backend)</option>
              <option value="agent-pixel">Pixel-04 (Frontend)</option>
              <option value="agent-sage">Sage-05 (AI Research)</option>
              <option value="agent-shield">Shield-07 (Security)</option>
              <option value="agent-forge">Forge-08 (DevOps)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Importance (0.1 - 1.0)
            </label>
            <input
              type="number"
              step="0.05"
              min="0.1"
              max="1.0"
              value={importance}
              onChange={(e) => setImportance(parseFloat(e.target.value))}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Confidence (0.1 - 1.0)
            </label>
            <input
              type="number"
              step="0.05"
              min="0.1"
              max="1.0"
              value={confidence}
              onChange={(e) => setConfidence(parseFloat(e.target.value))}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        {/* If Contradiction, select conflicting node */}
        {type === 'contradiction' && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-[6px] space-y-3">
            <div>
              <label className="block text-xs font-mono text-red-300 uppercase mb-1">
                Target Node in Conflict
              </label>
              <select
                value={contradictionTarget}
                onChange={(e) => setContradictionTarget(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-red-500/40 rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none"
                required
              >
                <option value="">Select target node...</option>
                {existingNodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    [{n.type.toUpperCase()}] {n.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-mono text-red-300 uppercase mb-1">
                Conflict Explanation & Evidence
              </label>
              <textarea
                value={contradictionReason}
                onChange={(e) => setContradictionReason(e.target.value)}
                rows={2}
                placeholder="Explain why this belief contradicts the target premise..."
                className="w-full px-3 py-2 bg-[#141416] border border-red-500/40 rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none"
                required
              />
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
            Detailed Summary / Reasoning Content
          </label>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={3}
            placeholder="Comprehensive description of this fact, observation, or derived thesis..."
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            required
          />
        </div>

        <div>
          <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
            Tags (comma-separated)
          </label>
          <input
            type="text"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="e.g. latency, redis, p99, telemetry"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit">
            Commit to Graph
          </Button>
        </div>
      </form>
    </Modal>
  );
}
