import React, { useState, useMemo } from 'react';
import {
  GitCommit,
  Search,
  Copy,
  Check,
  Cpu,
  TrendingUp,
  ExternalLink,
} from 'lucide-react';
import type { AggregatedCommit, GitRepoItem } from '@/types/gitRepo';
import { getLanguageColor, formatTimeAgo } from './gitUtils';
import { Button } from '@/components/common/Button';
import { AuthorAvatar } from './AuthorAvatar';

interface AllCommitsListProps {
  repos: GitRepoItem[];
  onSelectRepo: (repo: GitRepoItem) => void;
}

export function AllCommitsList({ repos, onSelectRepo }: AllCommitsListProps) {
  const [search, setSearch] = useState('');
  const [selectedRepoId, setSelectedRepoId] = useState<string>('all');
  const [selectedAuthor, setSelectedAuthor] = useState<string>('all');
  const [selectedCommitType, setSelectedCommitType] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'newest' | 'lines' | 'hash'>('newest');
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  // Flatten all commits across repos
  const allCommits = useMemo<AggregatedCommit[]>(() => {
    const list: AggregatedCommit[] = [];
    repos.forEach((repo) => {
      (repo.commits || []).forEach((c) => {
        list.push({
          ...c,
          repo_id: repo.id,
          repo_name: repo.name,
          repo_language: repo.language,
          repo_default_branch: repo.default_branch,
        });
      });
    });
    return list;
  }, [repos]);

  // Unique authors
  const uniqueAuthors = useMemo(() => {
    const set = new Set<string>();
    allCommits.forEach((c) => {
      if (c.author) set.add(c.author);
    });
    return Array.from(set);
  }, [allCommits]);

  // Filtered & sorted commits
  const filteredCommits = useMemo(() => {
    const q = search.toLowerCase();
    const result = allCommits.filter((c) => {
      const matchesSearch =
        !q ||
        c.message.toLowerCase().includes(q) ||
        c.hash.toLowerCase().includes(q) ||
        c.author.toLowerCase().includes(q) ||
        c.repo_name.toLowerCase().includes(q);

      const matchesRepo = selectedRepoId === 'all' || c.repo_id === selectedRepoId;
      const matchesAuthor = selectedAuthor === 'all' || c.author === selectedAuthor;
      
      let matchesType = true;
      if (selectedCommitType !== 'all') {
        matchesType = c.message.toLowerCase().startsWith(selectedCommitType.toLowerCase());
      }

      return matchesSearch && matchesRepo && matchesAuthor && matchesType;
    });

    result.sort((a, b) => {
      if (sortBy === 'lines') return (b.additions + b.deletions) - (a.additions + a.deletions);
      if (sortBy === 'hash') return a.hash.localeCompare(b.hash);
      // default: newest
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    });

    return result;
  }, [allCommits, search, selectedRepoId, selectedAuthor, selectedCommitType, sortBy]);

  // Summary Metrics
  const totalAdditions = useMemo(() => allCommits.reduce((s, c) => s + (c.additions || 0), 0), [allCommits]);
  const totalDeletions = useMemo(() => allCommits.reduce((s, c) => s + (c.deletions || 0), 0), [allCommits]);
  const astIndexedCount = useMemo(() => allCommits.filter((c) => c.ast_indexed).length, [allCommits]);

  const handleCopyHash = (hash: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  // Helper to colorize conventional commit message prefix
  const renderFormattedMessage = (msg: string) => {
    const match = msg.match(/^([a-zA-Z0-9_-]+)(\([^)]+\))?:\s*(.*)$/);
    if (!match) return <span>{msg}</span>;

    const [, type, scope, body] = match;
    let badgeClass = 'text-[#A8A8AB] bg-white/[0.06]';
    if (type === 'feat') badgeClass = 'text-[#22C55E] bg-[#22C55E]/10 border-[#22C55E]/20';
    else if (type === 'fix') badgeClass = 'text-[#FFB020] bg-[#FFB020]/10 border-[#FFB020]/20';
    else if (type === 'perf') badgeClass = 'text-[#38BDF8] bg-[#38BDF8]/10 border-[#38BDF8]/20';
    else if (type === 'sec') badgeClass = 'text-[#C084FC] bg-[#C084FC]/10 border-[#C084FC]/20';
    else if (type === 'refactor') badgeClass = 'text-[#818CF8] bg-[#818CF8]/10 border-[#818CF8]/20';
    else if (type === 'test') badgeClass = 'text-[#F43F5E] bg-[#F43F5E]/10 border-[#F43F5E]/20';

    return (
      <span className="flex items-center gap-1.5 flex-wrap">
        <span className={`px-1.5 py-0.2 rounded border text-[11px] font-mono font-medium ${badgeClass}`}>
          {type}{scope || ''}
        </span>
        <span className="text-[#F2F1EE]">{body}</span>
      </span>
    );
  };

  return (
    <div className="space-y-4">
      {/* Top Metrics Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-[#101012] border border-white/[0.08] rounded-[8px] p-3 font-mono">
          <div className="text-[11px] text-[#6B6B6E]">Total Commits</div>
          <div className="text-lg font-medium text-[#F2F1EE] mt-0.5">{allCommits.length}</div>
          <div className="text-[10px] text-[#22C55E] flex items-center gap-1 mt-1">
            <TrendingUp className="w-2.5 h-2.5" />
            <span>Autonomous agent commits</span>
          </div>
        </div>

        <div className="bg-[#101012] border border-white/[0.08] rounded-[8px] p-3 font-mono">
          <div className="text-[11px] text-[#6B6B6E]">Code Changes (LoC)</div>
          <div className="text-lg font-medium text-[#22C55E] mt-0.5">
            +{totalAdditions} <span className="text-xs text-[#EF4444]">-{totalDeletions}</span>
          </div>
          <div className="text-[10px] text-[#6B6B6E] mt-1">Net +{totalAdditions - totalDeletions} lines</div>
        </div>

        <div className="bg-[#101012] border border-white/[0.08] rounded-[8px] p-3 font-mono">
          <div className="text-[11px] text-[#6B6B6E]">AST Index Coverage</div>
          <div className="text-lg font-medium text-[#38BDF8] mt-0.5">
            {allCommits.length ? Math.round((astIndexedCount / allCommits.length) * 100) : 100}%
          </div>
          <div className="text-[10px] text-[#38BDF8] flex items-center gap-1 mt-1">
            <Cpu className="w-2.5 h-2.5" />
            <span>Symbol Graph Linked</span>
          </div>
        </div>

        <div className="bg-[#101012] border border-white/[0.08] rounded-[8px] p-3 font-mono">
          <div className="text-[11px] text-[#6B6B6E]">Active Authors</div>
          <div className="text-lg font-medium text-[#FFB020] mt-0.5">{uniqueAuthors.length} Agents</div>
          <div className="text-[10px] text-[#A8A8AB] mt-1">Across {repos.length} Repositories</div>
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
              placeholder="Search commit message, hash, agent, or repository..."
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

          {/* Conventional commit type selector */}
          <select
            value={selectedCommitType}
            onChange={(e) => setSelectedCommitType(e.target.value)}
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
          >
            <option value="all">All Commit Types</option>
            <option value="feat">feat (Features)</option>
            <option value="fix">fix (Bug Fixes)</option>
            <option value="perf">perf (Performance)</option>
            <option value="sec">sec (Security)</option>
            <option value="refactor">refactor (Refactors)</option>
            <option value="chore">chore (Tooling/Deps)</option>
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
            <option value="newest">Sort: Newest First</option>
            <option value="lines">Sort: Most Changed Lines</option>
            <option value="hash">Sort: Hash</option>
          </select>
        </div>
      </div>

      {/* Commits Timeline Feed */}
      {filteredCommits.length > 0 ? (
        <div className="space-y-2">
          {filteredCommits.map((c) => {
            const parentRepo = repos.find((r) => r.id === c.repo_id);
            const langColor = getLanguageColor(c.repo_language);
            const isCopied = copiedHash === c.hash;

            return (
              <div
                key={`${c.repo_id}-${c.hash}`}
                onClick={() => parentRepo && onSelectRepo(parentRepo)}
                className="group relative bg-[#101012] hover:bg-[#141417] border border-white/[0.08] hover:border-[#FFB020]/40 rounded-[8px] p-3 transition-all duration-150 cursor-pointer shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-3 font-mono"
              >
                {/* Left Section: Hash & Message & Repo Tag */}
                <div className="flex items-start md:items-center gap-3 min-w-0 flex-1">
                  {/* Git Commit Hash Button */}
                  <button
                    onClick={(e) => handleCopyHash(c.hash, e)}
                    title="Click to copy commit SHA"
                    className="flex items-center gap-1 px-2 py-1 rounded bg-[#18181C] hover:bg-[#222226] border border-white/[0.08] text-xs text-[#FFB020] hover:text-[#F2F1EE] transition-colors shrink-0 cursor-pointer group/btn"
                  >
                    <GitCommit className="w-3 h-3 text-[#FFB020]" />
                    <span>{c.hash.slice(0, 7)}</span>
                    {isCopied ? (
                      <Check className="w-3 h-3 text-[#22C55E] animate-in zoom-in" />
                    ) : (
                      <Copy className="w-2.5 h-2.5 text-[#6B6B6E] group-hover/btn:text-[#F2F1EE]" />
                    )}
                  </button>

                  {/* Message & Context */}
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors truncate">
                      {renderFormattedMessage(c.message)}
                    </div>

                    <div className="flex items-center gap-2 mt-1 text-[11px] text-[#6B6B6E] flex-wrap">
                      {/* Repo Name */}
                      <span className="flex items-center gap-1 text-[#A8A8AB]">
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: langColor }} />
                        <span>{c.repo_name}</span>
                      </span>

                      <span>·</span>

                      {/* Author */}
                      <span className="flex items-center gap-1.5 text-[#A8A8AB]">
                        <AuthorAvatar name={c.author} avatarUrl={c.author_avatar} size="xs" />
                        <span>{c.author}</span>
                      </span>

                      <span>·</span>

                      {/* Time */}
                      <span>{c.relative_time || formatTimeAgo(c.timestamp)}</span>
                    </div>
                  </div>
                </div>

                {/* Right Section: LoC additions/deletions + AST badge */}
                <div
                  className="flex items-center gap-3 shrink-0 self-end md:self-center text-xs"
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* AST indexed badge */}
                  {c.ast_indexed && (
                    <span
                      title="Semantic AST symbol relations indexed"
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-[#38BDF8]/10 text-[#38BDF8] border border-[#38BDF8]/20 text-[10px]"
                    >
                      <Cpu className="w-2.5 h-2.5" />
                      AST
                    </span>
                  )}

                  {/* Additions / Deletions */}
                  <div className="flex items-center gap-1 text-[11px] bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.04]">
                    <span className="text-[#22C55E]">+{c.additions}</span>
                    <span className="text-[#EF4444]">-{c.deletions}</span>
                  </div>

                  {/* Open Repo Drawer Button */}
                  <button
                    onClick={() => parentRepo && onSelectRepo(parentRepo)}
                    className="p-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-[#6B6B6E] hover:text-[#F2F1EE] transition-colors cursor-pointer"
                    title="Inspect Repository Workspace"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-16 bg-[#101012] border border-white/[0.06] rounded-[10px] space-y-3 font-mono">
          <GitCommit className="w-10 h-10 text-[#6B6B6E] mx-auto opacity-50" />
          <div className="text-sm text-[#F2F1EE]">No commits match your filter</div>
          <p className="text-xs text-[#6B6B6E]">
            Try adjusting your search query, selecting another repository, or picking another commit type.
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setSearch('');
              setSelectedRepoId('all');
              setSelectedAuthor('all');
              setSelectedCommitType('all');
            }}
          >
            Clear Filters
          </Button>
        </div>
      )}
    </div>
  );
}
