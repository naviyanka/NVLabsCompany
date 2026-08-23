import { useState } from 'react';
import {
  X,
  GitBranch,
  GitCommit,
  GitPullRequest,
  RefreshCw,
  ShieldCheck,
  Cpu,
  Plus,
  Users,
  Sparkles,
  ArrowRight,
  GitMerge,
  Copy,
  Check,
  ExternalLink,
  Settings,
  Trash2,
} from 'lucide-react';
import type { GitRepoItem, GitPullRequest as IGitPullRequest } from '@/types/gitRepo';
import { getLanguageColor } from './gitUtils';
import { Button } from '@/components/common/Button';
import { PRStatusBadge, PRChecksBadge, PRReviewBadge } from './PRBadges';
import { CommitTimeline } from './CommitTimeline';
import { AuthorAvatar } from './AuthorAvatar';
import { apiClient } from '@/api/client';

interface RepoDetailDrawerProps {
  repo: GitRepoItem | null;
  onClose: () => void;
  onSync: (repoId: string) => Promise<void>;
  onCreatePR: (repo: GitRepoItem) => void;
  onOpenPRDiff: (pr: IGitPullRequest, repo: GitRepoItem) => void;
  onMergePR: (repoId: string, prId: string) => Promise<void>;
  onTriggerReview?: (repoId: string, prId: string, reviewerAgent?: string) => Promise<void>;
  onDeleteRepo: (repoId: string) => Promise<void>;
}

