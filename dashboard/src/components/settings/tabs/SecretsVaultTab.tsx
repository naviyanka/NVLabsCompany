/**
 * SecretsVaultTab — manage the company secret vault.
 *
 * Wraps the backend secret API (metadata only; values are never returned):
 *   GET  /api/v1/secrets
 *   POST /api/v1/secrets                 { name, category, value, expires_at? }
 *   POST /api/v1/secrets/{id}/rotate     { new_value }
 *   POST /api/v1/secrets/{id}/revoke
 *   POST /api/v1/secrets/{id}/bind       { agent_id, expires_at?, one_time_use? }
 *
 * Create/rotate require the server SECRET_KEY to be set (not the dev default);
 * otherwise the backend answers 503, which we surface as a clear message.
 */

import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { KeyRound, Lock, Plus, RefreshCw, ShieldOff, X } from 'lucide-react';
import { useEffect, useState } from 'react';

interface SecretMeta {
  id: string;
  name: string;
  category: string;
  current_version: number;
  expires_at?: string | null;
  is_revoked: boolean;
  created_at: string;
  updated_at: string;
}

interface SecretsVaultTabProps {
  onSaveToast: (msg?: string) => void;
}

const inputCls =
  'w-full px-3 py-2 bg-[#0C0C0E] border border-white/[0.1] rounded text-white text-xs focus:outline-none focus:border-[#FFB020]';
const labelCls = 'block text-[11px] font-mono text-gray-400 uppercase mb-1';

