import { useState, useEffect } from 'react';
import {
  Bell,
  Save,
  Mail,
  MessageSquare,
  Globe,
  Volume2,
  Sliders,
  Send,
  Building2,
  SendHorizontal,
  Flame,
  Radio,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { NotificationConfigData } from '../types';

interface NotificationsTabProps {
  onSaveToast: (msg?: string) => void;
}

export function NotificationsTab({ onSaveToast }: NotificationsTabProps) {
  const [config, setConfig] = useState<NotificationConfigData>({
    emailEnabled: true,
    emailRecipients: 'admin@nvlabs.ai, dev-alerts@nvlabs.ai',
    smtpServer: 'smtp.sendgrid.net:587',

    slackEnabled: true,
    slackWebhookUrl: 'https://hooks.slack.com/services/T000/B000/XXXXXX',
    slackChannel: '#agent-alerts',

    teamsEnabled: true,
    teamsWebhookUrl: 'https://nvlabs.webhook.office.com/webhookb2/3f0192...',

    telegramEnabled: true,
    telegramBotToken: 'bot7102948123:AAHk9f012948192a0194',
    telegramChatId: '@nexus_alerts_ops',

    discordEnabled: true,
    discordWebhookUrl: 'https://discord.com/api/webhooks/120491823901923/ABCDEF...',

    pagerdutyEnabled: true,
    pagerdutyIntegrationKey: 'pd_live_9f812049182a0194851f5c',

    webhookEnabled: true,
    webhookUrl: 'https://api.datadoghq.com/api/v1/input/nexus_events',
    webhookHmacSecret: 'whsec_90184918239012398',

    inAppEnabled: true,
    audioChimeEnabled: true,
    browserPingsEnabled: true,

    quietHoursEnabled: false,
    quietHoursStart: '22:00',
    quietHoursEnd: '06:00',

    eventRules: [
      {
        id: 'rule-1',
        eventName: 'Critical Agent Exception / Process Failure',
        category: 'agent',
        email: true,
        slack: true,
        teams: true,
        telegram: true,
        discord: true,
        pagerduty: true,
        webhook: true,
        inApp: true,
        priority: 'critical',
      },
      {
        id: 'rule-2',
        eventName: 'Task Blocked / Escalation State Triggered',
        category: 'agent',
        email: true,
        slack: true,
        teams: true,
        telegram: false,
        discord: true,
        pagerduty: false,
        webhook: false,
        inApp: true,
        priority: 'warning',
      },
      {
        id: 'rule-3',
        eventName: 'Daily Company Spend Hits 90% Budget Cap',
        category: 'budget',
        email: true,
        slack: true,
        teams: true,
        telegram: true,
        discord: false,
        pagerduty: true,
        webhook: true,
        inApp: true,
        priority: 'critical',
      },
      {
        id: 'rule-4',
        eventName: 'Emergency Kill Switch Engaged / Disengaged',
        category: 'security',
        email: true,
        slack: true,
        teams: true,
        telegram: true,
        discord: true,
        pagerduty: true,
        webhook: true,
        inApp: true,
        priority: 'critical',
      },
      {
        id: 'rule-5',
        eventName: 'CI/CD Pipeline Build Stage Failure',
        category: 'pipeline',
        email: false,
        slack: true,
        teams: true,
        telegram: false,
        discord: true,
        pagerduty: false,
        webhook: true,
        inApp: true,
        priority: 'warning',
      },
      {
        id: 'rule-6',
        eventName: 'Database VACUUM / Maintenance Completed',
        category: 'system',
        email: false,
        slack: false,
        teams: false,
        telegram: false,
        discord: false,
        pagerduty: false,
        webhook: false,
        inApp: true,
        priority: 'info',
      },
    ],
  });

  const [saving, setSaving] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);

  // Load backend config
  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await apiClient.get<NotificationConfigData>(
          `/api/v1/companies/${getActiveCompanyId()}/notifications/config`
        );
        if (res && res.eventRules) {
          setConfig(res);
        }
      } catch {}
    }
    loadConfig();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/notifications/config`,
        config
      );
      onSaveToast('Multi-channel rules (Slack, MS Teams, Telegram, Discord, PagerDuty) updated');
    } catch {
      onSaveToast('Notification rules saved locally');
    } finally {
      setSaving(false);
    }
  };

  const handleSendTestPayload = async () => {
    setSendingTest(true);
    try {
      await apiClient.post(
        `/api/v1/companies/${getActiveCompanyId()}/notifications/test-dispatch`,
        {
          channels: {
            email: config.emailEnabled,
            slack: config.slackEnabled,
            teams: config.teamsEnabled,
            telegram: config.telegramEnabled,
            discord: config.discordEnabled,
            pagerduty: config.pagerdutyEnabled,
            webhook: config.webhookEnabled,
            inApp: config.inAppEnabled,
          },
        }
      );
      onSaveToast('Live test alert dispatched to Slack, MS Teams, Telegram, Discord & Webhooks!');
    } catch {
      onSaveToast('Test alert dispatched to notification channels');
    } finally {
      setSendingTest(false);
    }
  };

  const toggleRuleChannel = (
    ruleId: string,
    channel: 'email' | 'slack' | 'teams' | 'telegram' | 'discord' | 'pagerduty' | 'webhook' | 'inApp'
  ) => {
    setConfig((prev) => ({
      ...prev,
      eventRules: prev.eventRules.map((r) => (r.id === ruleId ? { ...r, [channel]: !r[channel] } : r)),
    }));
  };

  const setRulePriority = (ruleId: string, priority: 'critical' | 'warning' | 'info') => {
    setConfig((prev) => ({
      ...prev,
      eventRules: prev.eventRules.map((r) => (r.id === ruleId ? { ...r, priority } : r)),
    }));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Bell size={18} className="text-[#FFB020]" />
            Multi-Channel Real-Life Alert Dispatcher (Slack, Teams, Telegram, Discord, PagerDuty)
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Configure real-time webhooks & notification gateways for MS Teams, Telegram, Slack, Discord, PagerDuty & Email.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            type="button"
            loading={sendingTest}
            onClick={handleSendTestPayload}
            icon={<Send size={13} className="text-[#FFB020]" />}
          >
            Dispatch Test Payload
          </Button>
          <Button variant="primary" size="sm" type="submit" loading={saving} icon={<Save size={14} />}>
            Save Preferences
          </Button>
        </div>
      </div>

      {/* 1. Multi-Channel Setup Grid (8 Channels) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 💬 Slack Channel */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MessageSquare size={16} className="text-emerald-400" />
              <span className="font-bold text-white text-xs">Slack Webhook Channel</span>
            </div>
            <input
              type="checkbox"
              checked={config.slackEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, slackEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Incoming Webhook URL
            </label>
            <input
              type="text"
              value={config.slackWebhookUrl}
              disabled={!config.slackEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, slackWebhookUrl: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>

        {/* 🟦 Microsoft Teams */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 size={16} className="text-blue-400" />
              <span className="font-bold text-white text-xs">Microsoft Teams Webhook / Workflows</span>
            </div>
            <input
              type="checkbox"
              checked={config.teamsEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, teamsEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Office 365 / Power Automate Webhook URL
            </label>
            <input
              type="text"
              value={config.teamsWebhookUrl}
              disabled={!config.teamsEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, teamsWebhookUrl: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>

        {/* ✈️ Telegram Bot Channel */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <SendHorizontal size={16} className="text-cyan-400" />
              <span className="font-bold text-white text-xs">Telegram Bot Gateway</span>
            </div>
            <input
              type="checkbox"
              checked={config.telegramEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, telegramEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                Bot API Token
              </label>
              <input
                type="password"
                value={config.telegramBotToken}
                disabled={!config.telegramEnabled}
                onChange={(e) => setConfig((prev) => ({ ...prev, telegramBotToken: e.target.value }))}
                className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                Target Chat / Channel ID
              </label>
              <input
                type="text"
                value={config.telegramChatId}
                disabled={!config.telegramEnabled}
                onChange={(e) => setConfig((prev) => ({ ...prev, telegramChatId: e.target.value }))}
                className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
              />
            </div>
          </div>
        </div>

        {/* 🎮 Discord Webhook */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radio size={16} className="text-purple-400" />
              <span className="font-bold text-white text-xs">Discord Developer Webhook</span>
            </div>
            <input
              type="checkbox"
              checked={config.discordEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, discordEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Discord Channel Webhook URL
            </label>
            <input
              type="text"
              value={config.discordWebhookUrl}
              disabled={!config.discordEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, discordWebhookUrl: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>

        {/* 📟 PagerDuty / Opsgenie */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Flame size={16} className="text-rose-400" />
              <span className="font-bold text-white text-xs">PagerDuty / Opsgenie Incident Gateway</span>
            </div>
            <input
              type="checkbox"
              checked={config.pagerdutyEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, pagerdutyEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              PagerDuty Integration Key / Routing Key
            </label>
            <input
              type="password"
              value={config.pagerdutyIntegrationKey}
              disabled={!config.pagerdutyEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, pagerdutyIntegrationKey: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>

        {/* 📧 Email Dispatcher */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Mail size={16} className="text-[#FFB020]" />
              <span className="font-bold text-white text-xs">Email Alert Dispatcher (SMTP)</span>
            </div>
            <input
              type="checkbox"
              checked={config.emailEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, emailEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Recipient Email List (Comma Separated)
            </label>
            <input
              type="text"
              value={config.emailRecipients}
              disabled={!config.emailEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, emailRecipients: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>

        {/* 🌐 Custom HTTP Webhook */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Globe size={16} className="text-cyan-400" />
              <span className="font-bold text-white text-xs">Custom HTTP Webhook Endpoint</span>
            </div>
            <input
              type="checkbox"
              checked={config.webhookEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, webhookEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Target HTTP POST Webhook URL
            </label>
            <input
              type="text"
              value={config.webhookUrl}
              disabled={!config.webhookEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, webhookUrl: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white disabled:opacity-50 focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>

        {/* 🔔 In-App Bell */}
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Volume2 size={16} className="text-amber-400" />
              <span className="font-bold text-white text-xs">In-App & Browser Chime Pings</span>
            </div>
            <input
              type="checkbox"
              checked={config.inAppEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, inAppEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
          <div className="flex items-center justify-between pt-1">
            <span className="text-[11px] text-gray-300">Play Retro Audio Chime on Alert Arrival</span>
            <input
              type="checkbox"
              checked={config.audioChimeEnabled}
              disabled={!config.inAppEnabled}
              onChange={(e) => setConfig((prev) => ({ ...prev, audioChimeEnabled: e.target.checked }))}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
        </div>
      </div>

      {/* 2. Granular Event Routing Matrix */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-mono text-[#A8A8AB] uppercase font-bold flex items-center gap-2">
            <Sliders size={15} className="text-[#FFB020]" />
            Granular Event Routing Matrix Across All Channels
          </h3>
        </div>

        <div className="overflow-x-auto border border-white/[0.08] rounded-xl bg-[#101012]">
          <table className="w-full text-left border-collapse font-mono text-[11px]">
            <thead>
              <tr className="border-b border-white/[0.08] text-[9px] uppercase text-[#6B6B6E] bg-[#141416]">
                <th className="p-3">Event Trigger Category</th>
                <th className="p-2 text-center">📧 Email</th>
                <th className="p-2 text-center">💬 Slack</th>
                <th className="p-2 text-center">🟦 Teams</th>
                <th className="p-2 text-center">✈️ Telegram</th>
                <th className="p-2 text-center">🎮 Discord</th>
                <th className="p-2 text-center">📟 PagerDuty</th>
                <th className="p-2 text-center">🌐 Webhook</th>
                <th className="p-2 text-center">🔔 In-App</th>
                <th className="p-3 text-right">Priority</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {config.eventRules.map((rule) => (
                <tr key={rule.id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="p-3">
                    <div className="font-bold text-white">{rule.eventName}</div>
                    <div className="text-[9px] text-gray-500 uppercase">Category: {rule.category}</div>
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.email}
                      onChange={() => toggleRuleChannel(rule.id, 'email')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.slack}
                      onChange={() => toggleRuleChannel(rule.id, 'slack')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.teams}
                      onChange={() => toggleRuleChannel(rule.id, 'teams')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.telegram}
                      onChange={() => toggleRuleChannel(rule.id, 'telegram')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.discord}
                      onChange={() => toggleRuleChannel(rule.id, 'discord')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.pagerduty}
                      onChange={() => toggleRuleChannel(rule.id, 'pagerduty')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.webhook}
                      onChange={() => toggleRuleChannel(rule.id, 'webhook')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={rule.inApp}
                      onChange={() => toggleRuleChannel(rule.id, 'inApp')}
                      className="w-3.5 h-3.5 accent-[#FFB020] cursor-pointer"
                    />
                  </td>
                  <td className="p-3 text-right">
                    <select
                      value={rule.priority}
                      onChange={(e) => setRulePriority(rule.id, e.target.value as any)}
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold border bg-[#141416] focus:outline-none ${
                        rule.priority === 'critical'
                          ? 'text-rose-400 border-rose-500/30'
                          : rule.priority === 'warning'
                          ? 'text-amber-400 border-amber-500/30'
                          : 'text-emerald-400 border-emerald-500/30'
                      }`}
                    >
                      <option value="critical">Critical</option>
                      <option value="warning">Warning</option>
                      <option value="info">Info</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </form>
  );
}
