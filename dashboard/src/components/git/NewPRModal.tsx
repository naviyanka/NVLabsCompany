import React, { useState } from 'react';
import {
  X,
  GitPullRequest,
  Sparkles,
} from 'lucide-react';
import { GitRepoItem } from '@/types/gitRepo';
import { Button } from '@/components/common/Button';

interface NewPRModalProps {
  isOpen: boolean;
  onClose: () => void;
  repo: GitRepoItem | null;
  onSubmitPR: (
    repoId: string,
    data: {
      title: string;
      description: string;
      author: string;
      source_branch: string;
      target_branch: string;
      diff_preview?: string;
    }
  ) => Promise<void>;
}

const AGENT_CANDIDATES = [
  { name: 'Bolt-03', role: 'Senior Backend Engineer', specialization: 'Backend & High-Throughput APIs' },
  { name: 'Pixel-04', role: 'Frontend Engineer', specialization: 'React, Canvas, 3D & UI Accessibility' },
  { name: 'Sage-05', role: 'AI Research Lead', specialization: 'AI Reasoning, RAG & AST Graph Parsers' },
  { name: 'Forge-08', role: 'DevOps / Reliability', specialization: 'CI/CD, Build Systems & Infrastructure' },
  { name: 'Shield-07', role: 'Security QA Lead', specialization: 'Cryptographic Audits & CVE Hardening' },
  { name: 'Nova-02', role: 'Chief Technology Officer', specialization: 'Architecture & System Optimization' },
];

const PRESET_TEMPLATES = [
  {
    label: 'Performance Optimization',
    title: 'perf: optimize semantic memory query caching and adjacency lookups',
    description: 'Implements LRU caching and sparse matrix adjacency structures to reduce lookup latency by 40%.',
    diff: `diff --git a/src/cache/optimizer.ts b/src/cache/optimizer.ts\nnew file mode 100644\n--- /dev/null\n+++ b/src/cache/optimizer.ts\n@@ -0,0 +1,15 @@\n+export class MemoryCacheOptimizer {\n+  private cache = new Map<string, unknown>();\n+  getOrSet(key: string, fn: () => unknown) {\n+    if (this.cache.has(key)) return this.cache.get(key);\n+    const val = fn();\n+    this.cache.set(key, val);\n+    return val;\n+  }\n+}`,
  },
  {
    label: 'Security Hardening',
    title: 'sec: harden webhook signature validation and payload sanitization',
    description: 'Enforces constant-time HMAC comparison and rejects non-whitelisted payload schemas.',
    diff: `diff --git a/src/security/webhook.ts b/src/security/webhook.ts\n--- a/src/security/webhook.ts\n+++ b/src/security/webhook.ts\n@@ -10,4 +10,12 @@ export function verifySignature(raw: string, sig: string): boolean {\n+  const expected = crypto.createHmac('sha256', SECRET).update(raw).digest('hex');\n+  return crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected));\n+}`,
  },
  {
    label: 'Refactor / Feature',
    title: 'feat: add telemetry metrics exporter for agent execution latency',
    description: 'Streams granular CPU, token usage, and step completion metrics to Prometheus format.',
    diff: `diff --git a/src/telemetry/metrics.ts b/src/telemetry/metrics.ts\n--- a/src/telemetry/metrics.ts\n+++ b/src/telemetry/metrics.ts\n@@ -1,3 +1,8 @@\n+export const agentExecutionHistogram = new Histogram({\n+  name: 'agent_step_duration_seconds',\n+  help: 'Duration of individual agent execution steps in seconds',\n+});`,
  },
];

