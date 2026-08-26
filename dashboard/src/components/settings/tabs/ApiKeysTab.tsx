import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { getActiveCompanyId } from '@/config';
import { Bot, Check, Copy, Eye, Key, Plus, Shield, ShieldAlert, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

interface ApiKeyData {
  id: string;
  company_id: string;
  name: string;
  description: string | null;
  key_prefix: string;
  environment: string;
  status: string;
  role: string;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
  full_key?: string;
}

interface ApiKeysTabProps {
  onSaveToast: (msg?: string) => void;
}

const ROLES = [
  { value: 'admin', label: 'Admin', desc: 'Full access — create/delete agents, manage keys, all operations', icon: ShieldAlert, color: 'text-rose-400' },
  { value: 'manager', label: 'Manager', desc: 'Manage agents, tasks, pipelines — cannot manage API keys', icon: Shield, color: 'text-amber-400' },
  { value: 'agent', label: 'Agent / Service', desc: 'Execute tasks, chat, read data — cannot modify settings', icon: Bot, color: 'text-blue-400' },
  { value: 'viewer', label: 'Viewer (Read-only)', desc: 'Read-only access to all endpoints — no mutations', icon: Eye, color: 'text-gray-400' },
];

const ENVIRONMENTS = ['production', 'staging', 'development', 'ci-cd'];

export function ApiKeysTab({ onSaveToast }: ApiKeysTabProps) {
  const [apiKeys, setApiKeys] = useState<ApiKeyData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyRole, setNewKeyRole] = useState('viewer');
  const [newKeyEnv, setNewKeyEnv] = useState('production');
  const [newKeyDescription, setNewKeyDescription] = useState('');
  const [newKeyExpiresDays, setNewKeyExpiresDays] = useState<number | null>(365);
  const [creating, setCreating] = useState(false);

  // Created key display
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const companyId = getActiveCompanyId();

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<ApiKeyData[]>(`/api/v1/companies/${companyId}/api-keys`);
      setApiKeys(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      setError('Failed to load API keys. Ensure you have admin permissions.');
      setApiKeys([]);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    setCreating(true);
    setError(null);

    try {
      const body: Record<string, unknown> = {
        name: newKeyName.trim(),
        role: newKeyRole,
        environment: newKeyEnv,
        description: newKeyDescription.trim() || null,
      };
      if (newKeyExpiresDays) {
        body.expires_in_days = newKeyExpiresDays;
      }

      const result = await apiClient.post<ApiKeyData>(`/api/v1/companies/${companyId}/api-keys`, body);
      setCreatedSecret(result.full_key || null);
      setApiKeys([result, ...apiKeys]);
      setNewKeyName('');
      setNewKeyDescription('');
      onSaveToast(`API Key '${result.name}' created with ${newKeyRole} role`);
    } catch (err: any) {
      const detail = err?.body?.detail || err?.message || 'Failed to create API key';
      setError(detail);
    } finally {
      setCreating(false);
    }
  };

  const handleRevokeKey = async (keyId: string) => {
    try {
      await apiClient.post(`/api/v1/api-keys/${keyId}/revoke`, {});
      setApiKeys(apiKeys.map((k) => k.id === keyId ? { ...k, status: 'revoked' } : k));
      onSaveToast('API Key revoked');
    } catch {
      setError('Failed to revoke key');
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    try {
      await apiClient.delete(`/api/v1/api-keys/${keyId}`);
      setApiKeys(apiKeys.filter((k) => k.id !== keyId));
      onSaveToast('API Key deleted permanently');
    } catch {
      setError('Failed to delete key');
    }
  };

  const handleCopySecret = () => {
    if (createdSecret) {
      navigator.clipboard.writeText(createdSecret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const defaultRole = ROLES[3]!;
  const getRoleInfo = (role: string) => {
    for (const r of ROLES) if (r.value === role) return r;
    return defaultRole;
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Key size={18} className="text-[#FFB020]" />
            API Access Keys & Service Accounts
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Manage bearer tokens for CI/CD, agent sidecars, service integrations, and external tools.
            Keys authenticate as a specific role within this company.
          </p>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400 text-xs">
          {error}
        </div>
      )}

      {/* Create Key Form */}
      <form onSubmit={handleCreateKey} className="p-5 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase font-bold">
          Generate New API Key
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Name */}
          <div>
            <label className="block text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Key Name *</label>
            <input
              type="text"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder="e.g. Production CI/CD Runner"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Description</label>
            <input
              type="text"
              value={newKeyDescription}
              onChange={(e) => setNewKeyDescription(e.target.value)}
              placeholder="Optional description for this key"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        {/* Role Selection */}
        <div>
          <label className="block text-[10px] font-mono text-[#6B6B6E] uppercase mb-2">Access Scope / Role *</label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {ROLES.map((role) => {
              const Icon = role.icon;
              return (
                <button
                  key={role.value}
                  type="button"
                  onClick={() => setNewKeyRole(role.value)}
                  className={`p-3 rounded-lg border text-left transition-all cursor-pointer ${newKeyRole === role.value
                    ? 'bg-[#FFB020]/10 border-[#FFB020]/40'
                    : 'bg-[#141416] border-white/[0.06] hover:border-white/[0.12]'
                    }`}
                >
                  <div className="flex items-center gap-2">
                    <Icon size={14} className={newKeyRole === role.value ? 'text-[#FFB020]' : role.color} />
                    <span className={`text-xs font-medium ${newKeyRole === role.value ? 'text-[#FFB020]' : 'text-[#F2F1EE]'}`}>
                      {role.label}
                    </span>
                  </div>
                  <p className="text-[10px] text-[#6B6B6E] mt-1">{role.desc}</p>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Environment */}
          <div>
            <label className="block text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Environment</label>
            <select
              value={newKeyEnv}
              onChange={(e) => setNewKeyEnv(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] cursor-pointer"
            >
              {ENVIRONMENTS.map((env) => (
                <option key={env} value={env}>{env}</option>
              ))}
            </select>
          </div>

          {/* Expiry */}
          <div>
            <label className="block text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Expires In</label>
            <select
              value={newKeyExpiresDays ?? 'never'}
              onChange={(e) => setNewKeyExpiresDays(e.target.value === 'never' ? null : Number(e.target.value))}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] cursor-pointer"
            >
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="180">6 months</option>
              <option value="365">1 year</option>
              <option value="never">Never expires</option>
            </select>
          </div>
        </div>

        <Button variant="primary" size="sm" type="submit" icon={<Plus size={14} />} disabled={creating || !newKeyName.trim()}>
          {creating ? 'Generating...' : 'Generate API Key'}
        </Button>
      </form>

      {/* Secret Callout */}
      {createdSecret && (
        <div className="p-4 bg-emerald-500/15 border border-emerald-500/30 rounded-xl space-y-2 font-mono">
          <div className="text-emerald-400 font-bold text-xs">
            New API Key Created — Copy it now! It won't be shown again.
          </div>
          <div className="flex items-center justify-between bg-[#060608] p-2.5 rounded border border-emerald-500/30 text-emerald-300">
            <span className="text-xs select-all break-all">{createdSecret}</span>
            <button
              type="button"
              onClick={handleCopySecret}
              className="ml-3 px-2.5 py-1 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 rounded text-[11px] flex items-center gap-1 cursor-pointer shrink-0"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              <span>{copied ? 'Copied!' : 'Copy'}</span>
            </button>
          </div>
          <p className="text-[10px] text-emerald-400/70">
            Use as: <code className="bg-black/30 px-1 rounded">Authorization: Bearer {createdSecret.substring(0, 12)}...</code>
          </p>
        </div>
      )}

      {/* Active Keys List */}
      <div className="space-y-3">
        <h3 className="text-xs font-mono text-[#A8A8AB] uppercase font-bold">
          {loading ? 'Loading...' : `API Keys (${apiKeys.length})`}
        </h3>

        {!loading && apiKeys.length === 0 && (
          <div className="p-6 text-center text-[#6B6B6E] text-xs border border-dashed border-white/[0.08] rounded-lg">
            No API keys created yet. Generate one above to get started.
          </div>
        )}

        <div className="space-y-2">
          {apiKeys.map((k) => {
            const roleInfo = getRoleInfo(k.role)!;
            const RoleIcon = roleInfo.icon;
            const isRevoked = k.status === 'revoked';

            return (
              <div
                key={k.id}
                className={`p-4 bg-[#101012] border rounded-lg flex items-center justify-between gap-4 ${isRevoked ? 'border-rose-500/20 opacity-60' : 'border-white/[0.08]'
                  }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-white text-xs">{k.name}</span>
                    {isRevoked && (
                      <span className="px-1.5 py-0.5 bg-rose-500/20 text-rose-400 text-[9px] font-mono rounded uppercase">
                        Revoked
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-[#FFB020] font-mono mt-0.5">{k.key_prefix}</div>
                  <div className="flex items-center gap-3 mt-1.5 text-[10px] text-[#6B6B6E]">
                    <span className="flex items-center gap-1">
                      <RoleIcon size={10} className={roleInfo.color} />
                      {roleInfo.label}
                    </span>
                    <span>{k.environment}</span>
                    <span>Created {new Date(k.created_at).toLocaleDateString()}</span>
                    {k.expires_at && (
                      <span>Expires {new Date(k.expires_at).toLocaleDateString()}</span>
                    )}
                    {k.last_used_at && (
                      <span>Last used {new Date(k.last_used_at).toLocaleDateString()}</span>
                    )}
                  </div>
                  {k.description && (
                    <div className="text-[10px] text-[#6B6B6E] mt-1 italic">{k.description}</div>
                  )}
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  {!isRevoked && (
                    <button
                      type="button"
                      onClick={() => handleRevokeKey(k.id)}
                      title="Revoke key (disable without deleting)"
                      className="p-2 text-gray-500 hover:text-amber-400 hover:bg-amber-500/10 rounded transition-colors cursor-pointer"
                    >
                      <Shield size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDeleteKey(k.id)}
                    title="Delete key permanently"
                    className="p-2 text-gray-500 hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors cursor-pointer"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
