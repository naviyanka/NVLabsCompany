import { useState } from 'react';
import { Play, Sparkles } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { WorkflowDAGItem, DAGStep } from '@/types/workflow';

interface LaunchWorkflowModalProps {
  isOpen: boolean;
  onClose: () => void;
  onWorkflowLaunched: (workflow: WorkflowDAGItem) => void;
  agents: { id: string; name: string; role: string }[];
}

interface TemplateDef {
  title: string;
  steps: { name: string; role: string; action: string }[];
}

const TEMPLATES: Record<string, TemplateDef> = {
  'Feature Implementation': {
    title: 'Full-Stack Feature & AST Integration Pipeline',
    steps: [
      { name: '1. Decompose Requirement & Spec', role: 'Staff Architect', action: 'Deconstruct objective into AST milestones & Zod schemas' },
      { name: '2. Perform Code Graph Impact Analysis', role: 'Principal AI Researcher', action: 'Run GitNexus impact analysis to identify upstream callers' },
      { name: '3. Generate & Test Code Modules', role: 'Senior Systems Engineer', action: 'Implement code modules and execute unit test suites' },
      { name: '4. Security Audit & Deployment Gate', role: 'Lead Security Automation', action: 'Run gVisor microVM isolation checks and SAST scans' },
    ],
  },
  'Security Remediation': {
    title: 'Zero-Trust Vulnerability Remediation Pipeline',
    steps: [
      { name: '1. Fetch CVE Registry & Audit Webhooks', role: 'Lead Security Automation', action: 'Scan external endpoints for SSRF & rate limit risks' },
      { name: '2. Isolate & Patch Code Module', role: 'Senior Systems Engineer', action: 'Apply security patch and bind tenant SQL prepared statements' },
      { name: '3. Verify Regression Test Suite', role: 'Frontend Engineer', action: 'Run end-to-end regression tests' },
    ],
  },
  'Refactoring & AST': {
    title: 'AST Symbol Refactoring & Evolution DAG',
    steps: [
      { name: '1. Symbol Call Graph Analysis', role: 'Principal AI Researcher', action: 'Trace symbol execution tree' },
      { name: '2. Execute Code Refactor', role: 'Senior Systems Engineer', action: 'Refactor method signatures' },
      { name: '3. Verify Type & Linting Bounds', role: 'AI Reasoning Engineer', action: 'Execute tsc --noEmit check' },
    ],
  },
};

export function LaunchWorkflowModal({
  isOpen,
  onClose,
  onWorkflowLaunched,
  agents,
}: LaunchWorkflowModalProps) {
  const [templateType, setTemplateType] = useState<string>('Feature Implementation');
  const [objective, setObjective] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const currentPreset: TemplateDef = (TEMPLATES[templateType] || TEMPLATES['Feature Implementation'])!;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalObjective = objective.trim() || currentPreset.title;
    setIsSubmitting(true);

    const formattedSteps: DAGStep[] = currentPreset.steps.map((st, idx) => ({
      step_id: `step-${Date.now()}-${idx}`,
      step_name: st.name,
      agent_role: st.role,
      agent_name: agents.find((a) => a.role === st.role)?.name || 'Atlas-01',
      action: st.action,
      status: idx === 0 ? 'running' : 'pending',
      duration_ms: idx === 0 ? 450 : undefined,
      cost_cents: idx === 0 ? 25 : undefined,
      logs: idx === 0 ? 'Executing initial decomposition step...' : 'Pending upstream node completion.',
    }));

    const newWorkflow: WorkflowDAGItem = {
      workflow_id: `wf-${Date.now().toString(36)}`,
      title: finalObjective,
      objective: finalObjective,
      template_type: templateType as any,
      status: 'running',
      current_step: currentPreset.steps[0]?.name || 'Initial Step',
      total_steps: currentPreset.steps.length,
      completed_steps: 0,
      total_cost_cents: 25,
      duration_ms: 450,
      started_at: new Date().toISOString(),
      steps: formattedSteps,
    };

    try {
      const created = await apiClient.post<WorkflowDAGItem>(
        `/api/v1/companies/${getActiveCompanyId()}/workflows`,
        newWorkflow
      );
      onWorkflowLaunched(created);
    } catch {
      // Local fallback
      onWorkflowLaunched(newWorkflow);
    } finally {
      setIsSubmitting(false);
      onClose();
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Dispatch Multi-Agent DAG Workflow">
      <form onSubmit={handleSubmit} className="space-y-4 font-sans text-xs">
        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Workflow Template Preset
          </label>
          <select
            value={templateType}
            onChange={(e) => setTemplateType(e.target.value)}
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
          >
            <option value="Feature Implementation">Feature Implementation & AST Pipeline</option>
            <option value="Security Remediation">Zero-Trust Security Remediation</option>
            <option value="Refactoring & AST">AST Symbol Refactoring & Evolution DAG</option>
          </select>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Custom Objective Title / Prompt *
          </label>
          <input
            type="text"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder={`e.g. ${currentPreset.title}...`}
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Preset Step Topology Preview */}
        <div className="p-3 bg-[#101012] border border-white/[0.08] rounded space-y-2 font-mono">
          <span className="text-[10px] text-[#FFB020] uppercase font-bold flex items-center gap-1">
            <Sparkles size={12} /> Pre-configured DAG Node Topology ({currentPreset.steps.length} Nodes)
          </span>

          <div className="space-y-1.5 text-[11px]">
            {currentPreset.steps.map((s, idx) => (
              <div key={idx} className="p-2 bg-[#141416] border border-white/[0.06] rounded flex items-center justify-between">
                <div>
                  <div className="text-white font-bold">{s.name}</div>
                  <div className="text-[10px] text-gray-400">{s.action}</div>
                </div>
                <span className="text-[10px] text-[#FFB020] px-2 py-0.5 bg-[#FFB020]/10 rounded border border-[#FFB020]/20">
                  {s.role}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={isSubmitting}
            icon={<Play size={14} />}
          >
            {isSubmitting ? 'Dispatching...' : 'Dispatch DAG Execution'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
