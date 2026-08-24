import { useState } from 'react';
import { CheckSquare, Plus, Trash2, CheckCircle2, AlertCircle } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { Task, TaskSubtask } from '@/types/task';
import type { Agent } from '@/types/agent';

interface AddTaskModalProps {
  isOpen: boolean;
  onClose: () => void;
  onTaskCreated: (task: Task) => void;
  agents: Agent[];
}

export function AddTaskModal({
  isOpen,
  onClose,
  onTaskCreated,
  agents,
}: AddTaskModalProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [agentId, setAgentId] = useState(agents[0]?.id || 'agent-bolt');
  const [priority, setPriority] = useState<number>(2);
  const [projectId, setProjectId] = useState('proj-core');

  const [subtasks, setSubtasks] = useState<string[]>([
    'Deconstruct requirements & check AST dependencies',
    'Write code module and unit test suites',
  ]);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const handleClose = () => {
    setTitle('');
    setDescription('');
    setStatusMsg(null);
    onClose();
  };

  const handleAddSubtaskField = () => {
    setSubtasks((prev) => [...prev, '']);
  };

  const handleRemoveSubtaskField = (idx: number) => {
    setSubtasks((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubtaskChange = (idx: number, val: string) => {
    setSubtasks((prev) => prev.map((s, i) => (i === idx ? val : s)));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setIsSubmitting(true);
    setStatusMsg(null);

    const formattedSubtasks: TaskSubtask[] = subtasks
      .filter((s) => s.trim().length > 0)
      .map((s, idx) => ({
        id: `st-${Date.now()}-${idx}`,
        title: s.trim(),
        completed: false,
      }));

    const newTask: Task = {
      id: `task-${Date.now().toString(36)}`,
      company_id: getActiveCompanyId(),
      project_id: projectId,
      title: title.trim(),
      description: description.trim(),
      status: 'pending',
      priority: priority as any,
      assigned_agent_id: agentId,
      subtasks: formattedSubtasks,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    try {
      const created = await apiClient.post<Task>(
        `/api/v1/companies/${getActiveCompanyId()}/tasks`,
        newTask
      );
      onTaskCreated(created);
      setStatusMsg({ type: 'success', text: `Task '${created.title}' created!` });
      setTimeout(() => {
        handleClose();
      }, 700);
    } catch {
      // Fallback
      onTaskCreated(newTask);
      handleClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Dispatch New Autonomous Task">
      <form onSubmit={handleSubmit} className="space-y-4 font-sans text-xs">
        {statusMsg && (
          <div
            className={`p-3 rounded border text-xs flex items-center gap-2 ${
              statusMsg.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
            }`}
          >
            {statusMsg.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
            <span>{statusMsg.text}</span>
          </div>
        )}

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Task Objective Title *
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Implement High-Throughput Redis Cache for Vector Memory"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            required
          />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Assign Agent
            </label>
            <select
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.role})
                </option>
              ))}
              {agents.length === 0 && (
                <>
                  <option value="agent-bolt">Bolt-03 (Backend)</option>
                  <option value="agent-nova">Nova-02 (CTO)</option>
                  <option value="agent-sage">Sage-05 (AI Research)</option>
                  <option value="agent-shield">Shield-07 (Security)</option>
                </>
              )}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Priority Level
            </label>
            <select
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value={1}>P1 - Critical Urgent</option>
              <option value={2}>P2 - Standard Priority</option>
              <option value={3}>P3 - Background Queue</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Project Tag
            </label>
            <input
              type="text"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="e.g. proj-core"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        {/* Sub-tasks checklist builder */}
        <div className="space-y-2 pt-2 border-t border-white/[0.08]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-[#FFB020] uppercase font-bold">
              Sub-Task Deliverables ({subtasks.length})
            </span>
            <button
              type="button"
              onClick={handleAddSubtaskField}
              className="text-[10px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
            >
              <Plus size={11} /> Add Subtask
            </button>
          </div>

          <div className="space-y-2">
            {subtasks.map((st, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-gray-500 w-4 font-bold">{idx + 1}.</span>
                <input
                  type="text"
                  value={st}
                  onChange={(e) => handleSubtaskChange(idx, e.target.value)}
                  placeholder="Subtask requirement..."
                  className="flex-1 px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
                {subtasks.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveSubtaskField(idx)}
                    className="p-1 text-gray-500 hover:text-rose-400 cursor-pointer"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Detailed Acceptance Criteria & Context
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Specify technical parameters, AST requirements, or performance bounds..."
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={isSubmitting}
            icon={<CheckSquare size={14} />}
          >
            {isSubmitting ? 'Dispatching...' : 'Dispatch Task'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
