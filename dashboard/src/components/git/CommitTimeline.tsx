import React, { useState, useMemo } from 'react';
import {
  GitCommit,
  Copy,
  Check,
  Cpu,
  Search,
  Clock,
  Code2,
} from 'lucide-react';
import type { GitCommit as IGitCommit } from '@/types/gitRepo';
import { AuthorAvatar } from './AuthorAvatar';

interface CommitTimelineProps {
  commits: IGitCommit[];
  repoName?: string;
  defaultBranch?: string;
  maxHeight?: string;
  showSearch?: boolean;
  showFilters?: boolean;
  compact?: boolean;
  onSelectCommit?: (commit: IGitCommit) => void;
  className?: string;
}

export function CommitTimeline({
  commits = [],
  repoName,
  defaultBranch = 'main',
  maxHeight = 'max-h-[460px]',
  showSearch = true,
  showFilters = true,
  compact = false,
  onSelectCommit,
  className = '',
}: CommitTimelineProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  const handleCopyHash = (hash: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  // Helper to parse and render formatted commit messages
  const renderCommitMessage = (message: string) => {
    const match = message.match(/^([a-zA-Z0-9_-]+)(\([^)]+\))?:\s*(.*)$/);
    if (!match) {
      return <span className="text-[#F2F1EE] break-words">{message}</span>;
    }

    const [, type = '', scope = '', body = ''] = match;
    let typeClass = 'bg-white/[0.06] text-[#A8A8AB] border-white/[0.08]';

    switch (type.toLowerCase()) {
      case 'feat':
        typeClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25';
        break;
      case 'fix':
        typeClass = 'bg-amber-500/10 text-amber-400 border-amber-500/25';
        break;
      case 'perf':
        typeClass = 'bg-sky-500/10 text-sky-400 border-sky-500/25';
        break;
      case 'sec':
        typeClass = 'bg-purple-500/10 text-purple-400 border-purple-500/25';
        break;
      case 'refactor':
        typeClass = 'bg-indigo-500/10 text-indigo-400 border-indigo-500/25';
        break;
      case 'test':
        typeClass = 'bg-rose-500/10 text-rose-400 border-rose-500/25';
        break;
      case 'chore':
      case 'deps':
        typeClass = 'bg-zinc-500/10 text-zinc-400 border-zinc-500/25';
        break;
      default:
        typeClass = 'bg-white/[0.06] text-[#FFB020] border-white/[0.08]';
    }

    return (
      <div className="flex items-start gap-1.5 flex-wrap">
        <span className={`inline-flex items-center px-1.5 py-0.2 rounded border text-[10px] font-mono font-medium shrink-0 uppercase tracking-tight ${typeClass}`}>
          {type}{scope || ''}
        </span>
        <span className="text-[#F2F1EE] leading-snug font-sans text-xs">{body}</span>
      </div>
    );
  };

  // Helper for absolute readable timestamp tooltip
  const formatFullDate = (timestamp?: string) => {
    if (!timestamp) return 'Recent commit';
    try {
      const d = new Date(timestamp);
      return d.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZoneName: 'short',
      });
    } catch {
      return timestamp;
    }
  };

  // Filtered commits
  const filteredCommits = useMemo(() => {
    return commits.filter((c) => {
      const q = searchQuery.toLowerCase();
      const matchesSearch =
        !q ||
        c.message.toLowerCase().includes(q) ||
        c.hash.toLowerCase().includes(q) ||
        c.author.toLowerCase().includes(q);

      let matchesType = true;
      if (selectedType !== 'all') {
        matchesType = c.message.toLowerCase().startsWith(selectedType.toLowerCase());
      }

      return matchesSearch && matchesType;
    });
  }, [commits, searchQuery, selectedType]);

  // Unique authors in these commits
  const uniqueAuthors = useMemo(() => {
    const set = new Set<string>();
    commits.forEach((c) => set.add(c.author));
    return Array.from(set);
  }, [commits]);

  return (
    <div className={`flex flex-col bg-[#101012] border border-white/[0.08] rounded-[10px] overflow-hidden ${className}`}>
      {/* Header bar */}
      <div className="p-3 sm:px-4 bg-[#141417] border-b border-white/[0.08] flex items-center justify-between gap-3 flex-wrap font-mono">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-[#FFB020]/10 border border-[#FFB020]/20 flex items-center justify-center text-[#FFB020]">
            <GitCommit className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[#F2F1EE]">Recent Commits Timeline</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.06] text-[#A8A8AB]">
                {commits.length}
              </span>
            </div>
            {repoName && (
              <div className="text-[10px] text-[#6B6B6E]">
                branch: <span className="text-[#FFB020]">{defaultBranch}</span> · {uniqueAuthors.length} active agent contributors
              </div>
            )}
          </div>
        </div>

        {/* Quick Filter Buttons / Search Toggle */}
        {showFilters && !compact && (
          <div className="flex items-center gap-1.5 text-[10px]">
            {['all', 'feat', 'fix', 'perf', 'sec', 'refactor'].map((type) => (
              <button
                key={type}
                onClick={() => setSelectedType(type)}
                className={`px-2 py-0.5 rounded border transition-colors cursor-pointer capitalize ${
                  selectedType === type
                    ? 'bg-[#FFB020]/15 text-[#FFB020] border-[#FFB020]/40 font-medium'
                    : 'bg-white/[0.02] text-[#6B6B6E] border-white/[0.04] hover:text-[#A8A8AB]'
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Search Bar if enabled */}
      {showSearch && !compact && commits.length > 3 && (
        <div className="p-2.5 bg-[#0C0C0E] border-b border-white/[0.06] flex items-center gap-2 text-xs font-mono">
          <div className="relative flex-1">
            <Search className="w-3 h-3 text-[#6B6B6E] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter commits by SHA, keyword, or author..."
              className="w-full pl-7 pr-3 py-1 bg-[#141417] border border-white/[0.06] rounded text-[11px] text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]/50"
            />
          </div>
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="text-[10px] text-[#6B6B6E] hover:text-[#A8A8AB] px-1 cursor-pointer"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Scrollable Timeline Stream */}
      <div className={`overflow-y-auto ${maxHeight} p-3 sm:p-4 space-y-0 relative font-mono text-xs custom-scrollbar`}>
        {filteredCommits.length > 0 ? (
          <div className="relative pl-5 sm:pl-6 space-y-3.5">
            {/* Continuous Vertical Timeline Line */}
            <div className="absolute left-2.5 sm:left-3 top-2 bottom-2 w-0.5 bg-gradient-to-b from-[#FFB020]/40 via-white/[0.12] to-transparent pointer-events-none" />

            {filteredCommits.map((commit, index) => {
              const isCopied = copiedHash === commit.hash;
              const isFirst = index === 0;

              return (
                <div
                  key={commit.hash}
                  onClick={() => onSelectCommit && onSelectCommit(commit)}
                  className={`group relative flex items-start gap-3 p-2.5 rounded-[8px] bg-[#141417]/80 hover:bg-[#18181C] border border-white/[0.06] hover:border-[#FFB020]/40 transition-all duration-150 ${
                    onSelectCommit ? 'cursor-pointer' : ''
                  }`}
                >
                  {/* Timeline Node Icon/Dot */}
                  <div className="absolute -left-5 sm:-left-6 top-3 flex items-center justify-center">
                    <div
                      className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center transition-all ${
                        isFirst
                          ? 'bg-[#FFB020] border-[#FFB020] ring-4 ring-[#FFB020]/20'
                          : 'bg-[#101012] border-white/[0.2] group-hover:border-[#FFB020]'
                      }`}
                    >
                      <div
                        className={`w-1 h-1 rounded-full ${
                          isFirst ? 'bg-[#101012]' : 'bg-[#A8A8AB] group-hover:bg-[#FFB020]'
                        }`}
                      />
                    </div>
                  </div>

                  {/* Author Avatar with Role Tooltip */}
                  <div className="shrink-0 mt-0.5">
                    <AuthorAvatar
                      name={commit.author}
                      avatarUrl={commit.author_avatar}
                      size="sm"
                      showTooltip={true}
                    />
                  </div>

                  {/* Commit Content */}
                  <div className="min-w-0 flex-1 space-y-1.5">
                    {/* Header Row: Author Name, Timestamp, SHA Hash */}
                    <div className="flex items-center justify-between gap-2 flex-wrap text-[11px]">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="font-semibold text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors truncate">
                          {commit.author}
                        </span>
                        <span className="text-[#6B6B6E]">·</span>
                        <span
                          title={formatFullDate(commit.timestamp)}
                          className="text-[#8E8E93] text-[10px] flex items-center gap-1 hover:text-[#F2F1EE] transition-colors cursor-help shrink-0"
                        >
                          <Clock className="w-2.5 h-2.5 text-[#6B6B6E]" />
                          {commit.relative_time}
                        </span>
                      </div>

                      {/* Commit SHA Badge with 1-click copy */}
                      <button
                        onClick={(e) => handleCopyHash(commit.hash, e)}
                        title={`Copy commit SHA: ${commit.hash}`}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-[10px] text-[#A8A8AB] hover:text-[#F2F1EE] transition-colors cursor-pointer group/sha"
                      >
                        <span className="font-mono text-[#FFB020]">{commit.hash.slice(0, 7)}</span>
                        {isCopied ? (
                          <Check className="w-2.5 h-2.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-2.5 h-2.5 text-[#6B6B6E] group-hover/sha:text-[#F2F1EE]" />
                        )}
                      </button>
                    </div>

                    {/* Commit Message with conventional tag formatting */}
                    <div className="text-xs">
                      {renderCommitMessage(commit.message)}
                    </div>

                    {/* Metadata Footer: Additions / Deletions + AST status */}
                    <div className="flex items-center justify-between pt-1 border-t border-white/[0.04] text-[10px] text-[#6B6B6E]">
                      <div className="flex items-center gap-2">
                        {commit.additions !== undefined && (
                          <div className="flex items-center gap-1 font-mono">
                            <span className="text-emerald-400 font-medium">+{commit.additions}</span>
                            <span className="text-rose-400 font-medium">-{commit.deletions}</span>
                            <span className="text-[#6B6B6E]">lines</span>
                          </div>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        {commit.ast_indexed && (
                          <span
                            title="Semantic AST symbol relations index synchronized"
                            className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded bg-[#38BDF8]/10 text-[#38BDF8] border border-[#38BDF8]/20 text-[9px]"
                          >
                            <Cpu className="w-2.5 h-2.5" />
                            <span>AST Indexed</span>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="py-8 text-center space-y-2">
            <Code2 className="w-6 h-6 text-[#6B6B6E] mx-auto opacity-50" />
            <div className="text-xs text-[#A8A8AB]">No commits matched the selected filters.</div>
            {searchQuery && (
              <button
                onClick={() => {
                  setSearchQuery('');
                  setSelectedType('all');
                }}
                className="text-[11px] text-[#FFB020] hover:underline cursor-pointer"
              >
                Reset Search Filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Footer Info Strip */}
      <div className="p-2 sm:px-4 bg-[#0E0E10] border-t border-white/[0.06] flex items-center justify-between text-[10px] font-mono text-[#6B6B6E]">
        <span>Showing {filteredCommits.length} of {commits.length} commits</span>
        <span className="text-[#38BDF8] flex items-center gap-1">
          <Cpu className="w-2.5 h-2.5" />
          <span>Real-time AST sync</span>
        </span>
      </div>
    </div>
  );
}
