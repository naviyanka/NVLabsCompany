import { useState } from 'react';
import {
  Plus,
  Trash2,
  AlertTriangle,
  Download,
} from 'lucide-react';
import type { SettingsTabId } from './types';

interface OtherSettingsTabProps {
  activeTab: SettingsTabId;
  onSaveToast: () => void;
}

export function OtherSettingsTabs({ activeTab, onSaveToast }: OtherSettingsTabProps) {
  // General State
  const [workspaceName, setWorkspaceName] = useState('NEXUS Autonomous Operations');
  const [defaultEnv, setDefaultEnv] = useState('production');

  // Security State
  const [twoFactorAuth, setTwoFactorAuth] = useState(true);
  const [sessionTimeout, setSessionTimeout] = useState('24');
  const [requireSaml, setRequireSaml] = useState(false);

  // API Keys State
  const [apiKeys, setApiKeys] = useState([
    { id: 'k1', name: 'Agent Runtime Production', prefix: 'nx_live_8f3a...', created: '2024-04-12', scopes: 'read:agents, write:tasks, exec:pipelines' },
    { id: 'k2', name: 'CI/CD GitHub Actions Sync', prefix: 'nx_live_e901...', created: '2024-05-01', scopes: 'read:repos, write:deployments' },
    { id: 'k3', name: 'Telemetry Scraper Prom', prefix: 'nx_live_3c44...', created: '2024-05-10', scopes: 'read:metrics, read:audit' },
  ]);
  const [newKeyName, setNewKeyName] = useState('');
  const [createdKeySecret, setCreatedKeySecret] = useState<string | null>(null);

  // Integrations State
  const [integrations, setIntegrations] = useState([
    { id: 'slack', name: 'Slack Workplace', desc: 'Real-time agent anomaly alerts & standup sync', active: true, icon: '💬' },
    { id: 'github', name: 'GitHub Enterprise', desc: 'Continuous repository syncing & auto-PR evaluations', active: true, icon: '🐙' },
    { id: 'linear', name: 'Linear Tracker', desc: 'Autonomous bug triage and task dispatching', active: true, icon: '📐' },
    { id: 'datadog', name: 'Datadog APM', desc: 'Host telemetry, traces, and LLM latency spans', active: false, icon: '🐕' },
    { id: 'aws', name: 'AWS CloudWatch', desc: 'Cluster orchestration and autoscaling events', active: true, icon: '☁️' },
  ]);

  // Billing State
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'annual'>('annual');

  // System Configuration State
  const [defaultModel, setDefaultModel] = useState('Claude 3.5 Sonnet');
  const [fallbackModel, setFallbackModel] = useState('GPT-4o');
  const [maxTaskBudget, setMaxTaskBudget] = useState('15.00');
  const [dailyCompanyCap, setDailyCompanyCap] = useState('250.00');
  const [killSwitchEngaged, setKillSwitchEngaged] = useState(false);

  // Notifications State
  const [notifConfig, setNotifConfig] = useState({
    emailAgentFailure: true,
    emailBudget90: true,
    slackTaskBlocked: true,
    browserPings: false,
    weeklyDigest: true,
  });

  const handleCreateApiKey = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    const generatedSecret = `nx_live_${Math.random().toString(36).substring(2, 10)}${Math.random().toString(36).substring(2, 10)}`;
    const newKey = {
      id: `k-${Date.now()}`,
      name: newKeyName,
      prefix: `${generatedSecret.substring(0, 11)}...`,
      created: new Date().toISOString().split('T')[0] || '2024-05-16',
      scopes: 'full:access',
    };
    setApiKeys([newKey, ...apiKeys]);
    setCreatedKeySecret(generatedSecret);
    setNewKeyName('');
  };

  const deleteApiKey = (id: string) => {
    setApiKeys(apiKeys.filter((k) => k.id !== id));
  };

  const toggleIntegration = (id: string) => {
    setIntegrations(
      integrations.map((item) => (item.id === id ? { ...item, active: !item.active } : item))
    );
  };

  return (
    <div className="w-full space-y-6">
      {/* 1. General Tab */}
      {activeTab === 'general' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">General Settings</h2>
              <p className="text-xs text-[#A8A8AB]">Workspace identity, default region, and orchestration defaults.</p>
            </div>
            <button
              onClick={onSaveToast}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
            >
              Save Changes
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
            <div>
              <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">Workspace Name</label>
              <input
                type="text"
                value={workspaceName}
                onChange={(e) => setWorkspaceName(e.target.value)}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">Primary Environment</label>
              <select
                value={defaultEnv}
                onChange={(e) => setDefaultEnv(e.target.value)}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none"
              >
                <option value="production">Production (High Availability)</option>
                <option value="staging">Staging (Canary Sandbox)</option>
                <option value="development">Development (Local Mock)</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* 2. Security Tab */}
      {activeTab === 'security' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Security & Access Governance</h2>
              <p className="text-xs text-[#A8A8AB]">Authentication barriers, SSO protocols, and session controls.</p>
            </div>
            <button
              onClick={onSaveToast}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
            >
              Save Changes
            </button>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between p-4 bg-[#141416] border border-white/[0.08] rounded-xl">
              <div>
                <div className="text-xs font-semibold text-[#F2F1EE]">Two-Factor Authentication (2FA)</div>
                <div className="text-[11px] text-[#6B6B6E] font-mono">Enforce hardware keys or TOTP for all operator actions</div>
              </div>
              <button
                type="button"
                onClick={() => setTwoFactorAuth(!twoFactorAuth)}
                className={`w-11 h-6 rounded-full relative transition-colors cursor-pointer ${
                  twoFactorAuth ? 'bg-[#FFB020]' : 'bg-[#242428]'
                }`}
              >
                <div
                  className={`w-4 h-4 rounded-full bg-[#0A0A0B] absolute top-1 transition-transform ${
                    twoFactorAuth ? 'right-1' : 'left-1 bg-white/70'
                  }`}
                />
              </button>
            </div>

            <div className="flex items-center justify-between p-4 bg-[#141416] border border-white/[0.08] rounded-xl">
              <div>
                <div className="text-xs font-semibold text-[#F2F1EE]">SAML 2.0 / Okta Enterprise SSO</div>
                <div className="text-[11px] text-[#6B6B6E] font-mono">Force all organization members to authenticate through corporate identity provider</div>
              </div>
              <button
                type="button"
                onClick={() => setRequireSaml(!requireSaml)}
                className={`w-11 h-6 rounded-full relative transition-colors cursor-pointer ${
                  requireSaml ? 'bg-[#FFB020]' : 'bg-[#242428]'
                }`}
              >
                <div
                  className={`w-4 h-4 rounded-full bg-[#0A0A0B] absolute top-1 transition-transform ${
                    requireSaml ? 'right-1' : 'left-1 bg-white/70'
                  }`}
                />
              </button>
            </div>

            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-2">
              <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Inactivity Session Timeout (Hours)</label>
              <input
                type="number"
                value={sessionTimeout}
                onChange={(e) => setSessionTimeout(e.target.value)}
                className="w-48 px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] font-mono outline-none"
              />
            </div>
          </div>
        </div>
      )}

      {/* 3. API Keys Tab */}
      {activeTab === 'api_keys' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">API Keys & Tokens</h2>
              <p className="text-xs text-[#A8A8AB]">Authenticate external CI/CD pipelines, agent dispatchers, and scrapers.</p>
            </div>
          </div>

          {/* Create Key Form */}
          <form onSubmit={handleCreateApiKey} className="flex gap-3">
            <input
              type="text"
              placeholder="Key Name (e.g. Production Dispatcher)"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="flex-1 px-3.5 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none font-mono"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold flex items-center gap-1.5 cursor-pointer transition-colors"
            >
              <Plus size={14} />
              <span>Generate Key</span>
            </button>
          </form>

          {createdKeySecret && (
            <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl space-y-2">
              <div className="text-xs font-semibold text-emerald-400 font-mono">Save Your Secret Key Now</div>
              <p className="text-[11px] text-[#A8A8AB]">This secret will never be displayed again.</p>
              <div className="flex items-center gap-2 p-2.5 bg-[#0A0A0B] rounded-lg border border-white/[0.08]">
                <code className="text-xs font-mono text-[#F2F1EE] flex-1">{createdKeySecret}</code>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(createdKeySecret);
                    alert('Copied to clipboard!');
                  }}
                  className="px-2.5 py-1 bg-[#1C1C1F] hover:bg-[#2A2A2E] text-xs font-mono text-[#FFB020] border border-[#FFB020]/30 rounded cursor-pointer transition-colors"
                >
                  Copy
                </button>
              </div>
            </div>
          )}

          {/* Keys List */}
          <div className="space-y-3">
            {apiKeys.map((k) => (
              <div key={k.id} className="flex items-center justify-between p-4 bg-[#141416] border border-white/[0.08] rounded-xl">
                <div>
                  <div className="text-xs font-semibold text-[#F2F1EE]">{k.name}</div>
                  <div className="text-[11px] font-mono text-[#6B6B6E] mt-0.5">{k.prefix} • Created {k.created}</div>
                  <div className="text-[10px] font-mono text-[#FFB020] mt-1">Scopes: {k.scopes}</div>
                </div>
                <button
                  type="button"
                  onClick={() => deleteApiKey(k.id)}
                  className="p-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg cursor-pointer transition-colors"
                  title="Revoke key"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. Integrations Tab */}
      {activeTab === 'integrations' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Connected Integrations</h2>
              <p className="text-xs text-[#A8A8AB]">Connect third-party developer toolchains and messaging channels.</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {integrations.map((item) => (
              <div key={item.id} className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <span className="text-2xl">{item.icon}</span>
                  <div>
                    <div className="text-xs font-semibold text-[#F2F1EE]">{item.name}</div>
                    <div className="text-[11px] text-[#A8A8AB] mt-0.5">{item.desc}</div>
                    <div className="mt-2">
                      <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                        item.active ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/[0.04] text-[#6B6B6E]'
                      }`}>
                        {item.active ? 'Active Connection' : 'Disabled'}
                      </span>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => toggleIntegration(item.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors cursor-pointer ${
                    item.active
                      ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                      : 'bg-[#FFB020] text-[#0A0A0B] hover:bg-[#E59E1C]'
                  }`}
                >
                  {item.active ? 'Disconnect' : 'Connect'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. Teams & Users */}
      {activeTab === 'teams' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Teams & Operators</h2>
              <p className="text-xs text-[#A8A8AB]">Manage platform operators, supervisors, and invite colleagues.</p>
            </div>
            <button
              onClick={() => alert('Invitation modal opened')}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold flex items-center gap-1.5 cursor-pointer transition-colors"
            >
              <Plus size={14} />
              <span>Invite Operator</span>
            </button>
          </div>

          <div className="space-y-3">
            {[
              { name: 'Navi Yanka', email: 'navi.yanka@nvlabs.dev', role: 'Super Admin / Operator', status: 'Active (You)', avatar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80' },
              { name: 'Elena Rostova', email: 'elena.rostova@nvlabs.dev', role: 'Security Auditor', status: 'Active', avatar: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop&q=80' },
              { name: 'Marcus Vance', email: 'marcus.vance@nvlabs.dev', role: 'Pipeline Lead', status: 'Active', avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&auto=format&fit=crop&q=80' },
            ].map((usr, i) => (
              <div key={i} className="flex items-center justify-between p-3.5 bg-[#141416] border border-white/[0.08] rounded-xl">
                <div className="flex items-center gap-3">
                  <img src={usr.avatar} alt={usr.name} className="w-9 h-9 rounded-full object-cover ring-1 ring-white/10" />
                  <div>
                    <div className="text-xs font-semibold text-[#F2F1EE]">{usr.name}</div>
                    <div className="text-[11px] text-[#6B6B6E] font-mono">{usr.email}</div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-[#FFB020] font-mono font-medium">{usr.role}</span>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-mono">
                    {usr.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 6. Roles & Permissions */}
      {activeTab === 'roles' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Roles & Permissions (RBAC)</h2>
              <p className="text-xs text-[#A8A8AB]">Granular security matrix controlling agent mutations, tool execution, and budget authorization.</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { title: 'Super Admin', desc: 'Unrestricted execution, key generation, budget overrides, kill switch engagement.', badge: 'Full Access' },
              { title: 'Fleet Operator', desc: 'Task dispatching, pipeline triggers, agent prompting, and standup moderation.', badge: 'Standard Ops' },
              { title: 'Read-Only Auditor', desc: 'View telemetry, live agent logs, memory records, and compliance metrics.', badge: 'Inspect Only' },
            ].map((role, i) => (
              <div key={i} className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-[#F2F1EE]">{role.title}</h4>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20">
                    {role.badge}
                  </span>
                </div>
                <p className="text-[11px] text-[#A8A8AB] leading-relaxed">{role.desc}</p>
                <button
                  type="button"
                  onClick={() => alert(`Configuring role permissions for ${role.title}`)}
                  className="w-full py-1.5 bg-[#1C1C1F] hover:bg-[#2A2A2E] text-[#F2F1EE] border border-white/[0.08] rounded-lg text-xs font-mono font-medium cursor-pointer transition-colors"
                >
                  Edit Permissions Matrix
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 7. Billing & Subscription */}
      {activeTab === 'billing' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Billing & Subscription</h2>
              <p className="text-xs text-[#A8A8AB]">Enterprise cluster licensing, token allotments, and invoice downloads.</p>
            </div>
            <div className="flex items-center gap-1 bg-[#0A0A0B] p-1 rounded-lg border border-white/[0.08] font-mono text-xs">
              <button
                type="button"
                onClick={() => setBillingCycle('monthly')}
                className={`px-3 py-1 rounded text-xs font-medium cursor-pointer ${
                  billingCycle === 'monthly' ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold' : 'text-[#6B6B6E]'
                }`}
              >
                Monthly
              </button>
              <button
                type="button"
                onClick={() => setBillingCycle('annual')}
                className={`px-3 py-1 rounded text-xs font-medium cursor-pointer ${
                  billingCycle === 'annual' ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold' : 'text-[#6B6B6E]'
                }`}
              >
                Annual (Save 20%)
              </button>
            </div>
          </div>

          <div className="p-5 bg-gradient-to-br from-[#1C1C1F] to-[#141416] border border-[#FFB020]/30 rounded-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 bg-[#FFB020]/20 text-[#FFB020] text-[10px] font-mono font-semibold rounded uppercase tracking-wider">
                  Current Tier
                </span>
                <span className="text-xs text-emerald-400 font-mono">Renews April 2025</span>
              </div>
              <h3 className="text-xl font-bold text-[#F2F1EE] mt-1">Enterprise Fleet Tier</h3>
              <p className="text-xs text-[#A8A8AB] mt-0.5">Unlimited agents, 100M LLM reasoning tokens / mo, dedicated VPC gateway</p>
            </div>

            <div className="text-right">
              <div className="text-2xl font-bold text-[#F2F1EE] font-mono">$1,250 <span className="text-xs font-normal text-[#6B6B6E]">/ month</span></div>
              <button
                type="button"
                onClick={() => alert('Contacting enterprise account representative')}
                className="mt-2 px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] font-semibold font-mono text-xs rounded-lg transition-colors cursor-pointer"
              >
                Upgrade Cluster
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 8. System Configuration Tab */}
      {activeTab === 'system_config' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">System Configuration & Routing</h2>
              <p className="text-xs text-[#A8A8AB]">Reasoning engine failovers, spend guardrails, and emergency kill switches.</p>
            </div>
            <button
              onClick={onSaveToast}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
            >
              Save Configuration
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-2">
              <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Primary Reasoning Engine</label>
              <select
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none"
              >
                <option value="Claude 3.5 Sonnet">Claude 3.5 Sonnet (Default Ops)</option>
                <option value="GPT-4o">GPT-4o (OpenAI Omni)</option>
                <option value="Gemini 1.5 Pro">Gemini 1.5 Pro (Google)</option>
                <option value="DeepSeek R1">DeepSeek R1 (Local Reasoning)</option>
              </select>
            </div>

            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-2">
              <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Fallback Failover Provider</label>
              <select
                value={fallbackModel}
                onChange={(e) => setFallbackModel(e.target.value)}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none"
              >
                <option value="GPT-4o">GPT-4o</option>
                <option value="Claude 3.5 Sonnet">Claude 3.5 Sonnet</option>
                <option value="Gemini 1.5 Pro">Gemini 1.5 Pro</option>
              </select>
            </div>

            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-2">
              <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Max Spend Per Task ($ USD)</label>
              <input
                type="number"
                step="0.50"
                value={maxTaskBudget}
                onChange={(e) => setMaxTaskBudget(e.target.value)}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] font-mono outline-none"
              />
            </div>

            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-2">
              <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Daily Company Spend Ceiling ($ USD)</label>
              <input
                type="number"
                step="10.00"
                value={dailyCompanyCap}
                onChange={(e) => setDailyCompanyCap(e.target.value)}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] font-mono outline-none"
              />
            </div>
          </div>

          {/* Emergency Kill Switch */}
          <div className="p-4 bg-red-950/20 border border-red-500/30 rounded-xl flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2 text-xs font-semibold text-red-400 font-mono">
                <AlertTriangle size={15} />
                <span>Global Autonomous Kill Switch</span>
              </div>
              <p className="text-[11px] text-[#A8A8AB]">Instantly suspends all background agent loops and tool AST executions.</p>
            </div>
            <button
              type="button"
              onClick={() => setKillSwitchEngaged(!killSwitchEngaged)}
              className={`px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
                killSwitchEngaged
                  ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  : 'bg-red-600 hover:bg-red-500 text-white'
              }`}
            >
              {killSwitchEngaged ? 'DISENGAGE KILL SWITCH' : 'ENGAGE EMERGENCY STOP'}
            </button>
          </div>
        </div>
      )}

      {/* 9. Notifications Tab */}
      {activeTab === 'notifications' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Notification Preferences</h2>
              <p className="text-xs text-[#A8A8AB]">Configure delivery destinations and thresholds for alerts.</p>
            </div>
            <button
              onClick={onSaveToast}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
            >
              Save Preferences
            </button>
          </div>

          <div className="space-y-3">
            {[
              { key: 'emailAgentFailure', label: 'Agent Exception or Memory Stall', desc: 'Receive immediate email alert when an agent hits an unhandled error' },
              { key: 'emailBudget90', label: 'Budget 90% Threshold Warning', desc: 'Alert when hourly or daily token budget approaches limit' },
              { key: 'slackTaskBlocked', label: 'Slack Webhook for Blocked Tasks', desc: 'Post directly to #mission-control when human gate signoff is required' },
              { key: 'weeklyDigest', label: 'Weekly Autonomous Operations Digest', desc: 'Summary of tasks executed, cost per OKR, and performance evolution' },
            ].map((item) => (
              <div key={item.key} className="flex items-center justify-between p-4 bg-[#141416] border border-white/[0.08] rounded-xl">
                <div>
                  <div className="text-xs font-semibold text-[#F2F1EE]">{item.label}</div>
                  <div className="text-[11px] text-[#6B6B6E] font-mono">{item.desc}</div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setNotifConfig({
                      ...notifConfig,
                      [item.key]: !notifConfig[item.key as keyof typeof notifConfig],
                    })
                  }
                  className={`w-11 h-6 rounded-full relative transition-colors cursor-pointer ${
                    notifConfig[item.key as keyof typeof notifConfig] ? 'bg-[#FFB020]' : 'bg-[#242428]'
                  }`}
                >
                  <div
                    className={`w-4 h-4 rounded-full bg-[#0A0A0B] absolute top-1 transition-transform ${
                      notifConfig[item.key as keyof typeof notifConfig] ? 'right-1' : 'left-1 bg-white/70'
                    }`}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 10. Data & Storage Tab */}
      {activeTab === 'data_storage' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Data & Memory Storage</h2>
              <p className="text-xs text-[#A8A8AB]">Vector database index health, cache allocations, and vector compactors.</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 font-mono">
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-1">
              <span className="text-[11px] text-[#6B6B6E]">Vector Embeddings</span>
              <div className="text-xl font-bold text-[#F2F1EE]">1,482,900</div>
              <span className="text-[10px] text-emerald-400 font-mono">Index Healthy (HNSW)</span>
            </div>
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-1">
              <span className="text-[11px] text-[#6B6B6E]">Redis Context Cache</span>
              <div className="text-xl font-bold text-[#F2F1EE]">4.2 GB / 16 GB</div>
              <span className="text-[10px] text-emerald-400 font-mono">26% Utilized</span>
            </div>
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-1">
              <span className="text-[11px] text-[#6B6B6E]">Episodic Memory Retention</span>
              <div className="text-xl font-bold text-[#F2F1EE]">180 Days</div>
              <span className="text-[10px] text-[#FFB020] font-mono">Auto-Compaction On</span>
            </div>
          </div>
        </div>
      )}

      {/* 11. Backup & Restore */}
      {activeTab === 'backup' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Backup & Disaster Recovery</h2>
              <p className="text-xs text-[#A8A8AB]">Snapshot agent checkpoints, export workspace archives, and restore past states.</p>
            </div>
            <button
              onClick={() => alert('Snapshot backup triggered')}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold flex items-center gap-1.5 cursor-pointer transition-colors"
            >
              <Download size={14} />
              <span>Create Snapshot Now</span>
            </button>
          </div>

          <div className="space-y-3">
            {[
              { name: 'Daily Automated Snapshot #142', date: 'May 16, 2024, 04:00 AM', size: '284 MB', status: 'Verified' },
              { name: 'Pre-Deployment Release v2.4.0', date: 'May 15, 2024, 18:30 PM', size: '281 MB', status: 'Verified' },
              { name: 'Weekly System Archive #38', date: 'May 12, 2024, 00:00 AM', size: '1.2 GB', status: 'Archived' },
            ].map((snap, i) => (
              <div key={i} className="flex items-center justify-between p-3.5 bg-[#141416] border border-white/[0.08] rounded-xl">
                <div>
                  <div className="text-xs font-semibold text-[#F2F1EE]">{snap.name}</div>
                  <div className="text-[11px] text-[#6B6B6E] font-mono">{snap.date} • {snap.size}</div>
                </div>
                <button
                  type="button"
                  onClick={() => alert(`Restoring from ${snap.name}`)}
                  className="px-3 py-1.5 bg-[#1C1C1F] hover:bg-[#2A2A2E] text-xs text-[#F2F1EE] border border-white/[0.08] rounded-lg font-mono font-medium cursor-pointer transition-colors"
                >
                  Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 12. Audit Logs */}
      {activeTab === 'audit_logs' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Immutable Security Audit Trail</h2>
              <p className="text-xs text-[#A8A8AB]">Chronological log of administrative actions, API calls, and security events.</p>
            </div>
            <button
              onClick={() => alert('Exporting audit logs as CSV/JSON')}
              className="px-3.5 py-1.5 bg-[#1C1C1F] hover:bg-[#2A2A2E] text-[#F2F1EE] border border-white/[0.08] rounded-lg text-xs font-mono font-medium cursor-pointer transition-colors"
            >
              Export CSV
            </button>
          </div>

          <div className="space-y-2 font-mono text-xs">
            {[
              { time: '2024-05-16 10:25:12', user: 'Navi Yanka', action: 'AUTH_SUCCESS', ip: '127.0.0.1', details: 'Operator session authenticated with 2FA' },
              { time: '2024-05-16 09:41:00', user: 'SYSTEM', action: 'PIPELINE_TRIGGER', ip: '10.0.4.12', details: 'CI/CD runner triggered canary rollout' },
              { time: '2024-05-15 22:15:33', user: 'Elena Rostova', action: 'KEY_REVOKED', ip: '192.168.1.5', details: 'API Key #k-9182 revoked by security lead' },
              { time: '2024-05-15 17:04:19', user: 'Marcus Vance', action: 'BUDGET_ADJUST', ip: '127.0.0.1', details: 'Daily spend limit raised to $250.00' },
            ].map((log, i) => (
              <div key={i} className="p-3 bg-[#0A0A0B] border border-white/[0.04] rounded-lg flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <span className="text-[#6B6B6E] text-[11px]">{log.time}</span>
                  <span className="text-emerald-400 font-semibold text-[11px]">{log.action}</span>
                  <span className="text-[#F2F1EE]">{log.details}</span>
                </div>
                <span className="text-[#FFB020] text-[11px]">{log.user} ({log.ip})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 13. Appearance */}
      {activeTab === 'appearance' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Appearance & UI Theming</h2>
              <p className="text-xs text-[#A8A8AB]">Visual accents, font scales, and simulation render settings.</p>
            </div>
            <button
              onClick={onSaveToast}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
            >
              Apply Theme
            </button>
          </div>

          <div className="space-y-4">
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-3">
              <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Accent Highlight Palette</label>
              <div className="flex items-center gap-3">
                {[
                  { name: 'Nexus Gold (Active)', color: '#FFB020', active: true },
                  { name: 'Emerald Ops', color: '#10B981', active: false },
                  { name: 'Electric Cyan', color: '#06B6D4', active: false },
                  { name: 'Pure Amber', color: '#F59E0B', active: false },
                ].map((palette, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-mono cursor-pointer transition-all ${
                      palette.active
                        ? 'bg-[#1C1C1F] border border-[#FFB020]/50 text-[#FFB020]'
                        : 'bg-[#0A0A0B] border border-white/[0.08] hover:border-white/[0.3] text-[#A8A8AB]'
                    }`}
                  >
                    <span className="w-3 h-3 rounded-full" style={{ backgroundColor: palette.color }} />
                    <span>{palette.name}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 14. Advanced */}
      {activeTab === 'advanced' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
            <div>
              <h2 className="text-lg font-semibold text-[#F2F1EE]">Advanced & Developer Config</h2>
              <p className="text-xs text-[#A8A8AB]">Low-level JSON runtime overrides and engine flags.</p>
            </div>
            <button
              onClick={onSaveToast}
              className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
            >
              Deploy Overrides
            </button>
          </div>

          <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-xl space-y-2">
            <label className="block text-xs font-semibold text-[#F2F1EE] font-mono">Orchestrator Hyperparameters (JSON)</label>
            <textarea
              rows={8}
              defaultValue={`{
  "max_concurrent_agents": 64,
  "default_temperature": 0.2,
  "context_compression_ratio": 0.85,
  "speculative_decoding": true,
  "memory_prune_threshold_days": 180,
  "telemetry_sample_rate": 1.0
}`}
              className="w-full font-mono text-xs p-3 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-emerald-400 outline-none"
            />
          </div>
        </div>
      )}
    </div>
  );
}
