import React, { useState, useMemo } from 'react';
import {
  GitPullRequest,
  Search,
  Sparkles,
  ArrowRight,
  GitMerge,
  ExternalLink,
  ShieldCheck,
  FileCode,
  User,
  Zap,
  Clock,
  AlertOctagon,
  XCircle,
} from 'lucide-react';
import type { AggregatedPR, GitRepoItem, GitPullRequest as IGitPullRequest } from '@/types/gitRepo';
import { getLanguageColor, formatTimeAgo } from './gitUtils';
import { Button } from '@/components/common/Button';
import { PRStatusBadge, PRChecksBadge, PRReviewBadge } from './PRBadges';

interface AllPRsListProps {
  repos: GitRepoItem[];
  onOpenDiff: (pr: IGitPullRequest, repo: GitRepoItem) => void;
  onMergePR: (repoId: string, prId: string) => Promise<void>;
  onTriggerReview: (repoId: string, prId: string, reviewerAgent?: string) => Promise<void>;
  onSelectRepo: (repo: GitRepoItem) => void;
  onCreatePRClick: () => void;
}

type StatusFilterType = 'all' | 'open' | 'needs_review' | 'ci_failed' | 'merged' | 'closed';

export function AllPRsList({
  repos,
  onOpenDiff,
  onMergePR,
  onTriggerReview,
  onSelectRepo,
  onCreatePRClick,
}: AllPRsListProps) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilterType>('all');
  const [selectedRepoId, setSelectedRepoId] = useState<string>('all');
  const [selectedAuthor, setSelectedAuthor] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'updated' | 'score' | 'additions' | 'number'>('updated');
  const [mergingId, setMergingId] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  // Flatten all PRs from repos
  const allPRs = useMemo<AggregatedPR[]>(() => {
    const list: AggregatedPR[] = [];
    repos.forEach((repo) => {
      (repo.prs || []).forEach((pr) => {
        list.push({
          ...pr,
          repo_id: repo.id,
          repo_name: repo.name,
          repo_language: repo.language,
          repo_default_branch: repo.default_branch,
        });
      });
    });
    return list;
  }, [repos]);

  // Unique authors across all PRs
  const uniqueAuthors = useMemo(() => {
    const set = new Set<string>();
    allPRs.forEach((pr) => {
      if (pr.author) set.add(pr.author);
    });
    return Array.from(set);
  }, [allPRs]);

  // Derived counts
  const openCount = useMemo(() => allPRs.filter((p) => p.status === 'open').length, [allPRs]);
  const mergedCount = useMemo(() => allPRs.filter((p) => p.status === 'merged').length, [allPRs]);
  const closedCount = useMemo(() => allPRs.filter((p) => p.status === 'closed').length, [allPRs]);
  const ciFailedCount = useMemo(() => allPRs.filter((p) => p.checks === 'failed').length, [allPRs]);
  const needsReviewCount = useMemo(() => {
    return allPRs.filter((p) => {
      if (p.status !== 'open') return false;
      const approved = (p.reviewers || []).some((r) => r.decision === 'approved');
      return !approved;
    }).length;
  }, [allPRs]);

  const avgScore = useMemo(() => {
    if (!allPRs.length) return 0;
    const sum = allPRs.reduce((acc, p) => acc + (p.ai_review_score || 95), 0);
    return Math.round(sum / allPRs.length);
  }, [allPRs]);

  // Filtered & sorted PRs
  const filteredPRs = useMemo(() => {
    const q = search.toLowerCase();
    const result = allPRs.filter((pr) => {
      const matchesSearch =
        !q ||
        pr.title.toLowerCase().includes(q) ||
        pr.description?.toLowerCase().includes(q) ||
        pr.author.toLowerCase().includes(q) ||
        pr.repo_name.toLowerCase().includes(q) ||
        pr.source_branch.toLowerCase().includes(q) ||
        String(pr.number).includes(q);

      let matchesStatus = true;
      if (statusFilter === 'open') {
        matchesStatus = pr.status === 'open';
      } else if (statusFilter === 'merged') {
        matchesStatus = pr.status === 'merged';
      } else if (statusFilter === 'closed') {
        matchesStatus = pr.status === 'closed';
      } else if (statusFilter === 'ci_failed') {
        matchesStatus = pr.checks === 'failed';
      } else if (statusFilter === 'needs_review') {
        const approved = (pr.reviewers || []).some((r) => r.decision === 'approved');
        matchesStatus = pr.status === 'open' && !approved;
      }

      const matchesRepo = selectedRepoId === 'all' || pr.repo_id === selectedRepoId;
      const matchesAuthor = selectedAuthor === 'all' || pr.author === selectedAuthor;

      return matchesSearch && matchesStatus && matchesRepo && matchesAuthor;
    });

    result.sort((a, b) => {
      if (sortBy === 'score') return (b.ai_review_score || 0) - (a.ai_review_score || 0);
      if (sortBy === 'additions') return (b.additions || 0) - (a.additions || 0);
      if (sortBy === 'number') return b.number - a.number;
      // default: updated
      return new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime();
    });

    return result;
  }, [allPRs, search, statusFilter, selectedRepoId, selectedAuthor, sortBy]);

  const handleMerge = async (repoId: string, prId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setMergingId(prId);
    try {
      await onMergePR(repoId, prId);
    } finally {
      setMergingId(null);
    }
  };

  const handleReview = async (repoId: string, prId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setReviewingId(prId);
    try {
      await onTriggerReview(repoId, prId, 'Shield-07');
    } finally {
      setReviewingId(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Top Quick Status Pill Tabs & Filter Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-[#101012] border border-white/[0.08] rounded-[10px] p-3 text-xs font-mono">
        {/* Status Filters */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1.5 rounded-[6px] border transition-colors cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'all'
                ? 'bg-[#FFB020]/15 text-[#FFB020] border-[#FFB020]/40 font-medium'
                : 'bg-[#141416] text-[#A8A8AB] border-white/[0.06] hover:bg-white/[0.04]'
            }`}
          >
            <span>All PRs</span>
            <span className="px-1.5 py-0.2 rounded bg-black/40 text-[10px] text-[#F2F1EE]">
              {allPRs.length}
            </span>
          </button>

          <button
            onClick={() => setStatusFilter('open')}
            className={`px-3 py-1.5 rounded-[6px] border transition-colors cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'open'
                ? 'bg-[#22C55E]/15 text-[#22C55E] border-[#22C55E]/40 font-medium'
                : 'bg-[#141416] text-[#A8A8AB] border-white/[0.06] hover:bg-white/[0.04]'
            }`}
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span>Open</span>
            <span className="px-1.5 py-0.2 rounded bg-black/40 text-[10px] text-[#22C55E]">
              {openCount}
            </span>
          </button>

          <button
            onClick={() => setStatusFilter('needs_review')}
            className={`px-3 py-1.5 rounded-[6px] border transition-colors cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'needs_review'
                ? 'bg-amber-500/20 text-amber-400 border-amber-500/50 font-medium shadow-[0_0_10px_rgba(245,158,11,0.2)]'
                : 'bg-[#141416] text-[#A8A8AB] border-white/[0.06] hover:bg-white/[0.04]'
            }`}
          >
            <Clock className="w-3 h-3 text-amber-400" />
            <span>Needs Review</span>
            <span className="px-1.5 py-0.2 rounded bg-black/40 text-[10px] text-amber-400">
              {needsReviewCount}
            </span>
          </button>

          {ciFailedCount > 0 && (
            <button
              onClick={() => setStatusFilter('ci_failed')}
              className={`px-3 py-1.5 rounded-[6px] border transition-colors cursor-pointer flex items-center gap-1.5 ${
                statusFilter === 'ci_failed'
                  ? 'bg-rose-500/20 text-rose-400 border-rose-500/50 font-medium shadow-[0_0_10px_rgba(244,63,94,0.2)]'
                  : 'bg-[#141416] text-rose-400/80 border-rose-500/30 hover:bg-rose-500/10'
              }`}
            >
              <AlertOctagon className="w-3 h-3 text-rose-400" />
              <span>CI Failed</span>
              <span className="px-1.5 py-0.2 rounded bg-black/40 text-[10px] text-rose-400 font-bold">
                {ciFailedCount}
              </span>
            </button>
          )}

          <button
            onClick={() => setStatusFilter('merged')}
            className={`px-3 py-1.5 rounded-[6px] border transition-colors cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'merged'
                ? 'bg-[#A855F7]/15 text-[#C084FC] border-[#A855F7]/40 font-medium'
                : 'bg-[#141416] text-[#A8A8AB] border-white/[0.06] hover:bg-white/[0.04]'
            }`}
          >
            <GitMerge className="w-3 h-3 text-[#C084FC]" />
            <span>Merged</span>
            <span className="px-1.5 py-0.2 rounded bg-black/40 text-[10px] text-[#C084FC]">
              {mergedCount}
            </span>
          </button>

          <button
            onClick={() => setStatusFilter('closed')}
            className={`px-3 py-1.5 rounded-[6px] border transition-colors cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'closed'
                ? 'bg-rose-500/15 text-rose-400 border-rose-500/40 font-medium'
                : 'bg-[#141416] text-[#A8A8AB] border-white/[0.06] hover:bg-white/[0.04]'
            }`}
          >
            <XCircle className="w-3 h-3 text-rose-400" />
            <span>Closed</span>
            <span className="px-1.5 py-0.2 rounded bg-black/40 text-[10px] text-rose-400">
              {closedCount}
            </span>
          </button>
        </div>

        {/* Quality Banner Pill */}
        <div className="flex items-center gap-3 text-xs text-[#A8A8AB] bg-[#141416] px-3 py-1.5 rounded-[6px] border border-white/[0.06] shrink-0">
          <div className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-[#FFB020]" />
            <span>Avg AST Quality:</span>
            <span className="text-[#22C55E] font-medium">{avgScore}%</span>
          </div>
          <span className="text-white/20">|</span>
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-[#38BDF8]" />
            <span>CI Health:</span>
            <span className={ciFailedCount > 0 ? 'text-amber-400' : 'text-[#38BDF8]'}>
              {allPRs.length - ciFailedCount} / {allPRs.length} Clean
            </span>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-[#101012] p-3 border border-white/[0.08] rounded-[10px] flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 text-xs font-mono">
        <div className="flex-1 flex items-center gap-2 max-w-md">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search PR title, #number, agent, branch, or repo..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Repo selector */}
          <select
            value={selectedRepoId}
            onChange={(e) => setSelectedRepoId(e.target.value)}
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
          >
            <option value="all">All Repositories</option>
            {repos.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>

          {/* Author Agent selector */}
          <select
            value={selectedAuthor}
            onChange={(e) => setSelectedAuthor(e.target.value)}
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
          >
            <option value="all">All Authors</option>
            {uniqueAuthors.map((author) => (
              <option key={author} value={author}>
                {author}
              </option>
            ))}
          </select>

          {/* Sort By */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
          >
            <option value="updated">Sort: Recently Updated</option>
            <option value="score">Sort: Highest AI Score</option>
            <option value="additions">Sort: Most Changed Lines</option>
            <option value="number">Sort: PR # (Newest)</option>
          </select>
        </div>
      </div>

      {/* Pull Requests List */}
      {filteredPRs.length > 0 ? (
        <div className="space-y-3">
          {filteredPRs.map((pr) => {
            const parentRepo = repos.find((r) => r.id === pr.repo_id);
            const langColor = getLanguageColor(pr.repo_language);

            const scoreColor =
              (pr.ai_review_score || 95) >= 90
                ? 'text-[#22C55E] bg-[#22C55E]/10 border-[#22C55E]/20'
                : (pr.ai_review_score || 95) >= 75
                ? 'text-amber-400 bg-amber-500/10 border-amber-500/20'
                : 'text-rose-400 bg-rose-500/10 border-rose-500/20';

            return (
              <div
                key={`${pr.repo_id}-${pr.id}`}
                onClick={() => parentRepo && onOpenDiff(pr, parentRepo)}
                className={`group relative bg-[#101012] hover:bg-[#141417] border rounded-[10px] p-4 transition-all duration-200 cursor-pointer shadow-md ${
                  pr.checks === 'failed'
                    ? 'border-rose-500/30 hover:border-rose-500/60'
                    : 'border-white/[0.08] hover:border-[#FFB020]/40'
                }`}
              >
                <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3">
                  {/* Left Column: PR Info */}
                  <div className="min-w-0 flex-1">
                    {/* Header line: Repo badge + PR Number + Status + CI Checks + Review Badges */}
                    <div className="flex items-center gap-2 flex-wrap text-xs font-mono">
                      {/* Repo Chip */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (parentRepo) onSelectRepo(parentRepo);
                        }}
                        className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] text-[#A8A8AB] hover:text-[#F2F1EE] border border-white/[0.06] transition-colors"
                        title="View repository drawer"
                      >
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: langColor }} />
                        <span className="font-medium text-[#F2F1EE]">{pr.repo_name}</span>
                        <ExternalLink className="w-2.5 h-2.5 text-[#6B6B6E]" />
                      </button>

                      <span className="text-[#6B6B6E]">#{pr.number}</span>

                      {/* Color-Coded PR Status Badge (Open / Merged / Closed / Draft) */}
                      <PRStatusBadge status={pr.status} size="sm" />

                      {/* Color-Coded CI Checks Badge (CI Passed / CI Failed / CI Running / CI Pending) */}
                      <PRChecksBadge checks={pr.checks} size="sm" />

                      {/* Review State Badge (Needs Review / Approved / Changes Requested) */}
                      <PRReviewBadge reviewers={pr.reviewers} status={pr.status} size="sm" />

                      {/* Time */}
                      <span className="text-[#6B6B6E] text-[11px] ml-auto lg:ml-0">
                        {formatTimeAgo(pr.updated_at || pr.created_at)}
                      </span>
                    </div>

                    {/* PR Title */}
                    <div className="mt-2 flex items-baseline gap-2">
                      <h3 className="text-sm font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors leading-snug">
                        {pr.title}
                      </h3>
                    </div>

                    {/* PR Description snippet */}
                    {pr.description && (
                      <p className="text-xs text-[#A8A8AB] mt-1 line-clamp-2 leading-relaxed">
                        {pr.description}
                      </p>
                    )}

                    {/* Branch routing + Author + Diff stats bar */}
                    <div className="mt-3 flex items-center gap-3 flex-wrap text-xs font-mono text-[#6B6B6E]">
                      {/* Branch routing */}
                      <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-white/[0.04] border border-white/[0.04] text-[#A8A8AB]">
                        <span className="text-[#38BDF8]">{pr.source_branch}</span>
                        <ArrowRight className="w-3 h-3 text-[#6B6B6E]" />
                        <span>{pr.target_branch}</span>
                      </div>

                      {/* Author Agent */}
                      <div className="flex items-center gap-1 text-[#A8A8AB]">
                        <User className="w-3 h-3 text-[#FFB020]" />
                        <span className="text-[#F2F1EE] font-medium">{pr.author}</span>
                        {pr.author_role && <span className="text-[#6B6B6E]">({pr.author_role})</span>}
                      </div>

                      {/* Lines Changed */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-emerald-400">+{pr.additions}</span>
                        <span className="text-rose-400">-{pr.deletions}</span>
                        <span className="text-[#6B6B6E]">({pr.changed_files_count || 1} files)</span>
                      </div>
                    </div>
                  </div>

                  {/* Right Column: AI Score & Actions */}
                  <div
                    className="flex lg:flex-col items-center lg:items-end justify-between lg:justify-center gap-3 shrink-0 pt-2 lg:pt-0 border-t lg:border-t-0 border-white/[0.06]"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* AST AI Review Score Pill */}
                    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[6px] border text-xs font-mono ${scoreColor}`}>
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>{pr.ai_review_score}% AST Gate</span>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center gap-1.5">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => parentRepo && onOpenDiff(pr, parentRepo)}
                      >
                        <FileCode className="w-3 h-3 mr-1" />
                        Inspect Diff
                      </Button>

                      {pr.status === 'open' && (
                        <>
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={reviewingId === pr.id}
                            onClick={(e) => handleReview(pr.repo_id, pr.id, e)}
                            title="Run Shield-07 security & AST verification"
                          >
                            <ShieldCheck className="w-3 h-3 mr-1 text-[#38BDF8]" />
                            {reviewingId === pr.id ? 'Auditing...' : 'Audit'}
                          </Button>

                          <Button
                            variant="primary"
                            size="sm"
                            disabled={mergingId === pr.id || pr.checks === 'failed'}
                            onClick={(e) => handleMerge(pr.repo_id, pr.id, e)}
                            title={
                              pr.checks === 'failed'
                                ? 'CI failed: resolving pipeline errors is required before merge'
                                : 'Merge PR into target branch'
                            }
                            className={
                              pr.checks === 'failed'
                                ? 'opacity-50 cursor-not-allowed bg-zinc-800 text-zinc-500 border-zinc-700'
                                : ''
                            }
                          >
                            <GitMerge className="w-3 h-3 mr-1" />
                            {mergingId === pr.id ? 'Merging...' : 'Merge'}
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-16 bg-[#101012] border border-white/[0.06] rounded-[10px] space-y-3 font-mono">
          <GitPullRequest className="w-10 h-10 text-[#6B6B6E] mx-auto opacity-50" />
          <div className="text-sm text-[#F2F1EE]">No pull requests match your filter</div>
          <p className="text-xs text-[#6B6B6E]">
            Try adjusting your search criteria, selecting another repository, or dispatching an agent PR.
          </p>
          <div className="flex items-center justify-center gap-2 pt-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setSearch('');
                setStatusFilter('all');
                setSelectedRepoId('all');
                setSelectedAuthor('all');
              }}
            >
              Clear Filters
            </Button>
            <Button variant="primary" size="sm" onClick={onCreatePRClick}>
              <Zap className="w-3.5 h-3.5 mr-1" />
              Dispatch Agent PR
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