export function RepoDetailDrawer({
  repo,
  onClose,
  onSync,
  onCreatePR,
  onOpenPRDiff,
  onMergePR,
  onDeleteRepo,
}: RepoDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<'prs' | 'commits' | 'branches' | 'squad' | 'settings'>('prs');
  const [isSyncing, setIsSyncing] = useState(false);
  const [copiedWebhook, setCopiedWebhook] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showCreateBranch, setShowCreateBranch] = useState(false);
  const [newBranchInput, setNewBranchInput] = useState('');
  const [isCreatingBranch, setIsCreatingBranch] = useState(false);
  const [branchMsg, setBranchMsg] = useState<string | null>(null);

  if (!repo) return null;

  const handleSyncClick = async () => {
    setIsSyncing(true);
    try {
      await onSync(repo.id);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleCreateBranchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBranchInput.trim()) return;
    setIsCreatingBranch(true);
    setBranchMsg(null);

    try {
      const parts = repo.name.split('/');
      if (parts.length === 2) {
        const [owner, repoName] = parts;
        const res = await apiClient.post<{ message: string; branch: any }>(
          `/api/v1/companies/00000000-0000-4000-8000-000000000001/github/repos/${owner}/${repoName}/branches`,
          { branch_name: newBranchInput.trim(), from_branch: repo.default_branch }
        );
        if (res?.branch) {
          if (!repo.branches) repo.branches = [];
          repo.branches.push(res.branch);
          setBranchMsg(`Branch '${newBranchInput}' created!`);
          setNewBranchInput('');
          setShowCreateBranch(false);
        }
      }
    } catch (err: any) {
      setBranchMsg(err?.detail || 'Failed to create branch');
    } finally {
      setIsCreatingBranch(false);
    }
  };

  const handleCopyWebhook = () => {
    if (repo.webhook_url) {
      navigator.clipboard.writeText(repo.webhook_url);
      setCopiedWebhook(true);
      setTimeout(() => setCopiedWebhook(false), 2000);
    }
  };

  const handleDeleteClick = async () => {
    if (window.confirm(`Are you sure you want to unmount repository "${repo.name}"?`)) {
      setIsDeleting(true);
      try {
        await onDeleteRepo(repo.id);
        onClose();
      } finally {
        setIsDeleting(false);
      }
    }
  };

  const langColor = getLanguageColor(repo.language);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="w-full max-w-3xl h-full bg-[#101012] border-l border-white/[0.12] flex flex-col shadow-2xl overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Top Header */}
        <div className="p-4 sm:p-5 border-b border-white/[0.08] bg-[#141417] flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-white/[0.04] text-[#FFB020] border border-white/[0.06] uppercase">
                {repo.provider}
              </span>
              <div className="flex items-center gap-1.5 text-xs font-mono text-[#A8A8AB]">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: langColor }} />
                <span>{repo.language}</span>
              </div>
              <span className="text-xs font-mono text-[#6B6B6E]">·</span>
              <div className="flex items-center gap-1 text-xs font-mono text-[#A8A8AB]">
                <GitBranch className="w-3.5 h-3.5 text-[#6B6B6E]" />
                <span>{repo.default_branch}</span>
              </div>
            </div>

            <h1 className="text-lg sm:text-xl font-medium text-[#F2F1EE] mt-2 font-mono truncate">
              {repo.name}
            </h1>
            {repo.description && (
              <p className="text-xs text-[#A8A8AB] mt-1 leading-relaxed line-clamp-2">
                {repo.description}
              </p>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleSyncClick}
              disabled={isSyncing}
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isSyncing ? 'animate-spin text-[#FFB020]' : ''}`} />
              {isSyncing ? 'Syncing...' : 'Sync AST'}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => onCreatePR(repo)}
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              New Agent PR
            </Button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-[6px] text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.06] transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Stats Metrics Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 sm:px-5 bg-[#0C0C0E] border-b border-white/[0.06] text-xs font-mono">
          <div className="p-2 rounded bg-white/[0.02] border border-white/[0.04]">
            <div className="text-[10px] text-[#6B6B6E] uppercase">AST Coverage</div>
            <div className="text-sm font-semibold text-[#38BDF8] flex items-center gap-1 mt-0.5">
              <Cpu className="w-3.5 h-3.5" />
              <span>{repo.ast_index_coverage}%</span>
            </div>
          </div>

          <div className="p-2 rounded bg-white/[0.02] border border-white/[0.04]">
            <div className="text-[10px] text-[#6B6B6E] uppercase">Security Gate</div>
            <div className="text-sm font-semibold text-[#22C55E] flex items-center gap-1 mt-0.5">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>{repo.security_score}%</span>
            </div>
          </div>

          <div className="p-2 rounded bg-white/[0.02] border border-white/[0.04]">
            <div className="text-[10px] text-[#6B6B6E] uppercase">Open Agent PRs</div>
            <div className="text-sm font-semibold text-[#FFB020] flex items-center gap-1 mt-0.5">
              <GitPullRequest className="w-3.5 h-3.5" />
              <span>{repo.open_prs_count} PRs</span>
            </div>
          </div>

          <div className="p-2 rounded bg-white/[0.02] border border-white/[0.04]">
            <div className="text-[10px] text-[#6B6B6E] uppercase">7-Day Commits</div>
            <div className="text-sm font-semibold text-[#F2F1EE] flex items-center gap-1 mt-0.5">
              <GitCommit className="w-3.5 h-3.5 text-[#A8A8AB]" />
              <span>{repo.total_commits_7d}</span>
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 px-4 sm:px-5 border-b border-white/[0.06] bg-[#0E0E10] text-xs font-mono overflow-x-auto">
          <button
            onClick={() => setActiveTab('prs')}
            className={`py-3 px-2 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
              activeTab === 'prs'
                ? 'border-[#FFB020] text-[#FFB020]'
                : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
          >
            <GitPullRequest className="w-3.5 h-3.5" />
            <span>Agent Pull Requests</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.06]">
              {repo.prs?.length || 0}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('commits')}
            className={`py-3 px-2 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
              activeTab === 'commits'
                ? 'border-[#FFB020] text-[#FFB020]'
                : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
          >
            <GitCommit className="w-3.5 h-3.5" />
            <span>Commits & AST Log</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.06]">
              {repo.commits?.length || 0}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('branches')}
            className={`py-3 px-2 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
              activeTab === 'branches'
                ? 'border-[#FFB020] text-[#FFB020]'
                : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
          >
            <GitBranch className="w-3.5 h-3.5" />
            <span>Branches ({repo.branches?.length || 0})</span>
          </button>

          <button
            onClick={() => setActiveTab('squad')}
            className={`py-3 px-2 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
              activeTab === 'squad'
                ? 'border-[#FFB020] text-[#FFB020]'
                : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Agent Squad ({repo.assigned_agents?.length || 0})</span>
          </button>

          <button
            onClick={() => setActiveTab('settings')}
            className={`py-3 px-2 border-b-2 font-medium transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
              activeTab === 'settings'
                ? 'border-[#FFB020] text-[#FFB020]'
                : 'border-transparent text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
          >
            <Settings className="w-3.5 h-3.5" />
            <span>Settings</span>
          </button>
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4 font-mono text-xs">
          {/* TAB 1: PULL REQUESTS */}
          {activeTab === 'prs' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A8A8AB]">
                <span>Autonomous Code Review Queue</span>
                <span className="text-[10px] text-[#6B6B6E]">
                  Click any PR to inspect AST diffs & reviews
                </span>
              </div>

              {repo.prs && repo.prs.length > 0 ? (
                <div className="space-y-3">
                  {repo.prs.map((pr) => (
                    <div
                      key={pr.id}
                      onClick={() => onOpenPRDiff(pr, repo)}
                      className="p-3.5 bg-[#141417] hover:bg-[#18181C] border border-white/[0.08] hover:border-[#FFB020]/40 rounded-[8px] transition-all cursor-pointer space-y-2.5 group"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[11px] font-semibold text-[#FFB020]">
                              #{pr.number}
                            </span>
                            <span className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                              {pr.title}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-[#6B6B6E]">
                            <span>
                              by <strong className="text-[#A8A8AB]">{pr.author}</strong>
                            </span>
                            <span>·</span>
                            <span>{pr.source_branch}</span>
                            <ArrowRight className="w-3 h-3 inline text-[#6B6B6E]" />
                            <span>{pr.target_branch}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
                          <PRStatusBadge status={pr.status} size="xs" />
                          <PRChecksBadge checks={pr.checks} size="xs" />
                          <PRReviewBadge reviewers={pr.reviewers} status={pr.status} size="xs" />
                        </div>
                      </div>

                      {/* Diff stats & AI Review Score */}
                      <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px]">
                        <div className="flex items-center gap-3">
                          <span className="text-emerald-400">+{pr.additions}</span>
                          <span className="text-rose-400">-{pr.deletions}</span>
                          <span className="text-[#6B6B6E]">{pr.changed_files_count} files</span>
                        </div>

                        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center gap-1 text-[#38BDF8] text-[10px]">
                            <Sparkles className="w-3 h-3" />
                            <span>{pr.ai_review_score}% Pass</span>
                          </div>

                          {pr.status === 'open' && (
                            <button
                              onClick={() => onMergePR(repo.id, pr.id)}
                              disabled={pr.checks === 'failed'}
                              title={pr.checks === 'failed' ? 'CI failed: Cannot merge until checks pass' : 'Merge PR'}
                              className={`px-2 py-0.5 rounded text-[10px] flex items-center gap-1 transition-colors ${
                                pr.checks === 'failed'
                                  ? 'bg-zinc-800 text-zinc-500 border border-zinc-700 cursor-not-allowed opacity-60'
                                  : 'bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-400 border border-emerald-500/30 cursor-pointer'
                              }`}
                            >
                              <GitMerge className="w-3 h-3" />
                              <span>Merge</span>
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 bg-[#141417]/50 rounded-[8px] border border-white/[0.04] space-y-3">
                  <GitPullRequest className="w-8 h-8 text-[#6B6B6E] mx-auto opacity-50" />
                  <div className="text-[#A8A8AB] text-xs">No pull requests currently open on this repo.</div>
                  <Button variant="primary" size="sm" onClick={() => onCreatePR(repo)}>
                    <Plus className="w-3.5 h-3.5 mr-1" />
                    Draft First Agent PR
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: COMMITS */}
          {activeTab === 'commits' && (
            <div className="space-y-3">
              <CommitTimeline
                commits={repo.commits || []}
                repoName={repo.name}
                defaultBranch={repo.default_branch}
                maxHeight="max-h-[540px]"
                showSearch={true}
                showFilters={true}
              />
            </div>
          )}

          {/* TAB 3: BRANCHES */}
          {activeTab === 'branches' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[#A8A8AB]">
                <span>Tracked Branches ({repo.branches?.length || 0})</span>
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={() => setShowCreateBranch(!showCreateBranch)}
                  icon={<Plus size={12} />}
                >
                  Create Branch
                </Button>
              </div>

              {branchMsg && (
                <div className="p-2 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[11px] font-mono">
                  {branchMsg}
                </div>
              )}

              {/* Inline Create Branch Form */}
              {showCreateBranch && (
                <form onSubmit={handleCreateBranchSubmit} className="p-3 bg-[#141416] border border-[#FFB020]/30 rounded-[8px] space-y-2.5 font-mono">
                  <div className="text-xs font-bold text-white flex items-center gap-2">
                    <GitBranch size={14} className="text-[#FFB020]" />
                    Create New Branch on GitHub
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={newBranchInput}
                      onChange={(e) => setNewBranchInput(e.target.value)}
                      placeholder="e.g. feat/agent-optimizer"
                      className="flex-1 px-3 py-1.5 bg-[#0A0A0C] border border-white/[0.12] rounded text-xs text-white placeholder-gray-600 focus:outline-none focus:border-[#FFB020]"
                      required
                    />
                    <Button variant="primary" size="xs" type="submit" disabled={isCreatingBranch}>
                      {isCreatingBranch ? 'Creating...' : 'Create'}
                    </Button>
                  </div>
                  <p className="text-[10px] text-gray-500">
                    Branch will be created off base branch <code className="text-[#FFB020]">{repo.default_branch}</code>.
                  </p>
                </form>
              )}

              <div className="space-y-2">
                {repo.branches?.map((branch) => (
                  <div
                    key={branch.name}
                    className="p-3 bg-[#141417] border border-white/[0.06] rounded-[8px] flex items-center justify-between gap-3"
                  >
                    <div className="flex items-center gap-2.5">
                      <GitBranch className="w-4 h-4 text-[#FFB020]" />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-[#F2F1EE]">
                            {branch.name}
                          </span>
                          {branch.is_protected && (
                            <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px]">
                              Protected
                            </span>
                          )}
                          {branch.name === repo.default_branch && (
                            <span className="px-1.5 py-0.2 rounded bg-white/[0.06] text-[#A8A8AB] text-[9px]">
                              Default
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-[#6B6B6E] mt-0.5 truncate">
                          {branch.last_commit_message} ({branch.last_commit_time})
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-[#6B6B6E] font-mono">
                        {branch.last_commit_hash}
                      </span>

                      {repo.name.includes('/') && (
                        <a
                          href={`https://github.com/${repo.name}/tree/${branch.name}`}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1 text-gray-500 hover:text-white transition-colors"
                          title={`View ${branch.name} branch on GitHub`}
                        >
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 4: SQUAD & CONTRIBUTORS */}
          {activeTab === 'squad' && (
            <div className="space-y-4">
              <div className="text-xs text-[#A8A8AB]">
                Assigned Squad & Autonomous Contributors
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {repo.contributors?.map((contrib) => (
                  <div
                    key={contrib.name}
                    className="p-3 bg-[#141417] border border-white/[0.06] rounded-[8px] flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2.5">
                      <AuthorAvatar name={contrib.name} size="md" />
                      <div>
                        <div className="text-xs font-medium text-[#F2F1EE]">
                          {contrib.name}
                        </div>
                        <div className="text-[10px] text-[#6B6B6E]">{contrib.role}</div>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-xs font-semibold text-[#FFB020]">
                        {contrib.commits}
                      </div>
                      <div className="text-[9px] text-[#6B6B6E]">commits</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 5: SETTINGS */}
          {activeTab === 'settings' && (
            <div className="space-y-4">
              <div className="text-xs text-[#A8A8AB] uppercase tracking-wider">
                Repository Settings & Webhooks
              </div>

              {/* Webhook URL */}
              <div className="p-3.5 bg-[#141417] border border-white/[0.06] rounded-[8px] space-y-2">
                <div className="text-xs font-medium text-[#F2F1EE]">
                  Automated Event Webhook Ingress
                </div>
                <p className="text-[11px] text-[#6B6B6E] font-sans">
                  NEXUS listens to push, PR, and review events to maintain live AST symbols.
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    readOnly
                    value={repo.webhook_url || 'https://api.nexus.nvlabs.internal/webhooks/gh-events'}
                    className="flex-1 px-3 py-1.5 bg-[#0A0A0C] border border-white/[0.08] rounded text-[11px] text-[#A8A8AB] font-mono focus:outline-none"
                  />
                  <Button variant="secondary" size="sm" onClick={handleCopyWebhook}>
                    {copiedWebhook ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    {copiedWebhook ? 'Copied' : 'Copy'}
                  </Button>
                </div>
              </div>

              {/* Danger Zone: Unmount */}
              <div className="p-3.5 bg-red-500/[0.04] border border-red-500/20 rounded-[8px] space-y-3">
                <div className="text-xs font-medium text-red-400 flex items-center gap-1.5">
                  <Trash2 className="w-4 h-4" />
                  <span>Unmount Repository</span>
                </div>
                <p className="text-[11px] text-[#A8A8AB] font-sans">
                  Disconnects this codebase from NEXUS. Stored AST indices and memory graphs will be unlinked.
                </p>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleDeleteClick}
                  disabled={isDeleting}
                >
                  {isDeleting ? 'Unmounting...' : 'Unmount Repository'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
