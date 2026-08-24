import { apiClient, unwrapItems } from '@/api/client';
import { Button } from '@/components/common/Button';
import { StatCard } from '@/components/common/StatCard';
import { FileExplorer } from '@/components/files/FileExplorer';
import { AllCommitsList } from '@/components/git/AllCommitsList';
import { AllPRsList } from '@/components/git/AllPRsList';
import { DiffViewer } from '@/components/git/DiffViewer';
import { GitHubConnectorModal } from '@/components/git/GitHubConnectorModal';
import { NewPRModal } from '@/components/git/NewPRModal';
import { NewRepoModal } from '@/components/git/NewRepoModal';
import { PRDiffModal } from '@/components/git/PRDiffModal';
import { RepoDetailDrawer } from '@/components/git/RepoDetailDrawer';
import { RepoListCard } from '@/components/git/RepoListCard';
import { getActiveCompanyId } from '@/config';
import type { GitProvider, GitRepoItem, GitPullRequest as IGitPullRequest } from '@/types/gitRepo';
import {
  CheckCircle2,
  Cpu,
  FolderGit2,
  GitCommit,
  Github,
  GitPullRequest,
  Plus,
  RefreshCw,
  Search,
  Zap,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

export function GitRepos() {
  const [repos, setRepos] = useState<GitRepoItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'repositories' | 'prs' | 'commits'>('repositories');
  const [search, setSearch] = useState('');
  const [selectedLanguage, setSelectedLanguage] = useState<string>('all');
  const [selectedProvider, setSelectedProvider] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'recent' | 'prs' | 'commits' | 'name'>('recent');

  // Modals & Drawers state
  const [selectedRepo, setSelectedRepo] = useState<GitRepoItem | null>(null);
  const [isNewRepoModalOpen, setIsNewRepoModalOpen] = useState(false);
  const [isGitHubModalOpen, setIsGitHubModalOpen] = useState(false);
  const [isNewPRModalOpen, setIsNewPRModalOpen] = useState(false);
  const [repoForNewPR, setRepoForNewPR] = useState<GitRepoItem | null>(null);
  const [activeDiffPR, setActiveDiffPR] = useState<IGitPullRequest | null>(null);
  const [diffRepo, setDiffRepo] = useState<GitRepoItem | null>(null);
  const [isSyncingAll, setIsSyncingAll] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const loadRepos = async () => {
    try {
      setIsLoading(true);
      const res = await apiClient.get<GitRepoItem[] | { items: GitRepoItem[] }>(
        `/api/v1/companies/${getActiveCompanyId()}/repos`
      );
      const repoItems = unwrapItems(res);
      if (repoItems.length) {
        setRepos(repoItems);
        // Refresh selectedRepo if currently open
        if (selectedRepo) {
          const updated = repoItems.find((r) => r.id === selectedRepo.id);
          if (updated) setSelectedRepo(updated);
        }
      }
    } catch (err) {
      console.error('Failed to load git repos', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadRepos();
  }, []);

  // Sync single repository
  const handleSyncRepo = async (repoId: string) => {
    try {
      const res = await apiClient.post<{ message: string; repo: GitRepoItem }>(
        `/api/v1/companies/${getActiveCompanyId()}/repos/${repoId}/sync`
      );
      if (res?.repo) {
        setRepos((prev) => prev.map((r) => (r.id === repoId ? res.repo : r)));
        if (selectedRepo?.id === repoId) setSelectedRepo(res.repo);
        showToast(res.message || 'AST Index & commits synchronized');
      }
    } catch (err) {
      console.error('Failed to sync repo', err);
      showToast('Failed to sync repository');
    }
  };

  // Sync all repositories
  const handleSyncAll = async () => {
    setIsSyncingAll(true);
    try {
      for (const repo of repos) {
        await apiClient.post(
          `/api/v1/companies/${getActiveCompanyId()}/repos/${repo.id}/sync`
        );
      }
      await loadRepos();
      showToast('All repositories and AST indices synchronized');
    } catch (err) {
      console.error('Failed to sync all repos', err);
    } finally {
      setIsSyncingAll(false);
    }
  };

  // Connect new repository
  const handleConnectRepo = async (data: {
    name: string;
    description: string;
    provider: GitProvider;
    visibility: 'private' | 'public' | 'internal';
    default_branch: string;
    language: string;
    assigned_agents: string[];
    auto_review_enabled: boolean;
  }) => {
    try {
      const created = await apiClient.post<GitRepoItem>(
        `/api/v1/companies/${getActiveCompanyId()}/repos`,
        data
      );
      if (created) {
        setRepos((prev) => [created, ...prev]);
        showToast(`Repository ${created.name} mounted successfully`);
      }
    } catch (err) {
      console.error('Failed to connect repo', err);
      showToast('Failed to connect repository');
    }
  };

  // Unmount / Delete repository
  const handleDeleteRepo = async (repoId: string) => {
    try {
      await apiClient.delete(
        `/api/v1/companies/${getActiveCompanyId()}/repos/${repoId}`
      );
      setRepos((prev) => prev.filter((r) => r.id !== repoId));
      if (selectedRepo?.id === repoId) setSelectedRepo(null);
      showToast('Repository unmounted');
    } catch (err) {
      console.error('Failed to delete repo', err);
    }
  };

  // Create PR
  const handleCreatePR = async (
    repoId: string,
    data: {
      title: string;
      description: string;
      author: string;
      source_branch: string;
      target_branch: string;
      diff_preview?: string;
    }
  ) => {
    try {
      const createdPR = await apiClient.post<IGitPullRequest>(
        `/api/v1/companies/${getActiveCompanyId()}/repos/${repoId}/prs`,
        data
      );
      await loadRepos();
      showToast(`PR #${createdPR.number} drafted by ${data.author}`);
    } catch (err) {
      console.error('Failed to create PR', err);
      showToast('Failed to draft Pull Request');
    }
  };

  // Merge PR
  const handleMergePR = async (repoId: string, prId: string) => {
    try {
      const res = await apiClient.post<{ message: string; pr: IGitPullRequest; repo: GitRepoItem }>(
        `/api/v1/companies/${getActiveCompanyId()}/repos/${repoId}/prs/${prId}/merge`
      );
      await loadRepos();
      if (activeDiffPR?.id === prId && res.pr) {
        setActiveDiffPR(res.pr);
      }
      showToast(res.message || 'Pull Request successfully merged');
    } catch (err) {
      console.error('Failed to merge PR', err);
      showToast('Failed to merge Pull Request');
    }
  };

  // Close PR
  const handleClosePR = async (repoId: string, prId: string) => {
    try {
      const res = await apiClient.post<{ message: string; pr: IGitPullRequest }>(
        `/api/v1/companies/${getActiveCompanyId()}/repos/${repoId}/prs/${prId}/close`
      );
      await loadRepos();
      if (activeDiffPR?.id === prId && res.pr) {
        setActiveDiffPR(res.pr);
      }
      showToast(res.message || 'Pull Request closed');
    } catch (err) {
      console.error('Failed to close PR', err);
    }
  };

  // Trigger agent review on PR
  const handleTriggerReview = async (repoId: string, prId: string, reviewerAgent = 'Shield-07') => {
    try {
      const res = await apiClient.post<{ message: string; pr: IGitPullRequest }>(
        `/api/v1/companies/${getActiveCompanyId()}/repos/${repoId}/prs/${prId}/review`,
        { reviewer: reviewerAgent }
      );
      await loadRepos();
      if (activeDiffPR?.id === prId && res.pr) {
        setActiveDiffPR(res.pr);
      }
      showToast(res.message || 'Automated code review completed');
    } catch (err) {
      console.error('Failed to review PR', err);
    }
  };

  // Open PR Modal for specific or default repo
  const openNewPRForRepo = (repo?: GitRepoItem) => {
    setRepoForNewPR(repo || repos[0] || null);
    setIsNewPRModalOpen(true);
  };

  // Open PR Diff
  const openPRDiffModal = (pr: IGitPullRequest, repo: GitRepoItem) => {
    setActiveDiffPR(pr);
    setDiffRepo(repo);
  };

  // Filter and Sort Repos
  const filteredAndSortedRepos = useMemo(() => {
    let result = repos.filter((r) => {
      const q = search.toLowerCase();
      const matchesSearch =
        !q ||
        r.name.toLowerCase().includes(q) ||
        r.description?.toLowerCase().includes(q) ||
        r.language.toLowerCase().includes(q) ||
        r.assigned_agents?.some((a) => a.toLowerCase().includes(q));

      const matchesLang =
        selectedLanguage === 'all' ||
        r.language.toLowerCase() === selectedLanguage.toLowerCase();

      const matchesProvider =
        selectedProvider === 'all' ||
        r.provider.toLowerCase() === selectedProvider.toLowerCase();

      return matchesSearch && matchesLang && matchesProvider;
    });

    result.sort((a, b) => {
      if (sortBy === 'prs') return (b.open_prs_count || 0) - (a.open_prs_count || 0);
      if (sortBy === 'commits') return (b.total_commits_7d || 0) - (a.total_commits_7d || 0);
      if (sortBy === 'name') return a.name.localeCompare(b.name);
      // default: recent sync
      return new Date(b.last_sync_at || 0).getTime() - new Date(a.last_sync_at || 0).getTime();
    });

    return result;
  }, [repos, search, selectedLanguage, selectedProvider, sortBy]);

  // Aggregate Stats
  const totalPRs = useMemo(() => {
    return repos.reduce((sum, r) => sum + ((r.prs || []).length), 0);
  }, [repos]);
  const openPRsCount = useMemo(() => {
    return repos.reduce((sum, r) => sum + ((r.prs || []).filter((p) => p.status === 'open').length), 0);
  }, [repos]);
  const totalCommitsCount = useMemo(() => {
    return repos.reduce((sum, r) => sum + ((r.commits || []).length), 0);
  }, [repos]);

  const avgAstCoverage = useMemo(() => {
    if (!repos.length) return 0;
    const sum = repos.reduce((s, r) => s + (r.ast_index_coverage || 0), 0);
    return Math.round(sum / repos.length);
  }, [repos]);
  const totalCommits7d = useMemo(() => repos.reduce((sum, r) => sum + (r.total_commits_7d || 0), 0), [repos]);
  const languagesList = useMemo(() => Array.from(new Set(repos.map((r) => r.language))), [repos]);

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 p-3.5 bg-[#18181C] border border-[#FFB020]/40 rounded-[8px] shadow-2xl text-xs font-mono text-[#F2F1EE] flex items-center gap-2.5 animate-in slide-in-from-bottom duration-150">
          <CheckCircle2 className="w-4 h-4 text-[#FFB020] shrink-0" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-[8px] bg-[#FFB020]/10 border border-[#FFB020]/20 text-[#FFB020]">
              <FolderGit2 className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
                Source Repositories & Agent PRs
              </h1>
              <p className="text-xs font-mono text-[#6B6B6E] mt-0.5">
                Mounted codebases, AST semantic dependency graphs, pull requests & autonomous commit logs
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsGitHubModalOpen(true)}
            icon={<Github className="w-3.5 h-3.5 text-[#FFB020]" />}
          >
            Connect GitHub API
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={handleSyncAll}
            disabled={isSyncingAll}
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isSyncingAll ? 'animate-spin text-[#FFB020]' : ''}`} />
            {isSyncingAll ? 'Syncing...' : 'Sync All AST'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => openNewPRForRepo()}
          >
            <Zap className="w-3.5 h-3.5 mr-1 text-[#FFB020]" />
            Dispatch PR
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsNewRepoModalOpen(true)}
          >
            <Plus className="w-3.5 h-3.5 mr-1" />
            Mount Repository
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Tracked Repositories"
          value={repos.length}
          subValue={`${languagesList.length} Languages`}
          change="AST Parser Active"
          changeType="positive"
          icon={<FolderGit2 className="w-4 h-4" />}
        />
        <StatCard
          label="Agent Pull Requests"
          value={`${openPRsCount} Open (${totalPRs} Total)`}
          subValue="Awaiting Review / Merge"
          change="Automated CI Passing"
          changeType="positive"
          icon={<GitPullRequest className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="AST Index Coverage"
          value={`${avgAstCoverage}%`}
          subValue="Semantic Symbol Resolution"
          change="100% Graph Linkage"
          changeType="positive"
          icon={<Cpu className="w-4 h-4 text-[#38BDF8]" />}
        />
        <StatCard
          label="Workspace Commits"
          value={`${totalCommitsCount} Commits`}
          subValue={`${totalCommits7d} in past 7 days`}
          change="Zero Regressions"
          changeType="positive"
          icon={<GitCommit className="w-4 h-4 text-[#22C55E]" />}
        />
      </div>

      {/* Main View Navigation Tabs */}
      <div className="flex items-center gap-1 border-b border-white/[0.08] text-xs font-mono">
        <button
          onClick={() => setActiveTab('repositories')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 font-medium transition-all cursor-pointer ${activeTab === 'repositories'
            ? 'border-[#FFB020] text-[#FFB020] bg-white/[0.02]'
            : 'border-transparent text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.01]'
            }`}
        >
          <FolderGit2 className="w-4 h-4" />
          <span>Repositories</span>
          <span className="px-1.5 py-0.2 rounded bg-white/[0.06] text-[10px] text-[#A8A8AB]">
            {repos.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('prs')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 font-medium transition-all cursor-pointer ${activeTab === 'prs'
            ? 'border-[#FFB020] text-[#FFB020] bg-white/[0.02]'
            : 'border-transparent text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.01]'
            }`}
        >
          <GitPullRequest className="w-4 h-4" />
          <span>Pull Requests</span>
          <span className="px-1.5 py-0.2 rounded bg-[#22C55E]/20 text-[10px] text-[#22C55E] font-medium">
            {openPRsCount} open
          </span>
          <span className="px-1.5 py-0.2 rounded bg-white/[0.06] text-[10px] text-[#A8A8AB]">
            {totalPRs}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('commits')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 font-medium transition-all cursor-pointer ${activeTab === 'commits'
            ? 'border-[#FFB020] text-[#FFB020] bg-white/[0.02]'
            : 'border-transparent text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.01]'
            }`}
        >
          <GitCommit className="w-4 h-4" />
          <span>All Commits</span>
          <span className="px-1.5 py-0.2 rounded bg-white/[0.06] text-[10px] text-[#A8A8AB]">
            {totalCommitsCount}
          </span>
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'repositories' && (
        <div className="space-y-4">
          {/* Search, Filter & Sorting Bar for Repos */}
          <div className="bg-[#101012] p-3 border border-white/[0.08] rounded-[10px] flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 text-xs font-mono">
            <div className="flex-1 flex items-center gap-2 max-w-md">
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search by repo name, agent, or language..."
                  className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
                />
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {/* Language filter */}
              <select
                value={selectedLanguage}
                onChange={(e) => setSelectedLanguage(e.target.value)}
                className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
              >
                <option value="all">All Languages</option>
                {languagesList.map((lang) => (
                  <option key={lang} value={lang}>
                    {lang}
                  </option>
                ))}
              </select>

              {/* Provider filter */}
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
              >
                <option value="all">All Providers</option>
                <option value="github">GitHub</option>
                <option value="gitlab">GitLab</option>
                <option value="bitbucket">Bitbucket</option>
                <option value="internal">Monorepo</option>
              </select>

              {/* Sort By */}
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
                className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#A8A8AB] focus:outline-none focus:border-[#FFB020] cursor-pointer"
              >
                <option value="recent">Sort: Recently Synced</option>
                <option value="prs">Sort: Open PRs</option>
                <option value="commits">Sort: Most Commits</option>
                <option value="name">Sort: Name (A-Z)</option>
              </select>
            </div>
          </div>

          {/* Repositories Grid */}
          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[1, 2, 3].map((n) => (
                <div
                  key={n}
                  className="bg-[#101012] border border-white/[0.06] rounded-[10px] p-5 h-44 animate-pulse space-y-3"
                >
                  <div className="h-4 bg-white/[0.06] rounded w-3/4" />
                  <div className="h-3 bg-white/[0.04] rounded w-full" />
                  <div className="h-3 bg-white/[0.04] rounded w-1/2" />
                </div>
              ))}
            </div>
          ) : filteredAndSortedRepos.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredAndSortedRepos.map((repo) => (
                <RepoListCard
                  key={repo.id}
                  repo={repo}
                  onSelect={(r) => setSelectedRepo(r)}
                  onSync={handleSyncRepo}
                  onCreatePR={openNewPRForRepo}
                />
              ))}
            </div>
          ) : (
            <div className="text-center py-12 px-6 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4 font-mono max-w-2xl mx-auto my-4">
              <div className="w-12 h-12 rounded-full bg-[#FFB020]/10 border border-[#FFB020]/20 flex items-center justify-center mx-auto text-[#FFB020]">
                <Github size={24} />
              </div>
              <div>
                <h3 className="text-base font-medium text-[#F2F1EE]">
                  {repos.length === 0 ? 'No Repositories Connected Yet' : 'No repositories match your filter'}
                </h3>
                <p className="text-xs text-[#9C9C9F] leading-relaxed max-w-md mx-auto mt-1">
                  {repos.length === 0
                    ? 'Connect your GitHub Personal Access Token (PAT) using the GitHub API Connector to import real repositories, view live commit streams, and create Pull Requests on GitHub.'
                    : 'Try adjusting your search query or language filter.'}
                </p>
              </div>

              <div className="pt-1 flex items-center justify-center gap-3">
                {repos.length === 0 ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setIsGitHubModalOpen(true)}
                    icon={<Github size={14} />}
                  >
                    Connect GitHub API Connector
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setSearch('');
                      setSelectedLanguage('all');
                      setSelectedProvider('all');
                    }}
                  >
                    Clear Filters
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Pull Requests Tab */}
      {activeTab === 'prs' && (
        <AllPRsList
          repos={repos}
          onOpenDiff={openPRDiffModal}
          onMergePR={handleMergePR}
          onTriggerReview={handleTriggerReview}
          onSelectRepo={(r) => setSelectedRepo(r)}
          onCreatePRClick={() => openNewPRForRepo()}
        />
      )}

      {/* Commits Tab */}
      {activeTab === 'commits' && (
        <AllCommitsList
          repos={repos}
          onSelectRepo={(r) => setSelectedRepo(r)}
        />
      )}

      {/* File Explorer & Diff Viewer (shown when repo selected) */}
      {selectedRepo && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <FileExplorer repoId={selectedRepo.id} onFileSelect={(path) => console.log('Selected:', path)} />
          <DiffViewer repoId={selectedRepo.id} />
        </div>
      )}

      {/* Selected Repo Inspector Drawer */}
      <RepoDetailDrawer
        repo={selectedRepo}
        onClose={() => setSelectedRepo(null)}
        onSync={handleSyncRepo}
        onCreatePR={openNewPRForRepo}
        onOpenPRDiff={openPRDiffModal}
        onMergePR={handleMergePR}
        onTriggerReview={handleTriggerReview}
        onDeleteRepo={handleDeleteRepo}
      />

      {/* Mount New Repository Modal */}
      <NewRepoModal
        isOpen={isNewRepoModalOpen}
        onClose={() => setIsNewRepoModalOpen(false)}
        onSubmitRepo={handleConnectRepo}
      />

      {/* Dispatch Agent PR Modal */}
      <NewPRModal
        isOpen={isNewPRModalOpen}
        onClose={() => {
          setIsNewPRModalOpen(false);
          setRepoForNewPR(null);
        }}
        repo={repoForNewPR}
        onSubmitPR={handleCreatePR}
      />

      {/* Real GitHub Connector Modal */}
      <GitHubConnectorModal
        isOpen={isGitHubModalOpen}
        onClose={() => setIsGitHubModalOpen(false)}
        onRepoImported={loadRepos}
      />

      {/* PR Diff & Review Modal */}
      <PRDiffModal
        isOpen={!!activeDiffPR}
        onClose={() => {
          setActiveDiffPR(null);
          setDiffRepo(null);
        }}
        pr={activeDiffPR}
        repo={diffRepo || selectedRepo}
        onMerge={handleMergePR}
        onClosePR={handleClosePR}
        onTriggerReview={handleTriggerReview}
      />
    </div>
  );
}
export default GitRepos;

