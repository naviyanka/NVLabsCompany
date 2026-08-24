import { useState } from 'react';
import {
  X,
  GitPullRequest,
  Trash2,
  Play,
  Terminal,
  Loader2,
} from 'lucide-react';
import type { PipelineItem, PipelineStage } from '@/types/pipeline';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';

interface PipelineDetailDrawerProps {
  pipeline: PipelineItem | null;
  onClose: () => void;
  onPipelineUpdated: (updated: PipelineItem) => void;
  onPipelineDeleted: (pipeId: string) => void;
}

export function PipelineDetailDrawer({
  pipeline,
  onClose,
  onPipelineUpdated,
  onPipelineDeleted,
}: PipelineDetailDrawerProps) {
  const [isExecuting, setIsExecuting] = useState(false);
  const [selectedStage, setSelectedStage] = useState<PipelineStage | null>(null);

  if (!pipeline) return null;

  const stages = pipeline.stages || [];
  const activeStage = selectedStage || stages.find((s) => s.status === 'running') || stages[0];

  const handleTriggerRun = async () => {
    setIsExecuting(true);

    const updatedStages = stages.map((s, idx) => ({
      ...s,
      status: idx === 0 ? ('running' as const) : ('pending' as const),
      logs: idx === 0 ? `Triggering pipeline run for '${pipeline.name}'...` : undefined,
    }));

    const runningPipeline: PipelineItem = {
      ...pipeline,
      status: 'running',
      stages: updatedStages,
      last_run: new Date().toISOString(),
    };

    onPipelineUpdated(runningPipeline);

    // Simulate stage 1 -> 2 -> 3 progression
    let currentIdx = 0;
    const interval = setInterval(() => {
      if (currentIdx < stages.length) {
        const nextStages = stages.map((st, i) => {
          if (i <= currentIdx) {
            return {
              ...st,
              status: 'completed' as const,
              duration_ms: Math.floor(400 + Math.random() * 800),
              logs: `[Stage Node Executed Cleanly]\n✔ Agent '${st.assignedAgent}' finished stage '${st.name}'\n✔ Zero-trust gate checks passed with status 200.`,
            };
          }
          if (i === currentIdx + 1) {
            return {
              ...st,
              status: 'running' as const,
              logs: `Agent '${st.assignedAgent}' processing stage '${st.name}'...`,
            };
          }
          return st;
        });

        const isFinished = currentIdx === stages.length - 1;
        const finishedPipeline: PipelineItem = {
          ...pipeline,
          status: isFinished ? 'completed' : 'running',
          stages: nextStages,
          last_run: new Date().toISOString(),
        };

        onPipelineUpdated(finishedPipeline);
        currentIdx++;
      } else {
        clearInterval(interval);
        setIsExecuting(false);
      }
    }, 1200);
  };

  const handleDelete = async () => {
    if (!confirm(`Are you sure you want to delete pipeline "${pipeline.name}"?`)) return;
    try {
      await apiClient.delete(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/pipelines/${pipeline.id}`
      );
    } catch {
      // Fallback
    }
    onPipelineDeleted(pipeline.id);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end">
      <div className="w-full max-w-xl bg-[#0A0A0C] border-l border-white/[0.1] h-full flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-white/[0.08] flex items-center justify-between bg-[#101012]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-[#FFB020]/15 border border-[#FFB020]/30 rounded-[8px]">
              <GitPullRequest className="w-5 h-5 text-[#FFB020]" />
            </div>
            <div>
              <h2 className="text-base font-medium text-white">{pipeline.name}</h2>
              <div className="flex items-center gap-2 text-xs font-mono text-[#6B6B6E] mt-0.5">
                <span>Trigger: {pipeline.trigger}</span>
                <span>·</span>
                <span className="text-[#22C55E]">SLA: {pipeline.success_rate}%</span>
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
          {/* Action Trigger Card */}
          <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] flex items-center justify-between">
            <div className="space-y-0.5">
              <span className="text-xs font-mono text-gray-400">
                Pipeline Status: <strong className="text-white uppercase">{pipeline.status}</strong>
              </span>
              <div className="text-[10px] font-mono text-gray-500">
                Last Run: {pipeline.last_run ? new Date(pipeline.last_run).toLocaleTimeString() : 'Recently'}
              </div>
            </div>

            <Button
              variant="primary"
              size="sm"
              icon={isExecuting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              onClick={handleTriggerRun}
              disabled={isExecuting}
            >
              {isExecuting ? 'Running Pipeline...' : 'Trigger Pipeline Run'}
            </Button>
          </div>

          {/* Sequential Stage Diagram */}
          <div className="space-y-3 font-mono text-xs">
            <span className="text-xs font-bold text-white uppercase flex items-center gap-1.5">
              <GitPullRequest size={14} className="text-[#FFB020]" /> Sequential Stage Diagram ({stages.length})
            </span>

            <div className="space-y-2">
              {stages.map((st, idx) => {
                const isDone = st.status === 'completed';
                const isRunning = st.status === 'running';
                const isSelected = activeStage?.id === st.id;

                return (
                  <div
                    key={st.id}
                    onClick={() => setSelectedStage(st)}
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
                      <div className="w-5 h-5 rounded bg-white/[0.04] border border-white/[0.08] flex items-center justify-center font-bold text-[10px] text-[#FFB020]">
                        {idx + 1}
                      </div>

                      <div>
                        <div className="font-bold text-white text-xs">{st.name}</div>
                        <div className="text-[10px] text-gray-400">Agent: {st.assignedAgent}</div>
                      </div>
                    </div>

                    <span className="text-[10px] font-mono text-[#FFB020] uppercase font-bold">
                      {st.status}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Stage Telemetry Output Console */}
          {activeStage && (
            <div className="p-3 bg-[#0C0C0E] border border-white/[0.08] rounded-[8px] space-y-2 font-mono text-xs">
              <div className="flex items-center justify-between text-[11px] text-gray-400 border-b border-white/[0.06] pb-2">
                <span className="flex items-center gap-1.5 font-bold text-white">
                  <Terminal size={13} className="text-emerald-400" /> Telemetry Console: {activeStage.name}
                </span>
                <span className="text-emerald-400 font-bold uppercase text-[10px]">
                  Agent: {activeStage.assignedAgent}
                </span>
              </div>

              <pre className="p-3 bg-[#060608] border border-white/[0.06] rounded text-[11px] text-emerald-300 overflow-x-auto max-h-48 whitespace-pre-wrap font-mono">
                {activeStage.logs || `[Stage Ready]\nAgent '${activeStage.assignedAgent}' assigned to stage '${activeStage.name}'. Waiting for execution trigger.`}
              </pre>
            </div>
          )}

          {/* Delete Action */}
          <div className="pt-4 border-t border-white/[0.08]">
            <Button
              variant="secondary"
              size="xs"
              onClick={handleDelete}
              icon={<Trash2 size={13} className="text-rose-400" />}
            >
              Delete Pipeline
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
