import { useState } from 'react';
import { Key, Plus, Trash2, Copy, Check } from 'lucide-react';
import { Button } from '@/components/common/Button';
import type { ApiKeyItem } from '../types';

interface ApiKeysTabProps {
  onSaveToast: (msg?: string) => void;
}

export function ApiKeysTab({ onSaveToast }: ApiKeysTabProps) {
  const [apiKeys, setApiKeys] = useState<ApiKeyItem[]>([
    { id: 'k1', name: 'Agent Runtime Production', prefix: 'nx_live_8f3a...', createdAt: '2024-04-12', scopes: 'read:agents, write:tasks, exec:pipelines' },
    { id: 'k2', name: 'CI/CD GitHub Actions Sync', prefix: 'nx_live_e901...', createdAt: '2024-05-01', scopes: 'read:repos, write:deployments' },
    { id: 'k3', name: 'Telemetry Scraper Prom', prefix: 'nx_live_3c44...', createdAt: '2024-05-10', scopes: 'read:metrics, read:audit' },
  ]);

  const [newKeyName, setNewKeyName] = useState('');
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleCreateApiKey = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    const secret = `nx_live_${Math.random().toString(36).substring(2, 10)}${Math.random().toString(36).substring(2, 10)}`;
    const newKey: ApiKeyItem = {
      id: `k-${Date.now()}`,
      name: newKeyName.trim(),
      prefix: `${secret.substring(0, 11)}...`,
      createdAt: new Date().toISOString().split('T')[0] || '2024-05-16',
      scopes: 'full:access',
    };
    setApiKeys([newKey, ...apiKeys]);
    setCreatedSecret(secret);
    setNewKeyName('');
    onSaveToast(`API Key '${newKey.name}' generated successfully`);
  };

  const handleDeleteKey = (id: string) => {
    setApiKeys(apiKeys.filter((k) => k.id !== id));
    onSaveToast('API Key revoked');
  };

  const handleCopySecret = () => {
    if (createdSecret) {
      navigator.clipboard.writeText(createdSecret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Key size={18} className="text-[#FFB020]" />
            API Access Keys & Bearer Tokens
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Manage live authentication tokens for CI/CD pipelines, agent sidecars, and webhooks.
          </p>
        </div>
      </div>

      {/* Create Key Form */}
      <form onSubmit={handleCreateApiKey} className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
        <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase">
          Generate New API Access Key
        </label>
        <div className="flex gap-2 max-w-lg">
          <input
            type="text"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="Key description (e.g. Production Kubernetes Runner)"
            className="flex-1 px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            required
          />
          <Button variant="primary" size="sm" type="submit" icon={<Plus size={14} />}>
            Generate Key
          </Button>
        </div>
      </form>

      {/* Secret Callout */}
      {createdSecret && (
        <div className="p-4 bg-emerald-500/15 border border-emerald-500/30 rounded-xl space-y-2 font-mono">
          <div className="text-emerald-400 font-bold text-xs">
            ✔ New API Key Created — Save Secret Key Now!
          </div>
          <div className="flex items-center justify-between bg-[#060608] p-2.5 rounded border border-emerald-500/30 text-emerald-300">
            <span className="text-xs select-all">{createdSecret}</span>
            <button
              type="button"
              onClick={handleCopySecret}
              className="px-2.5 py-1 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 rounded text-[11px] flex items-center gap-1 cursor-pointer"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              <span>{copied ? 'Copied!' : 'Copy Secret'}</span>
            </button>
          </div>
        </div>
      )}

      {/* Active Keys List */}
      <div className="space-y-2">
        <h3 className="text-xs font-mono text-[#A8A8AB] uppercase font-bold">
          Active API Keys ({apiKeys.length})
        </h3>

        <div className="space-y-2">
          {apiKeys.map((k) => (
            <div
              key={k.id}
              className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-lg flex items-center justify-between gap-4 font-mono"
            >
              <div>
                <div className="font-bold text-white text-xs">{k.name}</div>
                <div className="text-[11px] text-[#FFB020] mt-0.5">{k.prefix}</div>
                <div className="text-[10px] text-gray-500 mt-1 font-sans">
                  Created {k.createdAt} · Scopes: {k.scopes}
                </div>
              </div>

              <button
                type="button"
                onClick={() => handleDeleteKey(k.id)}
                className="p-2 text-gray-500 hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors cursor-pointer"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
