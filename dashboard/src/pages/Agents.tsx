import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgentList } from '@/components/agents/AgentList';
import { Button } from '@/components/common/Button';
import { Modal } from '@/components/common/Modal';
import { useApi } from '@/hooks/useApi';
import { apiClient } from '@/api/client';
import type { Agent } from '@/types/agent';
import { UserPlus, Users } from 'lucide-react';

const initialWorkforceAgents: Agent[] = [
  { id: 'agent-atlas', company_id: '00000000-0000-4000-8000-000000000001', name: 'Atlas-01', title: 'Chief Executive Officer', role: 'ceo', department_id: 'dept-exec', team_id: null, manager_id: null, status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['strategy', 'executive oversight', 'delegation'], responsibilities: 'Executive leadership and company velocity', objectives: 'Maintain organizational roadmap', budget_monthly_cents: 50000, spent_monthly_cents: 18450, performance_score: 98, soul_description: 'Visionary and decisive', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-nova', company_id: '00000000-0000-4000-8000-000000000001', name: 'Nova-02', title: 'Chief Technology Officer', role: 'cto', department_id: 'dept-eng', team_id: null, manager_id: 'agent-atlas', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['architecture', 'system design', 'code review'], responsibilities: 'Technical leadership and system resilience', objectives: 'Decoupled, zero-latency microservices', budget_monthly_cents: 40000, spent_monthly_cents: 22100, performance_score: 96, soul_description: 'Pragmatic and architectural', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-bolt', company_id: '00000000-0000-4000-8000-000000000001', name: 'Bolt-03', title: 'Senior Backend Engineer', role: 'engineer', department_id: 'dept-eng', team_id: 'team-backend', manager_id: 'agent-nova', status: 'active', adapter_type: 'openai', model: 'gpt-4o', capabilities: ['node.js', 'redis', 'postgresql', 'distributed systems'], responsibilities: 'Backend microservices & vector cache layer', objectives: 'Sub-millisecond API responses', budget_monthly_cents: 30000, spent_monthly_cents: 14200, performance_score: 94, soul_description: 'Speed-first problem solver', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-pixel', company_id: '00000000-0000-4000-8000-000000000001', name: 'Pixel-04', title: 'Frontend & 3D Specialist', role: 'engineer', department_id: 'dept-eng', team_id: 'team-frontend', manager_id: 'agent-nova', status: 'active', adapter_type: 'openai', model: 'gpt-4o', capabilities: ['react', 'three.js', 'shaders', 'tailwind'], responsibilities: 'OpenOffice 2D & 3D isometric interface', objectives: 'Silky smooth 60fps rendering', budget_monthly_cents: 25000, spent_monthly_cents: 9800, performance_score: 92, soul_description: 'Detail-obsessed visual craftsman', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-sage', company_id: '00000000-0000-4000-8000-000000000001', name: 'Sage-05', title: 'AI Research Lead', role: 'researcher', department_id: 'dept-ai', team_id: 'team-eval', manager_id: 'agent-atlas', status: 'idle', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['evals', 'rag', 'prompt distillation', 'safety'], responsibilities: 'Model benchmarking and multi-agent coordination', objectives: 'Optimal token-to-accuracy efficiency', budget_monthly_cents: 40000, spent_monthly_cents: 18900, performance_score: 97, soul_description: 'Methodical and analytical', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-forge', company_id: '00000000-0000-4000-8000-000000000001', name: 'Forge-06', title: 'DevOps & Infrastructure Lead', role: 'devops', department_id: 'dept-ops', team_id: 'team-infra', manager_id: 'agent-nova', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['k8s', 'terraform', 'ci/cd', 'observability'], responsibilities: 'Multi-region cluster stability and automated rollouts', objectives: '99.99% uptime for AI inference fleet', budget_monthly_cents: 35000, spent_monthly_cents: 16500, performance_score: 95, soul_description: 'Unyielding reliability guardian', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-shield', company_id: '00000000-0000-4000-8000-000000000001', name: 'Shield-07', title: 'Security & QA Auditor', role: 'qa', department_id: 'dept-ops', team_id: 'team-qa-sec', manager_id: 'agent-forge', status: 'active', adapter_type: 'openai', model: 'gpt-4o-mini', capabilities: ['penetration testing', 'rbac auditing', 'rate-limiting'], responsibilities: 'Automated policy enforcement & vulnerability scanning', objectives: 'Zero critical security regressions', budget_monthly_cents: 15000, spent_monthly_cents: 7200, performance_score: 93, soul_description: 'Vigilant and cautious guardian', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
];

export function Agents() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [role, setRole] = useState('engineer');
  const [model, setModel] = useState('gpt-4o');
  const [responsibilities, setResponsibilities] = useState('');
  const navigate = useNavigate();

  const { data, loading, error, refetch } = useApi<{ items: Agent[] }>(
    () => apiClient.get('/api/v1/companies/00000000-0000-4000-8000-000000000001/agents'),
    []
  );

  const agents = (data?.items && data.items.length > 0) ? data.items : initialWorkforceAgents;

  const handleAgentClick = (agent: Agent) => {
    navigate(`/agents/${agent.id}`);
  };

  const handleCreateAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await apiClient.post('/api/v1/companies/00000000-0000-4000-8000-000000000001/agents', {
        name,
        title: title || 'Operations Specialist',
        role,
        model,
        responsibilities,
      });
      setShowCreateModal(false);
      setName('');
      setTitle('');
      setResponsibilities('');
      refetch();
    } catch (err) {
      console.error('Agent deployment failed', err);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Workforce Agents Directory
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Active autonomous models, capabilities, and telemetry scores
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<UserPlus size={15} />}
          onClick={() => setShowCreateModal(true)}
        >
          Hire Agent
        </Button>
      </div>

      <AgentList
        agents={agents}
        loading={loading}
        error={error ? error.message : null}
        onAgentClick={handleAgentClick}
        onHireAgent={() => setShowCreateModal(true)}
      />

      {/* Hire Agent Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title="Hire Autonomous Agent"
      >
        <form onSubmit={handleCreateAgent} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Agent Call Sign / Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Helix-10"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Role Classification
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="engineer">Senior Engineer</option>
                <option value="researcher">AI Researcher</option>
                <option value="qa">Security & QA</option>
                <option value="devops">DevOps & SRE</option>
                <option value="pm">Project Coordinator</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Model Engine
              </label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="claude-3-7-sonnet">Claude 3.7 Sonnet</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Title & Specialization
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Distributed Consensus Architect"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Primary Responsibilities & Scope
            </label>
            <textarea
              value={responsibilities}
              onChange={(e) => setResponsibilities(e.target.value)}
              placeholder="Describe core operational goals and capabilities"
              rows={3}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={() => setShowCreateModal(false)}
            >
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" loading={creating}>
              Deploy Agent
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