export function NewPRModal({ isOpen, onClose, repo, onSubmitPR }: NewPRModalProps) {
  const [selectedAgent, setSelectedAgent] = useState('Bolt-03');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [sourceBranch, setSourceBranch] = useState('');
  const [targetBranch, setTargetBranch] = useState(repo?.default_branch || 'main');
  const [diffPreview, setDiffPreview] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen || !repo) return null;

  const handleApplyTemplate = (tpl: typeof PRESET_TEMPLATES[0]) => {
    setTitle(tpl.title);
    setDescription(tpl.description);
    setDiffPreview(tpl.diff);
    setSourceBranch(`agent/${selectedAgent.toLowerCase().replace(/[^a-z0-9]/g, '-')}/${tpl.label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setIsSubmitting(true);
    try {
      const branchName = sourceBranch.trim() || `agent/${selectedAgent.toLowerCase().replace(/[^a-z0-9]/g, '-')}/patch-${Date.now().toString(36)}`;
      await onSubmitPR(repo.id, {
        title,
        description,
        author: selectedAgent,
        source_branch: branchName,
        target_branch: targetBranch || repo.default_branch,
        diff_preview: diffPreview,
      });
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-150">
      <div className="bg-[#101012] border border-white/[0.12] rounded-[12px] w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-white/[0.08] bg-[#141417] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-[8px] bg-[#FFB020]/10 border border-[#FFB020]/20 text-[#FFB020]">
              <GitPullRequest className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-medium text-[#F2F1EE] font-display">
                Dispatch Agent Code Patch / PR
              </h2>
              <p className="text-xs font-mono text-[#6B6B6E]">
                Target: <span className="text-[#A8A8AB]">{repo.name}</span>
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
          {/* Quick Presets */}
          <div>
            <label className="block text-[11px] text-[#6B6B6E] uppercase tracking-wider mb-1.5">
              Quick Task Templates:
            </label>
            <div className="flex flex-wrap gap-2">
              {PRESET_TEMPLATES.map((tpl, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => handleApplyTemplate(tpl)}
                  className="px-2.5 py-1 rounded bg-white/[0.04] hover:bg-[#FFB020]/15 text-[#A8A8AB] hover:text-[#FFB020] border border-white/[0.08] text-[11px] transition-colors cursor-pointer"
                >
                  ⚡ {tpl.label}
                </button>
              ))}
            </div>
          </div>

          {/* Author Agent */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1.5">
              Assign Authoring Agent
            </label>
            <select
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] cursor-pointer"
            >
              {AGENT_CANDIDATES.map((agent) => (
                <option key={agent.name} value={agent.name}>
                  {agent.name} — {agent.role} ({agent.specialization})
                </option>
              ))}
            </select>
          </div>

          {/* Branches Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
                Source Patch Branch
              </label>
              <input
                type="text"
                value={sourceBranch}
                onChange={(e) => setSourceBranch(e.target.value)}
                placeholder={`agent/${selectedAgent.toLowerCase()}/patch-01`}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              />
            </div>

            <div>
              <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
                Target Merge Branch
              </label>
              <input
                type="text"
                value={targetBranch}
                onChange={(e) => setTargetBranch(e.target.value)}
                placeholder="main"
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              />
            </div>
          </div>

          {/* PR Title */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
              Pull Request Title <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. feat(memory): add bloom filter to avoid repetitive graph lookups"
              required
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
              Objective & Implementation Summary
            </label>
            <textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what the agent implemented, unit test coverage, and benchmark gains..."
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] leading-relaxed"
            />
          </div>

          {/* Optional Code Diff Preview */}
          <div>
            <label className="block text-[11px] text-[#A8A8AB] uppercase tracking-wider mb-1">
              Syntactic Patch / Diff Preview (Optional)
            </label>
            <textarea
              rows={4}
              value={diffPreview}
              onChange={(e) => setDiffPreview(e.target.value)}
              placeholder="diff --git a/src/file.ts b/src/file.ts..."
              className="w-full px-3 py-2 bg-[#0A0A0C] border border-white/[0.12] rounded-[6px] text-[#F2F1EE] font-mono text-[11px] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="submit"
              disabled={isSubmitting || !title.trim()}
            >
              <Sparkles className="w-3.5 h-3.5 mr-1.5" />
              {isSubmitting ? 'Dispatching...' : 'Dispatch Agent PR'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
