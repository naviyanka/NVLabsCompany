import { useState } from 'react';
import {
  X,
  GitMerge,
  CheckCircle2,
  AlertOctagon,
  Bot,
  Sparkles,
  FileCode,
  ArrowRight,
  RefreshCw,
  Clock,
} from 'lucide-react';
import type { GitPullRequest, GitRepoItem } from '@/types/gitRepo';
import { Button } from '@/components/common/Button';
import { PRStatusBadge, PRChecksBadge, PRReviewBadge } from './PRBadges';

interface PRDiffModalProps {
  isOpen: boolean;
  onClose: () => void;
  pr: GitPullRequest | null;
  repo: GitRepoItem | null;
  onMerge: (repoId: string, prId: string) => Promise<void>;
  onClosePR: (repoId: string, prId: string) => Promise<void>;
  onTriggerReview: (repoId: string, prId: string, reviewerAgent?: string) => Promise<void>;
}

export function PRDiffModal({
  isOpen,
  onClose,
  pr,
  repo,
  onMerge,
  onClosePR,
  onTriggerReview,
}: PRDiffModalProps) {
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'diff' | 'reviews' | 'checks'>('diff');

  if (!isOpen || !pr || !repo) return null;

  const handleMergeClick = async () => {
    setIsActionLoading(true);
    try {
      await onMerge(repo.id, pr.id);
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleClosePRClick = async () => {
    setIsActionLoading(true);
    try {
      await onClosePR(repo.id, pr.id);
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleReviewClick = async () => {
    setIsActionLoading(true);
    try {
      await onTriggerReview(repo.id, pr.id, 'Shield-07');
    } finally {
      setIsActionLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-150">
      <div className="bg-[#101012] border border-white/[0.12] rounded-[12px] w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-white/[0.08] bg-[#141417] flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-mono text-[#6B6B6E] bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.06]">
                {repo.name} #{pr.number}
              </span>

              {/* Color-Coded PR Status Badge */}
              <PRStatusBadge status={pr.status} size="sm" />

              {/* Color-Coded CI Checks Badge */}
              <PRChecksBadge checks={pr.checks} size="sm" />

              {/* Review Status Badge */}
              <PRReviewBadge reviewers={pr.reviewers} status={pr.status} size="sm" />

              <span className="text-xs font-mono text-[#A8A8AB] ml-auto sm:ml-0">
                {pr.source_branch} <ArrowRight className="inline w-3 h-3 text-[#6B6B6E]" />{' '}
                {pr.target_branch}
              </span>
            </div>

            <h2 className="text-base sm:text-lg font-medium text-[#F2F1EE] mt-2 font-display">
              {pr.title}
            </h2>

            <div className="flex items-center gap-3 mt-1.5 text-xs font-mono text-[#6B6B6E] flex-wrap">
              <span className="text-[#A8A8AB]">
                Authored by <span className="text-[#FFB020]">{pr.author}</span> ({pr.author_role || 'Agent'})
              </span>
              <span>·</span>
              <span className="text-emerald-400">+{pr.additions}</span>
              <span className="text-rose-400">-{pr.deletions}</span>
              <span>·</span>
              <span>{pr.changed_files_count} files changed</span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-[6px] text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.06] transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center justify-between px-4 sm:px-5 border-b border-white/[0.06] bg-[#0E0E10] text-xs font-mono">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setActiveTab('diff')}
              className={`py-2.5 border-b-2 font-medium transition-colors cursor-pointer ${
                activeTab === 'diff'
                  ? 'border-[#FFB020] text-[#FFB020]'
                  : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
              }`}
            >
              Unified Diff Preview
            </button>
            <button
              onClick={() => setActiveTab('reviews')}
              className={`py-2.5 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                activeTab === 'reviews'
                  ? 'border-[#FFB020] text-[#FFB020]'
                  : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
              }`}
            >
              <span>Agent Reviews</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.06]">
                {pr.reviewers?.length || 0}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('checks')}
              className={`py-2.5 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                activeTab === 'checks'
                  ? 'border-[#FFB020] text-[#FFB020]'
                  : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
              }`}
            >
              <span>AST Checks & Gate</span>
              {pr.checks === 'failed' ? (
                <span className="text-[10px] text-rose-400 font-bold">1 Check Failed</span>
              ) : pr.checks === 'running' ? (
                <span className="text-[10px] text-cyan-300">Running</span>
              ) : (
                <span className="text-[10px] text-emerald-400">100% Pass</span>
              )}
            </button>
          </div>

          <div className="hidden sm:flex items-center gap-2 text-[11px] text-[#38BDF8]">
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI Review Confidence: {pr.ai_review_score}%</span>
          </div>
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4 font-mono text-xs">
          {/* AI Summary Banner */}
          {pr.ai_summary && (
            <div
              className={`p-3 rounded-[8px] flex items-start gap-3 border ${
                pr.checks === 'failed'
                  ? 'bg-rose-500/10 border-rose-500/30'
                  : 'bg-[#38BDF8]/10 border-[#38BDF8]/20'
              }`}
            >
              <Bot
                className={`w-4 h-4 shrink-0 mt-0.5 ${
                  pr.checks === 'failed' ? 'text-rose-400' : 'text-[#38BDF8]'
                }`}
              />
              <div className="space-y-1">
                <div
                  className={`text-[11px] font-semibold uppercase tracking-wider ${
                    pr.checks === 'failed' ? 'text-rose-400' : 'text-[#38BDF8]'
                  }`}
                >
                  Automated AST Code Analysis & Gate Status
                </div>
                <p className="text-xs text-[#E0F2FE] font-sans leading-relaxed">
                  {pr.ai_summary}
                </p>
              </div>
            </div>
          )}

          {/* Diff View */}
          {activeTab === 'diff' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A8A8AB]">
                <span className="flex items-center gap-1.5">
                  <FileCode className="w-3.5 h-3.5 text-[#FFB020]" />
                  <span>Changed Files ({pr.changed_files_count})</span>
                </span>
                <span className="text-[10px] text-[#6B6B6E]">Syntactically parsed AST Diff</span>
              </div>

              <div className="bg-[#0A0A0C] border border-white/[0.08] rounded-[8px] p-3.5 overflow-x-auto text-[11px] leading-relaxed select-text font-mono">
                {pr.diff_preview ? (
                  <pre className="text-[#F2F1EE]">
                    {pr.diff_preview.split('\n').map((line: string, idx: number) => {
                      let color = 'text-[#A8A8AB]';
                      let bg = '';
                      if (line.startsWith('+') && !line.startsWith('+++')) {
                        color = 'text-emerald-400';
                        bg = 'bg-emerald-500/[0.08] block px-1 -mx-1';
                      } else if (line.startsWith('-') && !line.startsWith('---')) {
                        color = 'text-rose-400';
                        bg = 'bg-rose-500/[0.08] block px-1 -mx-1';
                      } else if (line.startsWith('@@')) {
                        color = 'text-[#38BDF8]';
                        bg = 'bg-[#38BDF8]/10 block px-1 -mx-1';
                      } else if (line.startsWith('diff --git')) {
                        color = 'text-[#FFB020] font-semibold';
                      }
                      return (
                        <span key={idx} className={`${color} ${bg}`}>
                          {line}
                          {'\n'}
                        </span>
                      );
                    })}
                  </pre>
                ) : (
                  <div className="text-[#6B6B6E] text-center py-6">
                    No detailed patch preview provided.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Reviews View */}
          {activeTab === 'reviews' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#A8A8AB] uppercase tracking-wider">
                  Automated Agent Reviews & Sign-offs
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleReviewClick}
                  disabled={isActionLoading || pr.status !== 'open'}
                >
                  <Sparkles className="w-3.5 h-3.5 text-[#FFB020] mr-1.5" />
                  Request Shield-07 Audit
                </Button>
              </div>

              {pr.reviewers && pr.reviewers.length > 0 ? (
                <div className="space-y-2.5">
                  {pr.reviewers.map((rev, idx) => {
                    const isApproved = rev.decision === 'approved';
                    const isChangesReq = rev.decision === 'changes_requested';

                    const decisionClasses = isApproved
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : isChangesReq
                      ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                      : 'bg-amber-500/10 text-amber-400 border-amber-500/20';

                    return (
                      <div
                        key={idx}
                        className="p-3 bg-[#141417] border border-white/[0.06] rounded-[8px] space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-[#F2F1EE]">{rev.agent_name}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] border font-mono ${decisionClasses}`}>
                              {rev.decision.replace('_', ' ').toUpperCase()}
                            </span>
                          </div>
                          <span className="text-[10px] text-[#6B6B6E]">{rev.timestamp}</span>
                        </div>
                        <p className="text-xs text-[#A8A8AB] font-sans leading-relaxed">
                          {rev.comment}
                        </p>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-8 text-[#6B6B6E] bg-[#141417]/50 rounded-[8px] border border-white/[0.04] space-y-2">
                  <Clock className="w-6 h-6 mx-auto text-amber-400 opacity-60" />
                  <div className="text-xs text-[#F2F1EE]">Needs Review</div>
                  <div className="text-[11px] text-[#6B6B6E]">
                    No formal agent reviews requested yet. Click &quot;Request Shield-07 Audit&quot; above to trigger review.
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Checks View */}
          {activeTab === 'checks' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#A8A8AB] uppercase tracking-wider">
                  CI/CD Pipeline & Static Analysis Gates
                </span>
                <PRChecksBadge checks={pr.checks} size="sm" />
              </div>

              <div className="space-y-2">
                <div className="p-3 bg-[#141417] border border-white/[0.06] rounded-[8px] flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <div>
                      <div className="text-xs font-medium text-[#F2F1EE]">AST Symbol Dependency Analysis</div>
                      <div className="text-[10px] text-[#6B6B6E]">Zero unresolvable cross-module references</div>
                    </div>
                  </div>
                  <span className="text-emerald-400 text-xs font-mono">100% Passed</span>
                </div>

                <div className="p-3 bg-[#141417] border border-white/[0.06] rounded-[8px] flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <div>
                      <div className="text-xs font-medium text-[#F2F1EE]">Vulnerability & Security Scanner</div>
                      <div className="text-[10px] text-[#6B6B6E]">0 CVEs, zero credential leaks, memory bounded</div>
                    </div>
                  </div>
                  <span className="text-emerald-400 text-xs font-mono">Clean</span>
                </div>

                <div
                  className={`p-3 bg-[#141417] border rounded-[8px] flex items-center justify-between ${
                    pr.checks === 'failed'
                      ? 'border-rose-500/40 bg-rose-500/[0.03]'
                      : 'border-white/[0.06]'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    {pr.checks === 'failed' ? (
                      <AlertOctagon className="w-4 h-4 text-rose-400" />
                    ) : pr.checks === 'running' ? (
                      <RefreshCw className="w-4 h-4 text-cyan-300 animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    )}
                    <div>
                      <div className="text-xs font-medium text-[#F2F1EE]">
                        Automated Unit & Integration Test Matrix
                      </div>
                      <div className="text-[10px] text-[#6B6B6E]">
                        {pr.checks === 'failed'
                          ? '2 test suites failed in sandbox container (WebGPU context binding mismatch)'
                          : pr.checks === 'running'
                          ? 'Executing 18 test suites across node sandboxes...'
                          : '18 test suites passing in sandbox container'}
                      </div>
                    </div>
                  </div>
                  <span
                    className={`text-xs font-mono ${
                      pr.checks === 'failed'
                        ? 'text-rose-400 font-bold'
                        : pr.checks === 'running'
                        ? 'text-cyan-300'
                        : 'text-emerald-400'
                    }`}
                  >
                    {pr.checks === 'failed' ? '16 / 18 (FAILED)' : pr.checks === 'running' ? 'Running...' : '18 / 18'}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-4 border-t border-white/[0.08] bg-[#141417] flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-[#6B6B6E]">Status:</span>
            <PRStatusBadge status={pr.status} size="sm" />
            <PRChecksBadge checks={pr.checks} size="sm" />
          </div>

          <div className="flex items-center gap-2">
            {pr.status === 'open' && (
              <>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleClosePRClick}
                  disabled={isActionLoading}
                >
                  Close PR
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleMergeClick}
                  disabled={isActionLoading || pr.checks === 'failed'}
                  title={pr.checks === 'failed' ? 'Cannot merge: CI checks failed' : 'Merge into base branch'}
                  className={
                    pr.checks === 'failed'
                      ? 'bg-zinc-800 text-zinc-500 border-zinc-700 cursor-not-allowed opacity-50'
                      : 'bg-emerald-600 hover:bg-emerald-500 border-emerald-500 text-white'
                  }
                >
                  <GitMerge className="w-3.5 h-3.5 mr-1.5" />
                  Merge into {pr.target_branch}
                </Button>
              </>
            )}
            <Button variant="secondary" size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
