import React, { useState } from 'react';
import {
  X,
  FolderGit2,
  Check,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { Button } from '@/components/common/Button';

interface NewRepoModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmitRepo: (data: {
    name: string;
    description: string;
    provider: 'github' | 'gitlab' | 'internal';
    language: string;
    default_branch: string;
    visibility: 'public' | 'private' | 'internal';
    assigned_agents: string[];
    auto_review_enabled: boolean;
  }) => Promise<void>;
}

const LANGUAGES = ['TypeScript', 'Rust', 'Go', 'Python', 'HCL', 'Solidity', 'C++'];
const AVAILABLE_AGENTS = ['Atlas-01', 'Nova-02', 'Bolt-03', 'Pixel-04', 'Sage-05', 'Forge-08', 'Shield-07'];

export function NewRepoModal({ isOpen, onClose, onSubmitRepo }: NewRepoModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [provider, setProvider] = useState<'github' | 'gitlab' | 'internal'>('github');
  const [language, setLanguage] = useState('TypeScript');
  const [defaultBranch, setDefaultBranch] = useState('main');
  const [visibility] = useState<'public' | 'private' | 'internal'>('private');
  const [selectedAgents, setSelectedAgents] = useState<string[]>(['Nova-02', 'Bolt-03']);
  const [autoReview, setAutoReview] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const toggleAgent = (agent: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agent) ? prev.filter((a) => a !== agent) : [...prev, agent]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    try {
      await onSubmitRepo({
        name: name.trim(),
        description: description.trim(),
        provider,
        language,
        default_branch: defaultBranch.trim() || 'main',
        visibility,
        assigned_agents: selectedAgents,
        auto_review_enabled: autoReview,
      });
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-150">
      <div className="bg-[#101012] border border-white/[0.12] rounded-[12px] w-full max-w-xl max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-white/[0.08] bg-[#141417] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-[8px] bg-[#38BDF8]/10 border border-[#38BDF8]/20 text-[#38BDF8]">
              <FolderGit2 className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-medium text-[#F2F1EE] font-display">
                Mount Git Repository
              </h2>
              <p className="text-xs font-mono text-[#6B6B6E]">
                Connect codebase to AST indexer and agent review bots
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-[6px] text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.06] transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4 text-xs font-mono">
          {/* Provider Selection */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1.5">
              Repository Host Provider
            </label>
            <div className="grid grid-cols-3 gap-2">
              {(['github', 'gitlab', 'internal'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setProvider(p)}
                  className={`p-2 rounded-[6px] border text-center capitalize transition-all cursor-pointer ${
                    provider === p
                      ? 'bg-[#FFB020]/15 border-[#FFB020] text-[#FFB020] font-medium'
                      : 'bg-[#141416] border-white/[0.08] text-[#A8A8AB] hover:border-white/[0.2]'
                  }`}
                >
                  {p === 'internal' ? 'NVLabs Internal' : p}
                </button>
              ))}
            </div>
          </div>

          {/* Repo Name */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
              Repository Path (Organization/Repo) <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. NVLabsCompany/telemetry-service"
              required
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
              Description & Purpose
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Distributed metric collection daemon with gRPC streaming"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          {/* Language & Default Branch */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
                Primary Language
              </label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] cursor-pointer"
              >
                {LANGUAGES.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
                Default Branch
              </label>
              <input
                type="text"
                value={defaultBranch}
                onChange={(e) => setDefaultBranch(e.target.value)}
                placeholder="main"
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              />
            </div>
          </div>

          {/* Assigned Agents */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1.5">
              Assigned Agent Maintainers
            </label>
            <div className="flex flex-wrap gap-1.5">
              {AVAILABLE_AGENTS.map((agent) => {
                const isSelected = selectedAgents.includes(agent);
                return (
                  <button
                    key={agent}
                    type="button"
                    onClick={() => toggleAgent(agent)}
                    className={`px-2.5 py-1 rounded-[6px] text-[11px] border flex items-center gap-1.5 transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-[#38BDF8]/15 border-[#38BDF8]/40 text-[#38BDF8]'
                        : 'bg-white/[0.04] border-white/[0.08] text-[#6B6B6E] hover:text-[#A8A8AB]'
                    }`}
                  >
                    {isSelected && <Check className="w-3 h-3" />}
                    {agent}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Automated AI Review Toggle */}
          <div className="p-3 rounded-[8px] bg-white/[0.02] border border-white/[0.08] flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <ShieldCheck className="w-4 h-4 text-[#22C55E]" />
              <div>
                <div className="text-xs text-[#F2F1EE] font-medium">Automated AST AI Review Gate</div>
                <div className="text-[10px] text-[#6B6B6E]">
                  Run security and architectural audits automatically on incoming PRs
                </div>
              </div>
            </div>
            <input
              type="checkbox"
              checked={autoReview}
              onChange={(e) => setAutoReview(e.target.checked)}
              className="accent-[#FFB020] w-4 h-4 cursor-pointer"
            />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" disabled={isSubmitting || !name.trim()}>
              <Zap className="w-3.5 h-3.5 mr-1.5" />
              {isSubmitting ? 'Mounting...' : 'Mount & Index Repository'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
