import React, { useState } from 'react';
import {
  GitBranch,
  GitPullRequest,
  RefreshCw,
  ShieldCheck,
  Cpu,
  ArrowRight,
  Plus,
  Users,
  Lock,
  AlertOctagon,
} from 'lucide-react';
import type { GitRepoItem } from '@/types/gitRepo';
import { getLanguageColor } from './gitUtils';
import { AuthorAvatar } from './AuthorAvatar';

interface RepoListCardProps {
  repo: GitRepoItem;
  onSelect: (repo: GitRepoItem) => void;
  onSync: (repoId: string) => Promise<void>;
  onCreatePR: (repo: GitRepoItem) => void;
}

export function RepoListCard({ repo, onSelect, onSync, onCreatePR }: RepoListCardProps) {
  const [isSyncing, setIsSyncing] = useState(false);

  const handleSyncClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsSyncing(true);
    try {
      await onSync(repo.id);
    } finally {
      setIsSyncing(false);
    }
  };

  const latestCommit = repo.commits?.[0];
  const langColor = getLanguageColor(repo.language);

  return (
    <div
      onClick={() => onSelect(repo)}
      className="group relative bg-[#101012] hover:bg-[#141417] border border-white/[0.08] hover:border-[#FFB020]/40 rounded-[10px] p-4.5 transition-all duration-200 cursor-pointer shadow-lg hover:shadow-xl flex flex-col justify-between"
    >
      {/* Top Header */}
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors truncate font-mono">
                {repo.name}
              </span>
              {repo.visibility === 'private' && (
                <span title="Private Repository">
                  <Lock className="w-3 h-3 text-[#6B6B6E] shrink-0" />
                </span>
              )}
            </div>
            {repo.description && (
              <p className="text-xs text-[#A8A8AB] mt-1 line-clamp-2 leading-relaxed">
                {repo.description}
              </p>
            )}
          </div>

          {/* Sync Button & PR Badge */}
          <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={handleSyncClick}
              disabled={isSyncing}
              title="Synchronize AST index and commits"
              className="p-1.5 rounded-[6px] bg-white/[0.04] hover:bg-white/[0.08] text-[#A8A8AB] hover:text-[#F2F1EE] border border-white/[0.06] transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin text-[#FFB020]' : ''}`} />
            </button>
            {repo.open_prs_count > 0 ? (
              <span
                title={`${repo.open_prs_count} open PR${repo.open_prs_count !== 1 ? 's' : ''}${
                  repo.prs?.some((p) => p.checks === 'failed') ? ' · 1+ CI Check Failed' : ''
                }`}
                className={`font-mono text-[10px] px-2 py-0.5 rounded-[5px] border flex items-center font-medium ${
                  repo.prs?.some((p) => p.checks === 'failed')
                    ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                    : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                }`}
              >
                {repo.prs?.some((p) => p.checks === 'failed') ? (
                  <AlertOctagon className="w-3 h-3 mr-1 text-rose-400" />
                ) : (
                  <GitPullRequest className="w-3 h-3 mr-1 text-emerald-400" />
                )}
                {repo.open_prs_count} PR{repo.open_prs_count !== 1 ? 's' : ''}
              </span>
            ) : (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.04] text-[#6B6B6E] border border-white/[0.04]">
                0 PRs
              </span>
            )}
          </div>
        </div>

        {/* Metadata Badges Bar */}
        <div className="flex flex-wrap items-center gap-2 mt-3 pt-2.5 border-t border-white/[0.04] text-xs font-mono text-[#6B6B6E]">
          {/* Language indicator */}
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: langColor }} />
            <span className="text-[#A8A8AB]">{repo.language}</span>
          </div>

          <span>·</span>

          {/* Default Branch */}
          <div className="flex items-center gap-1 text-[#A8A8AB]">
            <GitBranch className="w-3 h-3 text-[#6B6B6E]" />
            <span>{repo.default_branch}</span>
          </div>

          <span>·</span>

          {/* AST Index Coverage */}
          <div className="flex items-center gap-1" title="Semantic Abstract Syntax Tree Coverage">
            <Cpu className="w-3 h-3 text-[#38BDF8]" />
            <span className="text-[#38BDF8]">{repo.ast_index_coverage}% AST</span>
          </div>

          <span>·</span>

          {/* Security Score */}
          <div className="flex items-center gap-1" title="Static Vulnerability Gate Score">
            <ShieldCheck className="w-3 h-3 text-[#22C55E]" />
            <span className="text-[#22C55E]">{repo.security_score}% Gate</span>
          </div>
        </div>

        {/* Latest Commit Box */}
        {latestCommit && (
          <div className="mt-3 p-2.5 bg-[#0A0A0C] border border-white/[0.06] rounded-[6px] text-xs font-mono text-[#A8A8AB] flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <AuthorAvatar name={latestCommit.author} avatarUrl={latestCommit.author_avatar} size="xs" />
              <span className="text-[11px] text-[#FFB020] bg-white/[0.04] px-1 py-0.5 rounded shrink-0">
                {latestCommit.hash.slice(0, 7)}
              </span>
              <span className="truncate text-[#F2F1EE] text-[11px]">{latestCommit.message}</span>
            </div>
            <span className="text-[10px] text-[#6B6B6E] shrink-0">{latestCommit.relative_time}</span>
          </div>
        )}
      </div>

      {/* Footer: Assigned Squad & Quick Actions */}
      <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 min-w-0">
          <Users className="w-3.5 h-3.5 text-[#6B6B6E] shrink-0" />
          <div className="flex items-center gap-1 flex-wrap">
            {repo.assigned_agents?.slice(0, 3).map((agent) => (
              <span
                key={agent}
                className="flex items-center gap-1 pl-1 pr-1.5 py-0.5 rounded bg-white/[0.04] border border-white/[0.06] text-[10px] font-mono text-[#A8A8AB]"
              >
                <AuthorAvatar name={agent} size="xs" />
                <span>{agent}</span>
              </span>
            ))}
            {(repo.assigned_agents?.length || 0) > 3 && (
              <span className="text-[10px] font-mono text-[#6B6B6E]">
                +{(repo.assigned_agents?.length || 0) - 3}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => onCreatePR(repo)}
            className="px-2 py-1 bg-white/[0.04] hover:bg-[#FFB020]/15 text-[#A8A8AB] hover:text-[#FFB020] hover:border-[#FFB020]/40 rounded-[5px] border border-white/[0.08] text-[11px] font-mono flex items-center gap-1 transition-colors cursor-pointer"
          >
            <Plus className="w-3 h-3" />
            <span>Agent PR</span>
          </button>

          <button
            onClick={() => onSelect(repo)}
            className="p-1 text-[#6B6B6E] group-hover:text-[#FFB020] transition-colors cursor-pointer"
            title="Inspect repository workspace"
          >
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
