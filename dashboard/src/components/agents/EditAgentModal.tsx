/**
 * Edit Agent Modal — Edit an existing agent's configuration, personality traits,
 * capabilities, responsibilities, objectives, and soul description.
 */

import { updateAgent } from '@/api/agents';
import { getRolePreset } from '@/components/agents/rolePresets';
import { Button } from '@/components/common/Button';
import { Modal } from '@/components/common/Modal';
import type { Agent } from '@/types/agent';
import { Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';

interface EditAgentModalProps {
  agent: Agent;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updatedAgent: Agent) => void;
}

export function EditAgentModal({ agent, isOpen, onClose, onSuccess }: EditAgentModalProps) {
  const [name, setName] = useState(agent.name);
  const [title, setTitle] = useState(agent.title || '');
  const [role, setRole] = useState(agent.role || 'engineer');
  const [provider, setProvider] = useState(agent.adapter_type || 'openai');
  const [model, setModel] = useState(agent.model || '');
  const [capabilities, setCapabilities] = useState((agent.capabilities || []).join(', '));
  const [responsibilities, setResponsibilities] = useState(agent.responsibilities || '');
  const [objectives, setObjectives] = useState(agent.objectives || '');
  const [soulDescription, setSoulDescription] = useState(agent.soul_description || '');
  const [budgetCents, setBudgetCents] = useState(agent.budget_monthly_cents || 0);

  // Persona detail states parsed from soul_description if present
  const [personalityTraits, setPersonalityTraits] = useState('');
  const [communicationStyle, setCommunicationStyle] = useState('');
  const [agentValues, setAgentValues] = useState('');
  const [agentConstraints, setAgentConstraints] = useState('');
  const [tone, setTone] = useState('professional');

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Parse existing structured soul description when modal opens
  useEffect(() => {
    if (agent && isOpen) {
      setName(agent.name);
      setTitle(agent.title || '');
      setRole(agent.role || 'engineer');
      setProvider(agent.adapter_type || 'openai');
      setModel(agent.model || '');
      setCapabilities((agent.capabilities || []).join(', '));
      setResponsibilities(agent.responsibilities || '');
      setObjectives(agent.objectives || '');
      setSoulDescription(agent.soul_description || '');
      setBudgetCents(agent.budget_monthly_cents || 0);

      // Extract structured fields from soul_description if available
      const desc = agent.soul_description || '';
      let parsedTraits = '';
      let parsedComm = '';
      let parsedValues = '';
      let parsedConstraints = '';
      let parsedTone = 'professional';

      if (desc.includes('Personality:')) {
        for (const line of desc.split('\n\n')) {
          if (line.startsWith('Personality:')) parsedTraits = line.replace('Personality:', '').trim();
          else if (line.startsWith('Communication:')) parsedComm = line.replace('Communication:', '').trim();
          else if (line.startsWith('Values:')) parsedValues = line.replace('Values:', '').trim();
          else if (line.startsWith('Constraints:')) parsedConstraints = line.replace('Constraints:', '').trim();
          else if (line.startsWith('Tone:')) parsedTone = line.replace('Tone:', '').trim();
        }
      }

      setPersonalityTraits(parsedTraits);
      setCommunicationStyle(parsedComm);
      setAgentValues(parsedValues);
      setAgentConstraints(parsedConstraints);
      setTone(parsedTone);
    }
  }, [agent, isOpen]);

  // Function to re-fill preset based on selected role
  const handleRefillPreset = () => {
    const preset = getRolePreset(role);
    if (!title) setTitle(preset.title);
    setCapabilities(preset.capabilities);
    setResponsibilities(preset.responsibilities);
    setObjectives(preset.objectives);
    setPersonalityTraits(preset.personalityTraits);
    setCommunicationStyle(preset.communicationStyle);
    setAgentValues(preset.agentValues);
    setAgentConstraints(preset.agentConstraints);
    setTone(preset.tone);
    setSoulDescription(preset.soulDescription);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      // Re-build structured soul description
      const soulParts: string[] = [];
      if (soulDescription) soulParts.push(soulDescription);
      if (personalityTraits) soulParts.push(`Personality: ${personalityTraits}`);
      if (communicationStyle) soulParts.push(`Communication: ${communicationStyle}`);
      if (agentValues) soulParts.push(`Values: ${agentValues}`);
      if (agentConstraints) soulParts.push(`Constraints:\n${agentConstraints}`);
      if (tone && tone !== 'professional') soulParts.push(`Tone: ${tone}`);
      const fullSoulDescription = soulParts.join('\n\n') || undefined;

      const updated = await updateAgent(agent.id, {
        name,
        title: title || undefined,
        role: role || undefined,
        adapter_type: provider || undefined,
        model: model || undefined,
        capabilities: capabilities ? capabilities.split(',').map((c: string) => c.trim()).filter(Boolean) : [],
        responsibilities: responsibilities || undefined,
        objectives: objectives || undefined,
        soul_description: fullSoulDescription,
        budget_monthly_cents: budgetCents,
      });

      onSuccess(updated);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to update agent profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Edit Agent Configuration — ${agent.name}`} size="md">
      <form onSubmit={handleSave} className="space-y-4">
        {error && (
          <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-[6px] text-xs text-red-400 font-mono">
            {error}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Agent Call Sign / Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Title / Specialization
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-mono text-[#A8A8AB] uppercase">
                Role Classification
              </label>
              <button
                type="button"
                onClick={handleRefillPreset}
                className="text-[9px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
              >
                <Sparkles size={10} />
                Refill Presets
              </button>
            </div>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="software-architect">Software Architect</option>
              <option value="backend-engineer">Backend Engineer</option>
              <option value="frontend-engineer">Frontend Engineer</option>
              <option value="qa-engineer">QA Engineer</option>
              <option value="devops-engineer">DevOps Engineer</option>
              <option value="security-engineer">Security Engineer</option>
              <option value="data-engineer">Data Engineer</option>
              <option value="ml-engineer">ML Engineer</option>
              <option value="product-manager">Product Manager</option>
              <option value="tech-writer">Technical Writer</option>
              <option value="designer">Designer</option>
              <option value="researcher">Researcher</option>
              <option value="project-manager">Project Manager</option>
              <option value="scrum-master">Scrum Master</option>
              <option value="site-reliability-engineer">Site Reliability Engineer</option>
              <option value="database-admin">Database Administrator</option>
              <option value="mobile-developer">Mobile Developer</option>
              <option value="performance-engineer">Performance Engineer</option>
              <option value="accessibility-specialist">Accessibility Specialist</option>
              <option value="team-lead">Team Lead</option>
              <option value="hr-manager">HR Manager</option>
              <option value="ceo">CEO</option>
              <option value="hermes-agent">Hermes Agent</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Provider Backend
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="hermes">Hermes 3 (local)</option>
              <option value="hermes-cli">Hermes Agent CLI</option>
              <option value="claude">Claude Code</option>
              <option value="codex">Codex</option>
              <option value="antigravity">Antigravity</option>
              <option value="kiro-cli">Kiro CLI</option>
              <option value="aider">Aider</option>
              <option value="opencode">OpenCode</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              LLM Model Override
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. gpt-4o or hermes3:8b"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Monthly Budget (cents)
            </label>
            <input
              type="number"
              value={budgetCents}
              onChange={(e) => setBudgetCents(Number(e.target.value))}
              placeholder="e.g. 30000 ($300)"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
            Capabilities (comma-separated)
          </label>
          <input
            type="text"
            value={capabilities}
            onChange={(e) => setCapabilities(e.target.value)}
            placeholder="e.g. system-design, api-development"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        <div>
          <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
            Primary Responsibilities
          </label>
          <textarea
            value={responsibilities}
            onChange={(e) => setResponsibilities(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        <div>
          <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
            Strategic Objectives
          </label>
          <input
            type="text"
            value={objectives}
            onChange={(e) => setObjectives(e.target.value)}
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Personality & Persona Section */}
        <div className="p-3 bg-[#101012] border border-white/[0.08] rounded-[8px] space-y-3">
          <span className="text-xs font-mono font-medium uppercase text-[#FFB020] block">
            Personality & Persona Traits
          </span>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Personality Traits (comma-separated)
            </label>
            <input
              type="text"
              value={personalityTraits}
              onChange={(e) => setPersonalityTraits(e.target.value)}
              placeholder="e.g. detail-oriented, methodical, pragmatic, collaborative"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Communication Style
              </label>
              <input
                type="text"
                value={communicationStyle}
                onChange={(e) => setCommunicationStyle(e.target.value)}
                placeholder="e.g. concise, code-first, structured"
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Tone
              </label>
              <select
                value={tone}
                onChange={(e) => setTone(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="professional">Professional</option>
                <option value="analytical">Analytical</option>
                <option value="direct">Direct</option>
                <option value="collaborative">Collaborative</option>
                <option value="creative">Creative</option>
                <option value="supportive">Supportive</option>
                <option value="methodical">Methodical</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Core Values
            </label>
            <input
              type="text"
              value={agentValues}
              onChange={(e) => setAgentValues(e.target.value)}
              placeholder="e.g. correctness, simplicity, maintainability"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Operating Constraints (one per line)
            </label>
            <textarea
              value={agentConstraints}
              onChange={(e) => setAgentConstraints(e.target.value)}
              rows={2}
              placeholder="e.g. must write unit tests for all new code"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Soul Background Descriptor
            </label>
            <textarea
              value={soulDescription}
              onChange={(e) => setSoulDescription(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" loading={saving}>
            Save Changes
          </Button>
        </div>
      </form>
    </Modal>
  );
}