export function SecretsVaultTab({ onSaveToast }: SecretsVaultTabProps) {
  const [secrets, setSecrets] = useState<SecretMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [rotateTarget, setRotateTarget] = useState<SecretMeta | null>(null);

  const loadSecrets = async () => {
    try {
      const res = await apiClient.get<SecretMeta[]>('/api/v1/secrets');
      setSecrets(Array.isArray(res) ? res : []);
    } catch (err) {
      console.error('Failed to load secrets', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSecrets();
  }, []);

  const handleRevoke = async (s: SecretMeta) => {
    try {
      await apiClient.post(`/api/v1/secrets/${s.id}/revoke`, {});
      setSecrets((prev) => prev.map((x) => (x.id === s.id ? { ...x, is_revoked: true } : x)));
      onSaveToast(`Secret "${s.name}" revoked — all bindings invalidated.`);
    } catch (err) {
      console.error('Failed to revoke secret', err);
      onSaveToast('Failed to revoke secret.');
    }
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Lock size={18} className="text-[#FFB020]" />
            Secrets Vault
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Encrypted, versioned secrets. Values are write-only — they are never returned by the
            API after creation.
          </p>
        </div>
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowCreate(true)}>
          New Secret
        </Button>
      </div>

      {loading ? (
        <div className="p-8 text-center font-mono text-[#6B6B6E]">Loading secrets…</div>
      ) : secrets.length === 0 ? (
        <div className="p-8 text-center bg-[#101012] border border-white/[0.08] rounded-[10px] font-mono text-[#6B6B6E]">
          No secrets stored. Create one to make it available for binding to agents.
        </div>
      ) : (
        <div className="space-y-2">
          {secrets.map((s) => (
            <div
              key={s.id}
              className="p-3.5 bg-[#141416] border border-white/[0.08] rounded-[8px] flex items-center justify-between gap-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-8 h-8 rounded flex items-center justify-center bg-white/[0.04] border border-white/[0.08] shrink-0">
                  <KeyRound size={15} className={s.is_revoked ? 'text-[#6B6B6E]' : 'text-[#FFB020]'} />
                </span>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-[#F2F1EE] truncate flex items-center gap-2">
                    {s.name}
                    {s.is_revoked && (
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-rose-500/10 text-rose-400 border border-rose-500/20">
                        revoked
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] font-mono text-[#6B6B6E]">
                    {s.category} · v{s.current_version}
                    {s.expires_at && <> · expires {new Date(s.expires_at).toLocaleDateString()}</>}
                  </div>
                </div>
              </div>

              {!s.is_revoked && (
                <div className="flex items-center gap-1.5 shrink-0">
                  <Button
                    variant="ghost"
                    size="xs"
                    icon={<RefreshCw size={12} className="text-cyan-400" />}
                    onClick={() => setRotateTarget(s)}
                  >
                    Rotate
                  </Button>
                  <Button
                    variant="ghost"
                    size="xs"
                    icon={<ShieldOff size={12} className="text-rose-400" />}
                    onClick={() => handleRevoke(s)}
                  >
                    Revoke
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateSecretModal
          onClose={() => setShowCreate(false)}
          onSaveToast={onSaveToast}
          onCreated={(s) => {
            setSecrets((prev) => [s, ...prev]);
            setShowCreate(false);
          }}
        />
      )}

      {rotateTarget && (
        <RotateSecretModal
          secret={rotateTarget}
          onClose={() => setRotateTarget(null)}
          onSaveToast={onSaveToast}
          onRotated={(updated) => {
            setSecrets((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
            setRotateTarget(null);
          }}
        />
      )}
    </div>
  );
}

/* ── Create modal ── */
function CreateSecretModal({
  onClose,
  onCreated,
  onSaveToast,
}: {
  onClose: () => void;
  onCreated: (s: SecretMeta) => void;
  onSaveToast: (msg?: string) => void;
}) {
  const [name, setName] = useState('');
  const [category, setCategory] = useState('general');
  const [value, setValue] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    if (!name.trim() || !value) return;
    setSaving(true);
    try {
      const created = await apiClient.post<SecretMeta>('/api/v1/secrets', {
        name: name.trim(),
        category: category.trim() || 'general',
        value,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      onSaveToast(`Secret "${created.name}" stored (encrypted, v${created.current_version}).`);
      onCreated(created);
    } catch (err: any) {
      console.error('Failed to create secret', err);
      const msg = err?.status === 503 || /503/.test(String(err?.message))
        ? 'Server SECRET_KEY is unset or the dev default — set it to enable secret encryption.'
        : 'Failed to create secret.';
      onSaveToast(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#141416] border border-white/[0.12] rounded-[12px] p-5 w-[440px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-white">New Secret</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white cursor-pointer"><X size={16} /></button>
        </div>

        <div className="space-y-3">
          <div>
            <label className={labelCls}>Name</label>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="OPENAI_API_KEY" />
          </div>
          <div>
            <label className={labelCls}>Category</label>
            <input className={inputCls} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="general" />
          </div>
          <div>
            <label className={labelCls}>Value (stored encrypted, never shown again)</label>
            <input type="password" className={inputCls} value={value} onChange={(e) => setValue(e.target.value)} placeholder="••••••••••••" />
          </div>
          <div>
            <label className={labelCls}>Expires (optional)</label>
            <input type="datetime-local" className={inputCls} value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" loading={saving} disabled={!name.trim() || !value} onClick={handleCreate}>
            Store Secret
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Rotate modal ── */
function RotateSecretModal({
  secret,
  onClose,
  onRotated,
  onSaveToast,
}: {
  secret: SecretMeta;
  onClose: () => void;
  onRotated: (s: SecretMeta) => void;
  onSaveToast: (msg?: string) => void;
}) {
  const [newValue, setNewValue] = useState('');
  const [saving, setSaving] = useState(false);

  const handleRotate = async () => {
    if (!newValue) return;
    setSaving(true);
    try {
      const updated = await apiClient.post<SecretMeta>(`/api/v1/secrets/${secret.id}/rotate`, {
        new_value: newValue,
      });
      onSaveToast(`Secret "${secret.name}" rotated to v${updated.current_version}.`);
      onRotated(updated);
    } catch (err: any) {
      console.error('Failed to rotate secret', err);
      const msg = err?.status === 503 || /503/.test(String(err?.message))
        ? 'Server SECRET_KEY is unset or the dev default — set it to enable secret encryption.'
        : 'Failed to rotate secret.';
      onSaveToast(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#141416] border border-white/[0.12] rounded-[12px] p-5 w-[440px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-white">Rotate — {secret.name}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white cursor-pointer"><X size={16} /></button>
        </div>
        <p className="text-[11px] text-[#6B6B6E] mb-3">
          Rotating creates a new version (v{secret.current_version + 1}) and revokes the previous one.
        </p>
        <div>
          <label className={labelCls}>New value</label>
          <input type="password" className={inputCls} value={newValue} onChange={(e) => setNewValue(e.target.value)} placeholder="••••••••••••" />
        </div>
        <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" loading={saving} disabled={!newValue} onClick={handleRotate}>
            Rotate
          </Button>
        </div>
      </div>
    </div>
  );
}
