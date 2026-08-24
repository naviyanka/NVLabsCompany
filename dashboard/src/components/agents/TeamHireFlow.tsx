/**
 * TeamHireFlow — Multi-agent batch hiring interface with pre-built team template presets.
 * Users can start from a template or build a custom team from scratch.
 */

import { useState, useEffect } from 'react';
import { Button } from '@/components/common/Button';
import {
  hireTeam,
  listTeamTemplates,
  type AgentArchetype,
  type AgentProvider,
  type TeamAgentSpec,
  type TeamTemplate,
} from '@/api/agents';
import {
  Plus,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  Rocket,
  Users,
  LayoutTemplate,
  Pencil,
} from 'lucide-react';

interface TeamHireFlowProps {
  archetypes: AgentArchetype[];
  providers: AgentProvider[];
  onSuccess: () => void;
  onCancel: () => void;
}

interface TeamMember {
  id: string;
  archetype: string;
  name: string;
  model: string;
  provider: string;
}

// Fallback templates for when API is unavailable
const FALLBACK_TEMPLATES: TeamTemplate[] = [
  { id: 'startup-mvp', name: 'Startup MVP Squad', description: 'Ship a product from zero to production.', icon: '🚀', tags: ['full-stack', 'startup'], agent_count: 5, agents: [
    { archetype: 'Software Architect', suggested_name: 'Arch-01', default_provider: 'claude', default_model: '', reports_to_index: -1, title_override: 'Lead Architect' },
    { archetype: 'Backend Engineer', suggested_name: 'Bolt-02', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Frontend Engineer', suggested_name: 'Pixel-03', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'QA Engineer', suggested_name: 'Shield-04', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'DevOps Engineer', suggested_name: 'Forge-05', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
  ]},
  { id: 'core-product', name: 'Core Product Team', description: 'Feature development with product thinking and design.', icon: '📦', tags: ['product', 'features'], agent_count: 5, agents: [
    { archetype: 'Product Manager', suggested_name: 'Compass-01', default_provider: 'claude', default_model: '', reports_to_index: -1, title_override: 'Product Lead' },
    { archetype: 'Designer', suggested_name: 'Prism-02', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Frontend Engineer', suggested_name: 'Pixel-03', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Backend Engineer', suggested_name: 'Bolt-04', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'QA Engineer', suggested_name: 'Shield-05', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
  ]},
  { id: 'platform-infra', name: 'Platform & Infrastructure', description: 'Reliability, security, and infrastructure.', icon: '🏗️', tags: ['infra', 'platform'], agent_count: 4, agents: [
    { archetype: 'DevOps Engineer', suggested_name: 'Forge-01', default_provider: 'claude', default_model: '', reports_to_index: -1, title_override: 'Platform Lead' },
    { archetype: 'Site Reliability Engineer', suggested_name: 'Uptime-02', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Database Administrator', suggested_name: 'Vault-03', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Security Engineer', suggested_name: 'Sentinel-04', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
  ]},
  { id: 'ml-data', name: 'ML & Data Team', description: 'Model development, data pipelines, and research.', icon: '🧠', tags: ['ml', 'data'], agent_count: 3, agents: [
    { archetype: 'ML Engineer', suggested_name: 'Sage-01', default_provider: 'claude', default_model: '', reports_to_index: -1, title_override: 'ML Lead' },
    { archetype: 'Data Engineer', suggested_name: 'Flow-02', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Researcher', suggested_name: 'Lens-03', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
  ]},
  { id: 'leadership', name: 'Leadership & Coordination', description: 'Strategy, architecture, and project management.', icon: '👔', tags: ['leadership', 'management'], agent_count: 4, agents: [
    { archetype: 'Team Lead', suggested_name: 'Atlas-01', default_provider: 'claude', default_model: '', reports_to_index: -1, title_override: 'Engineering Director' },
    { archetype: 'Software Architect', suggested_name: 'Blueprint-02', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Project Manager', suggested_name: 'Compass-03', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'Scrum Master', suggested_name: 'Sprint-04', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
  ]},
  { id: 'full-company', name: 'Full Company (8 Agents)', description: 'Complete autonomous organization with all roles.', icon: '🏢', tags: ['full', 'company'], agent_count: 8, agents: [
    { archetype: 'Team Lead', suggested_name: 'Atlas', default_provider: 'claude', default_model: '', reports_to_index: -1, title_override: 'Chief Executive Officer' },
    { archetype: 'Software Architect', suggested_name: 'Nova', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: 'Chief Technology Officer' },
    { archetype: 'Backend Engineer', suggested_name: 'Bolt', default_provider: 'claude', default_model: '', reports_to_index: 1, title_override: '' },
    { archetype: 'Frontend Engineer', suggested_name: 'Pixel', default_provider: 'claude', default_model: '', reports_to_index: 1, title_override: '' },
    { archetype: 'Researcher', suggested_name: 'Sage', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: 'AI Research Lead' },
    { archetype: 'Project Manager', suggested_name: 'Compass', default_provider: 'claude', default_model: '', reports_to_index: 0, title_override: '' },
    { archetype: 'QA Engineer', suggested_name: 'Shield', default_provider: 'claude', default_model: '', reports_to_index: 1, title_override: '' },
    { archetype: 'DevOps Engineer', suggested_name: 'Forge', default_provider: 'claude', default_model: '', reports_to_index: 1, title_override: '' },
  ]},
];

export function TeamHireFlow({ archetypes, providers, onSuccess, onCancel }: TeamHireFlowProps) {
  const [teamTemplates, setTeamTemplates] = useState<TeamTemplate[]>(FALLBACK_TEMPLATES);
  const [teamName, setTeamName] = useState('');
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ agents_created: number; agents: any[] } | null>(null);

  // Load team templates from API
  useEffect(() => {
    listTeamTemplates()
      .then((templates) => {
        if (Array.isArray(templates) && templates.length > 0) {
          setTeamTemplates(templates);
        }
      })
      .catch(() => { /* keep fallbacks */ });
  }, []);

  const applyTemplate = (template: TeamTemplate) => {
    setSelectedTemplate(template.id);
    setTeamName(template.name);
    setMembers(
      template.agents.map((slot, idx) => ({
        id: `tmpl-${idx}-${Date.now()}`,
        archetype: slot.archetype,
        name: slot.suggested_name,
        model: slot.default_model,
        provider: slot.default_provider || 'claude',
      }))
    );
  };

  const clearTemplate = () => {
    setSelectedTemplate(null);
    setTeamName('');
    setMembers([]);
  };

  const addMember = (archetypeName?: string) => {
    const id = `member-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const archetype = archetypeName
      ? archetypes.find((a) => a.name === archetypeName)
      : undefined;

    setMembers((prev) => [
      ...prev,
      {
        id,
        archetype: archetype?.name || '',
        name: archetype ? `${archetype.name.split(' ')[0]}-${String(prev.length + 1).padStart(2, '0')}` : '',
        model: '',
        provider: 'claude',
      },
    ]);
    setSelectedTemplate(null); // Custom modification = no longer a pure template
  };

  const removeMember = (id: string) => {
    setMembers((prev) => prev.filter((m) => m.id !== id));
    setSelectedTemplate(null);
  };

  const updateMember = (id: string, field: keyof TeamMember, value: string) => {
    setMembers((prev) =>
      prev.map((m) => (m.id === id ? { ...m, [field]: value } : m))
    );
  };

  const handleArchetypeChange = (id: string, archetypeName: string) => {
    const archetype = archetypes.find((a) => a.name === archetypeName);
    setMembers((prev) =>
      prev.map((m) => {
        if (m.id !== id) return m;
        return {
          ...m,
          archetype: archetypeName,
          name: m.name || (archetype ? `${archetype.name.split(' ')[0]}-${String(prev.indexOf(m) + 1).padStart(2, '0')}` : ''),
        };
      })
    );
  };

  const setAllProviders = (providerId: string) => {
    setMembers((prev) => prev.map((m) => ({ ...m, provider: providerId })));
  };

  const handleDeploy = async () => {
    if (!teamName.trim()) {
      setError('Team name is required');
      return;
    }
    if (members.length === 0) {
      setError('Add at least one agent to the team');
      return;
    }
    if (members.some((m) => !m.name.trim())) {
      setError('All agents must have a name');
      return;
    }

    setDeploying(true);
    setError(null);

    try {
      const agents: TeamAgentSpec[] = members.map((m) => ({
        name: m.name,
        archetype: m.archetype || undefined,
        model: m.model || undefined,
        adapter_type: m.provider || 'langchain',
      }));

      const response = await hireTeam({
        team_name: teamName,
        agents,
      });

      setResult(response);
    } catch (err: any) {
      setError(err?.message || 'Team deployment failed');
    } finally {
      setDeploying(false);
    }
  };

  // Success state
  if (result) {
    return (
      <div className="space-y-4 text-center py-4">
        <div className="w-12 h-12 mx-auto rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
          <CheckCircle2 size={24} className="text-emerald-400" />
        </div>
        <div>
          <h3 className="text-sm font-medium text-[#F2F1EE]">Team Deployed Successfully</h3>
          <p className="text-xs text-[#6B6B6E] font-mono mt-1">
            {result.agents_created} agent{result.agents_created !== 1 ? 's' : ''} created in team "{teamName}"
          </p>
        </div>

        <div className="space-y-1.5 max-h-40 overflow-y-auto">
          {result.agents.map((agent: any) => (
            <div
              key={agent.id}
              className="flex items-center justify-between p-2 bg-[#141416] border border-white/[0.06] rounded-[6px] text-xs font-mono"
            >
              <span className="text-[#F2F1EE]">{agent.name}</span>
              <span className="text-[#6B6B6E]">{agent.role}</span>
            </div>
          ))}
        </div>

        <Button variant="primary" size="sm" onClick={onSuccess}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Team Template Presets */}
      {members.length === 0 && (
        <div className="space-y-2.5">
          <div className="flex items-center gap-2">
            <LayoutTemplate size={13} className="text-[#FFB020]" />
            <span className="text-xs font-mono text-[#A8A8AB] uppercase">Start from a template</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {teamTemplates.map((tmpl) => (
              <button
                key={tmpl.id}
                type="button"
                onClick={() => applyTemplate(tmpl)}
                className="p-3 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/40 rounded-[8px] text-left transition-all group cursor-pointer"
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-base">{tmpl.icon}</span>
                  <span className="text-[11px] font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors leading-tight">
                    {tmpl.name}
                  </span>
                </div>
                <p className="text-[9px] text-[#6B6B6E] font-mono leading-relaxed line-clamp-2">
                  {tmpl.description}
                </p>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-[9px] font-mono text-[#6B6B6E]">
                    {tmpl.agent_count} agents
                  </span>
                  <span className="text-[9px] font-mono text-[#FFB020] opacity-0 group-hover:opacity-100 transition-opacity">
                    Use →
                  </span>
                </div>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3 pt-2">
            <div className="flex-1 h-px bg-white/[0.06]" />
            <span className="text-[10px] font-mono text-[#6B6B6E]">or build from scratch</span>
            <div className="flex-1 h-px bg-white/[0.06]" />
          </div>
        </div>
      )}

      {/* Template Applied Banner */}
      {selectedTemplate && members.length > 0 && (
        <div className="flex items-center justify-between p-2.5 bg-[#FFB020]/5 border border-[#FFB020]/20 rounded-[6px]">
          <div className="flex items-center gap-2">
            <LayoutTemplate size={13} className="text-[#FFB020]" />
            <span className="text-[11px] font-mono text-[#FFB020]">
              Template: {teamTemplates.find((t) => t.id === selectedTemplate)?.name}
            </span>
          </div>
          <button
            type="button"
            onClick={clearTemplate}
            className="text-[9px] font-mono text-[#6B6B6E] hover:text-red-400 cursor-pointer flex items-center gap-1"
          >
            <Trash2 size={10} />
            Clear
          </button>
        </div>
      )}

      {error && (
        <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-[6px] text-xs text-red-400 font-mono flex items-center gap-2">
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Team Name */}
      <div>
        <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
          Team / Squad Name
        </label>
        <input
          type="text"
          value={teamName}
          onChange={(e) => setTeamName(e.target.value)}
          placeholder="e.g. Backend Squad, Security Team, Core Platform"
          className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
        />
      </div>

      {/* Bulk Provider Override */}
      {members.length > 1 && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-[#6B6B6E]">Set all providers to:</span>
          <div className="flex gap-1">
            {(providers.length > 0 ? providers.filter((p) => p.installed) : [{ id: 'claude', label: 'Claude' }]).map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setAllProviders(p.id)}
                className="px-2 py-0.5 bg-[#101012] border border-white/[0.08] hover:border-[#FFB020]/30 rounded text-[9px] font-mono text-[#A8A8AB] hover:text-[#FFB020] transition-colors cursor-pointer"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Team Members List */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs font-mono text-[#A8A8AB] uppercase flex items-center gap-1.5">
            <Users size={12} />
            Team Members ({members.length})
          </label>
          {members.length > 0 && (
            <button
              type="button"
              onClick={() => addMember()}
              className="text-[10px] font-mono text-[#FFB020] hover:underline cursor-pointer flex items-center gap-1"
            >
              <Plus size={10} />
              Add more
            </button>
          )}
        </div>

        {members.length === 0 ? (
          <div className="p-4 border border-dashed border-white/[0.12] rounded-[8px] text-center">
            <Pencil className="w-5 h-5 mx-auto text-gray-500 mb-1.5" />
            <p className="text-xs font-mono text-[#6B6B6E]">Start from a template above or add agents manually</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[260px] overflow-y-auto pr-1">
            {members.map((member, idx) => (
              <div
                key={member.id}
                className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-[#6B6B6E] uppercase">
                    Agent #{idx + 1}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeMember(member.id)}
                    className="p-1 text-[#6B6B6E] hover:text-red-400 transition-colors cursor-pointer"
                    title="Remove agent"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {/* Archetype Selection */}
                  <div>
                    <select
                      value={member.archetype}
                      onChange={(e) => handleArchetypeChange(member.id, e.target.value)}
                      className="w-full px-2 py-1.5 bg-[#101012] border border-white/[0.08] rounded-[4px] text-[11px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                    >
                      <option value="">Select archetype...</option>
                      {archetypes.map((a) => (
                        <option key={a.role} value={a.name}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Agent Name */}
                  <div>
                    <input
                      type="text"
                      value={member.name}
                      onChange={(e) => updateMember(member.id, 'name', e.target.value)}
                      placeholder="Agent name"
                      className="w-full px-2 py-1.5 bg-[#101012] border border-white/[0.08] rounded-[4px] text-[11px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {/* Provider */}
                  <div>
                    <select
                      value={member.provider}
                      onChange={(e) => updateMember(member.id, 'provider', e.target.value)}
                      className="w-full px-2 py-1.5 bg-[#101012] border border-white/[0.08] rounded-[4px] text-[11px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                    >
                      {providers.length > 0 ? (
                        providers.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.installed ? '● ' : '○ '}{p.label}
                          </option>
                        ))
                      ) : (
                        <>
                          <option value="claude">Claude Code</option>
                          <option value="codex">Codex</option>
                          <option value="kiro-cli">Kiro CLI</option>
                          <option value="antigravity">Antigravity</option>
                          <option value="copilot">Copilot</option>
                        </>
                      )}
                    </select>
                  </div>

                  {/* Model */}
                  <div>
                    <input
                      type="text"
                      value={member.model}
                      onChange={(e) => updateMember(member.id, 'model', e.target.value)}
                      placeholder="Provider default"
                      className="w-full px-2 py-1.5 bg-[#101012] border border-white/[0.08] rounded-[4px] text-[11px] text-[#F2F1EE] placeholder-[#4B4B4E] focus:outline-none focus:border-[#FFB020]"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Add Agent Button (when there are already members) */}
        {members.length > 0 && (
          <button
            type="button"
            onClick={() => addMember()}
            className="w-full p-2 border border-dashed border-white/[0.12] hover:border-[#FFB020]/40 rounded-[6px] text-xs font-mono text-[#6B6B6E] hover:text-[#FFB020] flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
          >
            <Plus size={13} />
            Add Agent
          </button>
        )}
      </div>

      {/* Deploy Actions */}
      <div className="flex items-center justify-between pt-3 border-t border-white/[0.08]">
        <span className="text-[10px] font-mono text-[#6B6B6E]">
          {members.length} agent{members.length !== 1 ? 's' : ''} will be deployed
        </span>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleDeploy}
            loading={deploying}
            icon={<Rocket size={13} />}
            disabled={members.length === 0}
          >
            Deploy Team
          </Button>
        </div>
      </div>
    </div>
  );
}
