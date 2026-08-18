import { useState } from 'react';
import type { AgentCreateRequest } from '@/types/agent';
import { Button } from '@/components/common/Button';

export interface AgentCreateProps {
  onSubmit: (data: AgentCreateRequest) => void;
  onCancel: () => void;
  loading?: boolean;
}

export function AgentCreate({ onSubmit, onCancel, loading = false }: AgentCreateProps) {
  const [formData, setFormData] = useState<AgentCreateRequest>({
    name: '',
    title: '',
    role: '',
    adapter_type: 'openai',
    model: 'gpt-4',
    capabilities: [],
    responsibilities: '',
    objectives: '',
    budget_monthly_cents: 10000,
    soul_description: '',
  });

  const [capabilitiesInput, setCapabilitiesInput] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const capabilities = capabilitiesInput
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean);
    onSubmit({ ...formData, capabilities });
  };

  const updateField = <K extends keyof AgentCreateRequest>(
    field: K,
    value: AgentCreateRequest[K]
  ) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
        <input
          type="text"
          required
          value={formData.name}
          onChange={(e) => updateField('name', e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          placeholder="e.g., Alex the Architect"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
        <input
          type="text"
          required
          value={formData.title}
          onChange={(e) => updateField('title', e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          placeholder="e.g., Senior Software Architect"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
        <input
          type="text"
          required
          value={formData.role}
          onChange={(e) => updateField('role', e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          placeholder="e.g., architect, developer, manager"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Adapter Type</label>
          <select
            value={formData.adapter_type}
            onChange={(e) => updateField('adapter_type', e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="local">Local</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
          <input
            type="text"
            required
            value={formData.model}
            onChange={(e) => updateField('model', e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            placeholder="e.g., gpt-4, claude-3-opus"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Capabilities (comma-separated)
        </label>
        <input
          type="text"
          value={capabilitiesInput}
          onChange={(e) => setCapabilitiesInput(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          placeholder="e.g., code-review, architecture, testing"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Responsibilities</label>
        <textarea
          value={formData.responsibilities}
          onChange={(e) => updateField('responsibilities', e.target.value)}
          rows={2}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          placeholder="Describe this agent's key responsibilities..."
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Objectives</label>
        <textarea
          value={formData.objectives}
          onChange={(e) => updateField('objectives', e.target.value)}
          rows={2}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          placeholder="What should this agent accomplish?"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Monthly Budget (cents)</label>
        <input
          type="number"
          value={formData.budget_monthly_cents}
          onChange={(e) => updateField('budget_monthly_cents', parseInt(e.target.value, 10) || 0)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          min={0}
        />
      </div>

      <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
        <Button variant="secondary" type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" loading={loading}>
          Hire Agent
        </Button>
      </div>
    </form>
  );
}
