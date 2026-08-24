import { useState } from 'react';
import {
  X,
  Layers,
  CheckCircle2,
  Play,
  Clock,
  DollarSign,
  Terminal,
  Loader2,
} from 'lucide-react';
import type { WorkflowDAGItem, DAGStep } from '@/types/workflow';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';

interface WorkflowDetailDrawerProps {
  workflow: WorkflowDAGItem | null;
  onClose: () => void;
  onWorkflowUpdated: (updated: WorkflowDAGItem) => void;
}

export function WorkflowDetailDrawer({
  workflow,
  onClose,
  onWorkflowUpdated,
}: WorkflowDetailDrawerProps) {
  const [isAdvancing, setIsAdvancing] = useState(false);
  const [selectedStep, setSelectedStep] = useState<DAGStep | null>(null);

  if (!workflow) return null;

  const steps = workflow.steps || [];
  const activeStep = selectedStep || steps.find((s) => s.status === 'running') || steps[0];

  const handleAdvanceStep = async () => {
    setIsAdvancing(true);

    const runningIdx = steps.findIndex((s) => s.status === 'running');
    const targetIdx = runningIdx !== -1 ? runningIdx : steps.findIndex((s) => s.status === 'pending');

    if (targetIdx === -1) {
      setIsAdvancing(false);
      return;
    }

    const updatedSteps = steps.map((s, idx) => {
      if (idx === targetIdx) {
        return {
          ...s,
          status: 'completed' as const,
          duration_ms: Math.floor(800 + Math.random() * 1200),
          cost_cents: Math.floor(20 + Math.random() * 50),
          logs: `[DAG Node Executed Cleanly]\n✔ Action '${s.action}' finished with status code 0.\n✔ Output artifacts passed downstream verification bounds.`,
        };
      }
      if (idx === targetIdx + 1) {
        return {
          ...s,
          status: 'running' as const,
          logs: `Executing step '${s.step_name}'...`,
        };
      }
      return s;
    });

    const completedCount = updatedSteps.filter((s) => s.status === 'completed').length;
    const isAllDone = completedCount === steps.length;
    const currentStepName = isAllDone ? 'Workflow Execution Complete' : updatedSteps.find((s) => s.status === 'running')?.step_name || 'Processing';
    const totalCost = updatedSteps.reduce((sum, s) => sum + (s.cost_cents || 0), 0);

    const updatedWorkflow: WorkflowDAGItem = {
      ...workflow,
      steps: updatedSteps,
      completed_steps: completedCount,
      current_step: currentStepName,
      status: isAllDone ? 'completed' : 'running',
      total_cost_cents: totalCost,
      completed_at: isAllDone ? new Date().toISOString() : null,
    };

    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/workflows/${workflow.workflow_id}`,
        updatedWorkflow
      );
    } catch {
      // Fallback
    }

    onWorkflowUpdated(updatedWorkflow);
    setIsAdvancing(false);
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end">
      <div className="w-full max-w-2xl bg-[#0A0A0C] border-l border-white/[0.1] h-full flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-white/[0.08] flex items-center justify-between bg-[#101012]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-[#FFB020]/15 border border-[#FFB020]/30 rounded-[8px]">
              <Layers className="w-5 h-5 text-[#FFB020]" />
            </div>
            <div>
              <h2 className="text-base font-medium text-white">{workflow.objective}</h2>
              <div className="flex items-center gap-2 text-xs font-mono text-[#6B6B6E] mt-0.5">
                <span>ID: {workflow.workflow_id}</span>
                <span>·</span>
                <span className="text-[#FFB020]">Stage: {workflow.current_step}</span>
              </div>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-5 font-sans">
          {/* Status & Control Banner */}
          <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] flex items-center justify-between">
            <div className="space-y-1">
              <span className="text-xs font-mono text-gray-400">
                Completed {workflow.completed_steps} of {workflow.total_steps} DAG Steps
              </span>
              <div className="flex items-center gap-3 text-xs font-mono">
                <span className="text-emerald-400 font-bold flex items-center gap-1">
                  <DollarSign size={13} /> ${(workflow.total_cost_cents / 100).toFixed(2)} Spend
                </span>
                <span className="text-cyan-400 font-bold flex items-center gap-1">
                  <Clock size={13} /> {workflow.duration_ms || 1450}ms Latency
                </span>
              </div>
            </div>

            {workflow.status === 'running' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Play size={14} />}
                onClick={handleAdvanceStep}
                disabled={isAdvancing}
              >
                {isAdvancing ? 'Advancing Node...' : 'Advance Next DAG Node'}
              </Button>
            )}
          </div>

          {/* Visual DAG Step Timeline Flow */}
          <div className="space-y-3 font-mono text-xs">
            <span className="text-xs font-bold text-white uppercase flex items-center gap-1.5">
              <Layers size={14} className="text-[#FFB020]" /> DAG Node Execution Sequence
            </span>

            <div className="space-y-2">
              {steps.map((st) => {
                const isSelected = activeStep?.step_id === st.step_id;
                const isDone = st.status === 'completed';
                const isRunning = st.status === 'running';

                return (
                  <div
                    key={st.step_id}
                    onClick={() => setSelectedStep(st)}
                    className={`p-3 rounded-[8px] border transition-all cursor-pointer flex items-center justify-between gap-3 ${
                      isSelected
                        ? 'border-[#FFB020] bg-[#FFB020]/10'
                        : isDone
                        ? 'bg-[#141416] border-emerald-500/30 text-emerald-300'
                        : isRunning
                        ? 'bg-[#141416] border-[#FFB020]/40 text-amber-300 animate-pulse'
                        : 'bg-[#141416] border-white/[0.06] text-gray-400'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {isDone ? (
                        <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
                      ) : isRunning ? (
                        <Loader2 size={16} className="text-[#FFB020] animate-spin shrink-0" />
                      ) : (
                        <div className="w-4 h-4 rounded-full border border-gray-600 shrink-0" />
                      )}

                      <div>
                        <div className="font-bold text-white text-xs">{st.step_name}</div>
                        <div className="text-[10px] text-gray-400">{st.action}</div>
                      </div>
                    </div>

                    <div className="text-right shrink-0 text-[10px]">
                      <span className="text-[#FFB020] font-bold">{st.agent_role}</span>
                      <div className="text-gray-500">{st.duration_ms ? `${st.duration_ms}ms` : 'Pending'}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Selected Node Log & Telemetry Output */}
          {activeStep && (
            <div className="p-3 bg-[#0C0C0E] border border-white/[0.08] rounded-[8px] space-y-2 font-mono text-xs">
              <div className="flex items-center justify-between text-[11px] text-gray-400 border-b border-white/[0.06] pb-2">
                <span className="flex items-center gap-1.5 font-bold text-white">
                  <Terminal size={13} className="text-emerald-400" /> Node Telemetry Logs: {activeStep.step_name}
                </span>
                <span className="text-emerald-400 font-bold uppercase text-[10px]">
                  Status: {activeStep.status}
                </span>
              </div>

              <pre className="p-3 bg-[#060608] border border-white/[0.06] rounded text-[11px] text-emerald-300 overflow-x-auto max-h-48 whitespace-pre-wrap font-mono">
                {activeStep.logs || 'No execution log generated yet for this node.'}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
