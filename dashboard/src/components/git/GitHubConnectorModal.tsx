import { useState, useEffect } from 'react';
import {
  X,
  Github,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Download,
  Key,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';

interface GitHubUser {
  login: string;
  name?: string;
  avatar_url?: string;
  html_url?: string;
  public_repos?: number;
}

interface GitHubRemoteRepo {
  id: string;
  name: string; // e.g. owner/repo
  description?: string;
  visibility: string;
  default_branch: string;
  language?: string;
  stars?: number;
  html_url?: string;
}

interface GitHubConnectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRepoImported?: () => void;
}

export function GitHubConnectorModal({ isOpen, onClose, onRepoImported }: GitHubConnectorModalProps) {
  const [tokenInput, setTokenInput] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [remoteRepos, setRemoteRepos] = useState<GitHubRemoteRepo[]>([]);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isLoadingRepos, setIsLoadingRepos] = useState(false);
  const [importingRepo, setImportingRepo] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Check connection status on open
  useEffect(() => {
    if (!isOpen) return;
    async function checkStatus() {
      try {
        const res = await apiClient.get<{ authenticated: boolean; user: GitHubUser | null }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/github/status'
        );
        if (res?.authenticated && res.user) {
          setIsConnected(true);
          setUser(res.user);
          loadRemoteRepos();
        } else {
          // Attempt auto-connect from saved localStorage PAT
          const savedPat = localStorage.getItem('nexus_github_pat');
          if (savedPat) {
            connectWithToken(savedPat);
          }
        }
      } catch {
        const savedPat = localStorage.getItem('nexus_github_pat');
        if (savedPat) {
          connectWithToken(savedPat);
        }
      }
    }
    checkStatus();
  }, [isOpen]);

  const loadRemoteRepos = async () => {
    setIsLoadingRepos(true);
    try {
      const res = await apiClient.get<{ items: GitHubRemoteRepo[] }>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/github/user-repos'
      );
      if (res?.items) {
        setRemoteRepos(res.items);
      }
    } catch {
      // Ignore
    } finally {
      setIsLoadingRepos(false);
    }
  };

  const connectWithToken = async (pat: string) => {
    setIsVerifying(true);
    setStatusMessage(null);
    try {
      const res = await apiClient.post<{ authenticated: boolean; user: GitHubUser; message: string }>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/github/connect',
        { token: pat }
      );
      if (res?.authenticated) {
        setIsConnected(true);
        setUser(res.user);
        localStorage.setItem('nexus_github_pat', pat);
        setStatusMessage({ type: 'success', text: res.message || `Connected as @${res.user.login}` });
        setTokenInput('');
        loadRemoteRepos();
      }
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: err?.detail || 'GitHub token authentication failed' });
    } finally {
      setIsVerifying(false);
    }
  };

  const handleConnectToken = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tokenInput.trim()) return;
    await connectWithToken(tokenInput.trim());
  };

  const handleImportRemoteRepo = async (repo: GitHubRemoteRepo) => {
    setImportingRepo(repo.name);
    try {
      await apiClient.post(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/github/import',
        { full_name: repo.name, default_branch: repo.default_branch }
      );
      setStatusMessage({ type: 'success', text: `Imported repository ${repo.name}!` });
      if (onRepoImported) onRepoImported();
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: err?.detail || 'Failed to import remote repository' });
    } finally {
      setImportingRepo(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-150 font-mono">
      <div className="bg-[#101012] border border-white/[0.12] rounded-[12px] w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-white/[0.08] bg-[#141417] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-[6px] bg-[#FFB020]/10 border border-[#FFB020]/20 flex items-center justify-center text-[#FFB020]">
              <Github size={18} />
            </div>
            <div>
              <h2 className="text-base font-display font-medium text-white tracking-tight">
                Real GitHub API Connector
              </h2>
              <p className="text-xs text-[#6B6B6E]">
                Connect GitHub PAT to access repos, commits, and open real Pull Requests
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-[#6B6B6E] hover:text-white rounded transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 overflow-y-auto space-y-5 flex-1 text-xs">
          {/* Feedback Banner */}
          {statusMessage && (
            <div
              className={`p-3 rounded-[6px] border flex items-center gap-2 ${
                statusMessage.type === 'success'
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
              }`}
            >
              {statusMessage.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
              <span>{statusMessage.text}</span>
            </div>
          )}

          {/* Connection Status Card */}
          {isConnected && user ? (
            <div className="p-4 bg-[#141416] border border-emerald-500/30 rounded-[8px] flex items-center justify-between">
              <div className="flex items-center gap-3">
                {user.avatar_url ? (
                  <img src={user.avatar_url} alt={user.login} className="w-10 h-10 rounded-full border border-white/[0.12]" />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold">
                    {user.login.slice(0, 2).toUpperCase()}
                  </div>
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-white">@{user.login}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">
                      AUTHENTICATED
                    </span>
                  </div>
                  <span className="text-[11px] text-gray-400">
                    {user.public_repos || 0} public repositories accessible
                  </span>
                </div>
              </div>

              {user.html_url && (
                <a
                  href={user.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-gray-400 hover:text-white flex items-center gap-1 text-[11px]"
                >
                  GitHub Profile <ExternalLink size={12} />
                </a>
              )}
            </div>
          ) : (
            /* PAT Connection Form */
            <form onSubmit={handleConnectToken} className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-3">
              <div className="flex items-center gap-2 text-amber-400 text-xs font-bold">
                <Key size={14} />
                Enter GitHub Personal Access Token (PAT)
              </div>
              <p className="text-[11px] text-gray-400">
                Provide a token with <code className="text-[#FFB020] bg-black/40 px-1 py-0.5 rounded">repo</code> scope from GitHub Settings &gt; Developer settings &gt; Personal access tokens.
              </p>

              <div className="space-y-1">
                <input
                  type="password"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                  className="w-full px-3 py-2 bg-[#0A0A0C] border border-white/[0.12] rounded text-xs text-white placeholder-gray-600 focus:outline-none focus:border-[#FFB020]"
                  required
                />
              </div>

              <div className="flex justify-end pt-1">
                <Button variant="primary" size="sm" type="submit" disabled={isVerifying}>
                  {isVerifying ? 'Authenticating...' : 'Authenticate & Save Token'}
                </Button>
              </div>
            </form>
          )}

          {/* Remote Repositories Ingest Section */}
          {isConnected && (
            <div className="space-y-3 pt-3 border-t border-white/[0.08]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-white uppercase tracking-wider">
                  Remote GitHub Repositories
                </span>
                <button
                  onClick={loadRemoteRepos}
                  className="text-[11px] text-[#FFB020] hover:underline"
                  disabled={isLoadingRepos}
                >
                  {isLoadingRepos ? 'Refreshing...' : 'Refresh Repos'}
                </button>
              </div>

              {isLoadingRepos ? (
                <div className="p-6 text-center text-gray-500">Loading GitHub repositories...</div>
              ) : remoteRepos.length === 0 ? (
                <div className="p-6 text-center text-gray-500 bg-[#141416] rounded border border-white/[0.06]">
                  No remote repositories found
                </div>
              ) : (
                <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                  {remoteRepos.map((r) => (
                    <div
                      key={r.id}
                      className="p-3 bg-[#141416] border border-white/[0.06] rounded-[6px] flex items-center justify-between hover:border-white/[0.15] transition-colors"
                    >
                      <div>
                        <div className="font-bold text-white text-xs">{r.name}</div>
                        <div className="text-[10px] text-gray-500 mt-0.5">
                          Branch: {r.default_branch} · {r.language || 'Code'}
                        </div>
                      </div>

                      <Button
                        variant="secondary"
                        size="xs"
                        icon={<Download size={12} />}
                        onClick={() => handleImportRemoteRepo(r)}
                        disabled={importingRepo === r.name}
                      >
                        {importingRepo === r.name ? 'Importing...' : 'Import Repo'}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.08] bg-[#141417] flex justify-end">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
