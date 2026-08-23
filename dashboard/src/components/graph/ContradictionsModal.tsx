import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { AlertTriangle, CheckCircle2, Trash2, ArrowRight } from 'lucide-react';
import { MemoryGraphNode } from '@/types/memoryGraph';

interface ContradictionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  contradictionNodes: MemoryGraphNode[];
  allNodes: MemoryGraphNode[];
  onSelectNode: (node: MemoryGraphNode) => void;
  onResolve: (nodeId: string, action: 'prune' | 'override' | 'archive') => void;
}

export function ContradictionsModal({
  isOpen,
  onClose,
  contradictionNodes,
  allNodes,
  onSelectNode,
  onResolve,
}: ContradictionsModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Belief Contradictions & Conflict Resolution"
    >
      <div className="space-y-4 max-h-[70vh] overflow-y-auto">
        <p className="text-xs text-[#A8A8AB] leading-relaxed">
          The memory graph detects conflicting premises, empirical evaluation regressions, and parameter mismatches between agent squad decisions.
        </p>

        {contradictionNodes.length === 0 ? (
          <div className="p-8 text-center bg-[#141416] border border-white/[0.06] rounded-[8px] space-y-2">
            <CheckCircle2 className="w-8 h-8 text-[#22C55E] mx-auto" />
            <div className="text-sm font-medium text-[#F2F1EE]">
              Graph Consistency Nominal
            </div>
            <p className="text-xs text-[#6B6B6E]">
              Zero active belief conflicts or empirical regressions in the collective memory.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {contradictionNodes.map((cNode) => {
              const targetNode = allNodes.find(
                (n) => n.id === cNode.contradiction_target_id
              );

              return (
                <div
                  key={cNode.id}
                  className="p-3.5 bg-red-500/10 border border-red-500/30 rounded-[8px] space-y-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                      <span className="font-mono text-xs font-semibold text-red-300">
                        {cNode.label}
                      </span>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-300 text-[10px] font-mono">
                      Agent: {cNode.agent_id}
                    </span>
                  </div>

                  <p className="text-xs text-red-100/90 leading-relaxed font-sans">
                    {cNode.summary}
                  </p>

                  {targetNode && (
                    <div className="p-2.5 bg-[#0E0E10]/80 rounded-[6px] border border-red-500/20 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-red-400 font-mono">Conflicts with:</span>
                        <span className="text-[#F2F1EE] font-medium truncate max-w-xs">
                          {targetNode.label}
                        </span>
                      </div>
                      <button
                        onClick={() => {
                          onSelectNode(targetNode);
                          onClose();
                        }}
                        className="text-[11px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                      >
                        <span>Inspect Target</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2 pt-2 border-t border-red-500/20">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => onResolve(cNode.id, 'override')}
                    >
                      Synthesize & Resolve
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      icon={<Trash2 size={13} />}
                      onClick={() => onResolve(cNode.id, 'prune')}
                    >
                      Prune Contradiction
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex justify-end pt-2 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}
