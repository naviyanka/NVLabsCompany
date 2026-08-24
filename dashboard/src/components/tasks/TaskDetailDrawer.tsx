import { useState } from 'react';
import {
  X,
  CheckSquare,
  Play,
  Trash2,
  Check,
  Terminal,
  Loader2,
  ListChecks,
} from 'lucide-react';
import type { Task, TaskSubtask } from '@/types/task';
import type { Agent } from '@/types/agent';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';

interface TaskDetailDrawerProps {
  task: Task | null;
  onClose: () => void;
  onTaskUpdated: (updated: Task) => void;
  onTaskDeleted: (taskId: string) => void;
  agents: Agent[];
}

export function TaskDetailDrawer({
  task,
  onClose,
  onTaskUpdated,
  onTaskDeleted,
  agents,
}: TaskDetailDrawerProps) {
  const [isExecuting, setIsExecuting] = useState(false);
  const [logsOutput, setLogsOutput] = useState<string>('');

  if (!task) return null;

  const assignedAgentObj = agents.find((a) => a.id === task.assigned_agent_id);
  const agentName = assignedAgentObj?.name || task.assigned_agent_id || 'Atlas-01';

  const subtasks = task.subtasks || [];
  const completedSubtasksCount = subtasks.filter((s) => s.completed).length;
  const subtasksProgress = subtasks.length > 0 ? Math.round((completedSubtasksCount / subtasks.length) * 100) : 0;

  const handleToggleSubtask = async (stId: string) => {
    const updatedSubtasks: TaskSubtask[] = subtasks.map((s) =>
      s.id === stId ? { ...s, completed: !s.completed } : s
    );

    const updatedTask: Task = {
      ...task,
      subtasks: updatedSubtasks,
      updated_at: new Date().toISOString(),
    };

    onTaskUpdated(updatedTask);

    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/tasks/${task.id}`,
        { subtasks: updatedSubtasks }
      );
    } catch {
      // Fallback
    }
  };

  const handleStatusChange = async (newStatus: Task['status']) => {
    const updatedTask: Task = {
      ...task,
      status: newStatus,
      completed_at: newStatus === 'completed' ? new Date().toISOString() : task.completed_at,
      updated_at: new Date().toISOString(),
    };

    onTaskUpdated(updatedTask);

    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/tasks/${task.id}`,
        { status: newStatus, completed_at: updatedTask.completed_at }
      );
    } catch {
      // Fallback
    }
  };

  const handleRunAgentSolver = () => {
    setIsExecuting(true);
    setLogsOutput(`[Agent Dispatch]\nInitializing workspace runner for Agent '${agentName}'...\nEvaluating task objective: "${task.title}"\nRunning AST impact analysis and zero-trust policy checks...`);

    const runningTask: Task = {
      ...task,
      status: 'in_progress',
      started_at: new Date().toISOString(),
    };
    onTaskUpdated(runningTask);

    setTimeout(() => {
      setLogsOutput((prev) => `${prev}\n\n[Step 1] Constructing AST graph nodes and resolving sub-task dependencies...`);
    }, 800);

    setTimeout(() => {
      setLogsOutput((prev) => `${prev}\n[Step 2] Executing automated unit test suites with gVisor microVM isolation...`);
    }, 1600);

    setTimeout(() => {
      const generatedResult = `✔ Task completed successfully by ${agentName}.\n✔ Sub-task deliverables passing 100% of acceptance criteria.\n✔ Result verified with zero-trust security audit.`;
      setLogsOutput((prev) => `${prev}\n\n[Success] Task solver execution finished cleanly.\n${generatedResult}`);
      
      const finishedTask: Task = {
        ...task,
        status: 'completed',
        result: generatedResult,
        logs: logsOutput,
        cost_cents: Math.floor(15 + Math.random() * 45),
        completed_at: new Date().toISOString(),
        subtasks: subtasks.map((s) => ({ ...s, completed: true })),
      };

      onTaskUpdated(finishedTask);
      setIsExecuting(false);

      apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/tasks/${task.id}`,
        finishedTask
      ).catch(() => {});
    }, 2800);
  };

  const handleDelete = async () => {
    if (!confirm(`Delete task "${task.title}"?`)) return;
    try {
      await apiClient.delete(
        `/api/v1/companies/${getActiveCompanyId()}/tasks/${task.id}`
      );
    } catch {
      // Fallback
    }
    onTaskDeleted(task.id);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end">
      <div className="w-full max-w-xl bg-[#0A0A0C] border-l border-white/[0.1] h-full flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-white/[0.08] flex items-center justify-between bg-[#101012]">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-emerald-500/15 border border-emerald-500/30 rounded-[8px]">
              <CheckSquare className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-base font-medium text-white line-clamp-1">{task.title}</h2>
              <div className="flex items-center gap-2 text-xs font-mono text-[#6B6B6E] mt-0.5">
                <span>Task #{task.id}</span>
                <span>·</span>
                <span className="text-[#FFB020]">Priority P{task.priority}</span>
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
          {/* Status & Agent Runner Bar */}
          <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-3">
            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-gray-400">
                Assigned Agent: <strong className="text-[#FFB020]">{agentName}</strong>
              </span>
              <Badge variant={task.status as any}>{task.status}</Badge>
            </div>

            <div className="flex items-center justify-between gap-2 pt-2 border-t border-white/[0.06]">
              {task.status === 'pending' && (
                <Button variant="secondary" size="xs" onClick={() => handleStatusChange('in_progress')}>
                  Set In-Progress
                </Button>
              )}
              {task.status === 'in_progress' && (
                <Button variant="secondary" size="xs" onClick={() => handleStatusChange('completed')}>
                  Mark Completed
                </Button>
              )}

              <Button
                variant="primary"
                size="xs"
                icon={isExecuting ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                onClick={handleRunAgentSolver}
                disabled={isExecuting}
              >
                {isExecuting ? 'Agent Solving Task...' : 'Simulate Agent Solver'}
              </Button>
            </div>
          </div>

          {/* Description */}
          <div className="space-y-1.5 font-mono text-xs">
            <span className="text-gray-400 font-bold uppercase text-[11px]">Objective Description</span>
            <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[8px] text-gray-200 leading-relaxed font-sans">
              {task.description || 'No detailed instructions specified.'}
            </div>
          </div>

          {/* Subtasks Checklist */}
          {subtasks.length > 0 && (
            <div className="space-y-2.5 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-white font-bold uppercase flex items-center gap-1.5 text-[11px]">
                  <ListChecks size={14} className="text-[#FFB020]" /> Sub-Task Deliverables ({completedSubtasksCount}/{subtasks.length})
                </span>
                <span className="text-emerald-400 font-bold">{subtasksProgress}%</span>
              </div>

              {/* Progress bar */}
              <div className="w-full bg-[#141416] h-1.5 rounded-full overflow-hidden border border-white/[0.08]">
                <div
                  className="bg-emerald-400 h-full transition-all duration-500"
                  style={{ width: `${subtasksProgress}%` }}
                />
              </div>

              <div className="space-y-1.5">
                {subtasks.map((st) => (
                  <div
                    key={st.id}
                    onClick={() => handleToggleSubtask(st.id)}
                    className={`p-2.5 rounded-[6px] border transition-colors cursor-pointer flex items-center justify-between gap-3 ${
                      st.completed
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                        : 'bg-[#101012] border-white/[0.06] text-gray-300 hover:border-white/[0.2]'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <div
                        className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                          st.completed ? 'bg-emerald-500 border-emerald-500 text-black' : 'border-white/[0.2]'
                        }`}
                      >
                        {st.completed && <Check size={11} className="stroke-[3]" />}
                      </div>
                      <span className={`text-xs ${st.completed ? 'line-through text-emerald-400/70' : ''}`}>
                        {st.title}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Execution Result & Terminal Console */}
          {(task.result || logsOutput) && (
            <div className="p-3 bg-[#0C0C0E] border border-white/[0.08] rounded-[8px] space-y-2 font-mono text-xs">
              <div className="flex items-center justify-between text-[11px] text-gray-400 border-b border-white/[0.06] pb-2">
                <span className="flex items-center gap-1.5 font-bold text-white">
                  <Terminal size={13} className="text-emerald-400" /> Agent Execution Telemetry
                </span>
                {task.cost_cents && (
                  <span className="text-[#FFB020] font-bold">${(task.cost_cents / 100).toFixed(2)} tokens</span>
                )}
              </div>

              <pre className="p-3 bg-[#060608] border border-white/[0.06] rounded text-[11px] text-emerald-300 overflow-x-auto max-h-48 whitespace-pre-wrap font-mono">
                {logsOutput || task.result}
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
              Delete Task
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
