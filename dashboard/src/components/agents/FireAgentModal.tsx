import { useState } from 'react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import type { Agent } from '@/types/agent';
import { AlertTriangle, Trash2 } from 'lucide-react';

interface FireAgentModalProps {
  agent: Agent | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (agent: Agent) => Promise<void>;
}

export function FireAgentModal({ agent, isOpen, onClose, onConfirm }: FireAgentModalProps) {
  const [firing, setFiring] = useState(false);

  if (!agent) return null;

  const handleConfirm = async () => {
    setFiring(true);
    try {
      await onConfirm(agent);
      onClose();
    } catch (err) {
      console.error('Failed to fire agent', err);
    } finally {
      setFiring(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Fire ${agent.name}?`}
    >
      <div className="space-y-4">
        {/* Warning Banner */}
        <div className="p-3.5 bg-red-500/10 border border-red-500/20 rounded-[8px] flex items-start gap-3">
          <AlertTriangle size={18} className="text-red-400 shrink-0 mt-0.5" />
          <div className="space-y-1 text-xs">
            <p className="font-semibold text-red-200">
              Confirm Agent Termination
            </p>
            <p className="text-red-300/80 leading-relaxed font-sans">
              Are you sure you want to fire <strong className="text-red-200">{agent.name}</strong> ({agent.title || agent.role})?
              This action cannot be undone.
            </p>
          </div>
        </div>

        {/* Agent Details Summary */}
        <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2 text-xs font-mono">
          <div className="flex justify-between">
            <span className="text-[#6B6B6E]">Agent Name:</span>
            <span className="text-[#F2F1EE] font-medium">{agent.name}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[#6B6B6E]">Role / Title:</span>
            <span className="text-[#A8A8AB]">{agent.title || agent.role}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[#6B6B6E]">Provider & Model:</span>
            <span className="text-[#FFB020]">{agent.adapter_type} ({agent.model || 'default'})</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[#6B6B6E]">Status:</span>
            <span className="uppercase text-[#22C55E]">{agent.status}</span>
          </div>
        </div>

        <p className="text-[11px] text-[#6B6B6E] font-mono leading-relaxed">
          Firing this agent will stop all background processes, revoke tool permissions, and permanently remove the record from the company workforce directory.
        </p>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/[0.08]">
          <Button
            variant="secondary"
            size="sm"
            onClick={onClose}
            disabled={firing}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={firing}
            icon={<Trash2 size={14} />}
            onClick={handleConfirm}
            className="bg-red-600 hover:bg-red-500 text-white border-red-500"
          >
            Fire Agent
          </Button>
        </div>
      </div>
    </Modal>
  );
}
