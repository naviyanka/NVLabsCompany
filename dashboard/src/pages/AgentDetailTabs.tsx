import { useState, useCallback } from 'react';
import type { Agent } from '@/types/agent';
import { agentsApi } from '@/api/agents';
import {
  CheckCircle2, BarChart3, Clock, Layers, Signal, ArrowUpRight, ChevronDown,
  GitCommit, Brain, Play, FileText, Rocket, Eye, Plus, Pause, Power,
  Save, Terminal, Database, Shield, Zap, AlertTriangle, Settings as SettingsIcon,
  RefreshCw, Download, Trash2,
} from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell } from 'recharts';

// ═══════════════════════════════════════════════════════════════════════════════
// SKILLS TAB
// ═══════════════════════════════════════════════════════════════════════════════

interface SkillsTabProps {
  skills: Array<{ name: string; proficiency: number; color: string; experience: string; lastUsed: string }>;
  capabilities: string[];
}

export function SkillsTab({ skills, capabilities }: SkillsTabProps) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Skills Table */}
        <div className="lg:col-span-2 p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
          <h3 className="text-white font-semibold text-sm mb-4">Skills & Proficiency</h3>
          <table className="w-full text-xs">
            <thead><tr className="text-gray-400 border-b border-white/[0.05]"><th className="text-left pb-2">Skill</th><th className="text-left pb-2">Proficiency</th><th className="text-left pb-2">Experience</th><th className="text-left pb-2">Last Used</th><th className="text-left pb-2">Status</th></tr></thead>
            <tbody>
              {skills.map(s => (
                <tr key={s.name} className="border-b border-white/[0.03]">
                  <td className="py-3 text-white font-medium">{s.name}</td>
                  <td className="py-3"><div className="flex items-center gap-2"><div className="w-24 h-2 bg-white/[0.08] rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${s.proficiency}%`, backgroundColor: s.color }} /></div><span className="text-gray-400">{s.proficiency}%</span></div></td>
                  <td className="py-3 text-gray-400">{s.experience}</td>
                  <td className="py-3 text-gray-400">{s.lastUsed}</td>
                  <td className="py-3"><span className="px-2 py-0.5 text-[10px] rounded-full bg-green-500/15 text-green-400">Active</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Capabilities */}
        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
          <h3 className="text-white font-semibold text-sm mb-4">All Capabilities</h3>
          <div className="flex flex-wrap gap-2">
            {capabilities.map(cap => (
              <span key={cap} className="px-2.5 py-1 text-xs text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-lg">
                {cap.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
              </span>
            ))}
          </div>
          {capabilities.length === 0 && <p className="text-xs text-gray-500">No capabilities defined</p>}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MEMORY TAB
// ═══════════════════════════════════════════════════════════════════════════════

export function MemoryTab({ agentId, agentName }: { agentId: string; agentName: string }) {
  const memories = [
    { id: '1', content: 'Learned that PostgreSQL connection pooling improves throughput by 40%', tier: 'warm', importance: 0.8, time: '2h ago' },
    { id: '2', content: 'API rate limiting should use sliding window algorithm for accuracy', tier: 'warm', importance: 0.7, time: '5h ago' },
    { id: '3', content: 'Team prefers explicit error messages over generic 500 responses', tier: 'hot', importance: 0.9, time: '1d ago' },
    { id: '4', content: 'Redis pub/sub is preferred for real-time notifications', tier: 'warm', importance: 0.6, time: '2d ago' },
    { id: '5', content: 'Always run migrations before deploying to staging', tier: 'cold', importance: 0.5, time: '5d ago' },
  ];

  const tierColors: Record<string, string> = { hot: '#EF4444', warm: '#F59E0B', cold: '#3B82F6' };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold">Memory Store — {agentName}</h3>
        <div className="flex gap-2">
          <span className="flex items-center gap-1 text-[10px] text-red-400"><span className="w-2 h-2 rounded-full bg-red-400" />Hot</span>
          <span className="flex items-center gap-1 text-[10px] text-yellow-400"><span className="w-2 h-2 rounded-full bg-yellow-400" />Warm</span>
          <span className="flex items-center gap-1 text-[10px] text-blue-400"><span className="w-2 h-2 rounded-full bg-blue-400" />Cold</span>
        </div>
      </div>
      <div className="space-y-2">
        {memories.map(m => (
          <div key={m.id} className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06] flex items-start gap-3">
            <div className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ backgroundColor: tierColors[m.tier] }} />
            <div className="flex-1">
              <p className="text-xs text-gray-200">{m.content}</p>
              <div className="flex items-center gap-3 mt-1">
                <span className="text-[10px] text-gray-500">{m.time}</span>
                <span className="text-[10px] text-gray-500">Importance: {m.importance}</span>
                <span className="text-[10px] text-gray-500 capitalize">{m.tier} tier</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TASKS TAB
// ═══════════════════════════════════════════════════════════════════════════════

export function TasksTab({ agentName }: { agentName: string }) {
  const tasks = [
    { id: '1', title: 'Implement user authentication', status: 'in_progress', priority: 3, progress: 75 },
    { id: '2', title: 'Optimize database queries', status: 'pending', priority: 2, progress: 0 },
    { id: '3', title: 'API rate limiting implementation', status: 'pending', priority: 1, progress: 0 },
    { id: '4', title: 'Write unit tests for payment module', status: 'pending', priority: 1, progress: 0 },
    { id: '5', title: 'Fix session timeout bug', status: 'completed', priority: 3, progress: 100 },
    { id: '6', title: 'Add logging middleware', status: 'completed', priority: 2, progress: 100 },
  ];

  const statusColors: Record<string, { label: string; color: string }> = {
    in_progress: { label: 'In Progress', color: '#22C55E' },
    pending: { label: 'Pending', color: '#F59E0B' },
    completed: { label: 'Completed', color: '#3B82F6' },
  };
  const priorityLabels: Record<number, { label: string; color: string }> = {
    3: { label: 'High', color: '#EF4444' }, 2: { label: 'Medium', color: '#F59E0B' }, 1: { label: 'Low', color: '#22C55E' },
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold">Task Queue — {agentName}</h3>
        <button className="flex items-center gap-1 text-xs text-teal-400"><Plus size={12} /> Assign Task</button>
      </div>
      <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
        <table className="w-full text-xs">
          <thead><tr className="text-gray-400 border-b border-white/[0.05]"><th className="text-left pb-2">Task</th><th className="text-left pb-2">Status</th><th className="text-left pb-2">Priority</th><th className="text-left pb-2">Progress</th></tr></thead>
          <tbody>
            {tasks.map(t => (
              <tr key={t.id} className="border-b border-white/[0.03]">
                <td className="py-3 text-white">{t.title}</td>
                <td className="py-3"><span className="px-2 py-0.5 text-[10px] rounded-full" style={{ color: statusColors[t.status].color, backgroundColor: statusColors[t.status].color + '15' }}>{statusColors[t.status].label}</span></td>
                <td className="py-3"><span className="flex items-center gap-1 text-[10px]" style={{ color: priorityLabels[t.priority].color }}><span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: priorityLabels[t.priority].color }} />{priorityLabels[t.priority].label}</span></td>
                <td className="py-3"><div className="flex items-center gap-2"><div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden"><div className="h-full rounded-full bg-teal-500" style={{ width: `${t.progress}%` }} /></div><span className="text-gray-400">{t.progress}%</span></div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// PERFORMANCE TAB
// ═══════════════════════════════════════════════════════════════════════════════

export function PerformanceTab({ perfData, agentName }: { perfData: any[]; agentName: string }) {
  const costData = [
    { day: 'Mon', cost: 12 }, { day: 'Tue', cost: 18 }, { day: 'Wed', cost: 15 },
    { day: 'Thu', cost: 22 }, { day: 'Fri', cost: 19 }, { day: 'Sat', cost: 8 }, { day: 'Sun', cost: 5 },
  ];

  return (
    <div className="space-y-4">
      <h3 className="text-white font-semibold">Performance Analytics — {agentName}</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
          <h4 className="text-sm text-white font-medium mb-3">Tasks & Success Rate (7 Days)</h4>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={perfData}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" /><XAxis dataKey="date" stroke="#6b7280" fontSize={10} /><YAxis stroke="#6b7280" fontSize={10} /><Tooltip contentStyle={{ backgroundColor: '#1a1b2e', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, color: '#fff', fontSize: 11 }} /><Line type="monotone" dataKey="tasksCompleted" stroke="#10b981" strokeWidth={2} dot={false} /><Line type="monotone" dataKey="successRate" stroke="#8b5cf6" strokeWidth={2} dot={false} /></LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
          <h4 className="text-sm text-white font-medium mb-3">Daily Cost (cents)</h4>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={costData}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" /><XAxis dataKey="day" stroke="#6b7280" fontSize={10} /><YAxis stroke="#6b7280" fontSize={10} /><Tooltip contentStyle={{ backgroundColor: '#1a1b2e', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, color: '#fff', fontSize: 11 }} /><Bar dataKey="cost" fill="#3b82f6" radius={[4, 4, 0, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-3">
        {[{ label: 'Avg Latency', value: '2.4s', color: '#06B6D4' }, { label: 'Error Rate', value: '1.4%', color: '#EF4444' }, { label: 'Tokens/Day', value: '41.2K', color: '#8B5CF6' }, { label: 'Cost/Day', value: '$0.14', color: '#F59E0B' }].map(m => (
          <div key={m.label} className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]"><p className="text-[10px] text-gray-400">{m.label}</p><p className="text-lg font-bold mt-1" style={{ color: m.color }}>{m.value}</p></div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// SETTINGS TAB
// ═══════════════════════════════════════════════════════════════════════════════

export function SettingsTab({ agent, refetch }: { agent: Agent; refetch: () => void }) {
  const [form, setForm] = useState({ name: agent.name, title: agent.title || '', role: agent.role, model: agent.model || '', budget_monthly_cents: agent.budget_monthly_cents, responsibilities: agent.responsibilities || '', objectives: agent.objectives || '' });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try { await agentsApi.update(agent.id, form); refetch(); alert('Saved!'); } catch (err: any) { alert(err.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-4 max-w-2xl">
      <h3 className="text-white font-semibold">Agent Settings</h3>
      <div className="p-5 rounded-xl bg-white/[0.03] border border-white/[0.06] space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div><label className="block text-xs text-gray-400 mb-1">Name</label><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm" /></div>
          <div><label className="block text-xs text-gray-400 mb-1">Title</label><input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm" /></div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div><label className="block text-xs text-gray-400 mb-1">Role</label><input value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm" /></div>
          <div><label className="block text-xs text-gray-400 mb-1">Model</label><input value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm" /></div>
        </div>
        <div><label className="block text-xs text-gray-400 mb-1">Monthly Budget (cents)</label><input type="number" value={form.budget_monthly_cents} onChange={e => setForm({ ...form, budget_monthly_cents: parseInt(e.target.value) || 0 })} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm" /></div>
        <div><label className="block text-xs text-gray-400 mb-1">Responsibilities</label><textarea value={form.responsibilities} onChange={e => setForm({ ...form, responsibilities: e.target.value })} rows={3} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm resize-none" /></div>
        <div><label className="block text-xs text-gray-400 mb-1">Objectives</label><textarea value={form.objectives} onChange={e => setForm({ ...form, objectives: e.target.value })} rows={3} className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm resize-none" /></div>
        <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-4 py-2 bg-green-500/20 text-green-400 text-sm font-medium rounded-lg hover:bg-green-500/30 disabled:opacity-50"><Save size={14} />{saving ? 'Saving...' : 'Save Changes'}</button>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOGS TAB
// ═══════════════════════════════════════════════════════════════════════════════

export function LogsTab({ agentName }: { agentName: string }) {
  const logs = [
    { time: '14:08:33', level: 'INFO', message: 'Agent session initialized successfully' },
    { time: '14:08:34', level: 'INFO', message: 'Connected to adapter: kiro-cli' },
    { time: '14:08:35', level: 'INFO', message: 'Heartbeat registered — status: ready' },
    { time: '14:09:01', level: 'DEBUG', message: 'Received task assignment: implement auth' },
    { time: '14:09:02', level: 'INFO', message: 'Task execution started — task_7f2a9c' },
    { time: '14:09:15', level: 'DEBUG', message: 'LLM call: 1,240 input tokens, 890 output tokens' },
    { time: '14:09:18', level: 'INFO', message: 'Step 1/4 completed — analyzing requirements' },
    { time: '14:10:42', level: 'WARN', message: 'Rate limit approaching: 85% of minute quota used' },
    { time: '14:11:03', level: 'INFO', message: 'Step 2/4 completed — generating implementation' },
    { time: '14:12:30', level: 'ERROR', message: 'Transient API error (429) — retrying in 2s' },
    { time: '14:12:33', level: 'INFO', message: 'Retry successful — continuing execution' },
    { time: '14:13:05', level: 'INFO', message: 'Step 3/4 completed — running tests' },
  ];

  const levelColors: Record<string, string> = { INFO: '#22C55E', DEBUG: '#6B7280', WARN: '#F59E0B', ERROR: '#EF4444' };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold">Execution Logs — {agentName}</h3>
        <button className="flex items-center gap-1 text-xs text-gray-400 hover:text-white"><Download size={12} /> Export</button>
      </div>
      <div className="p-4 rounded-xl bg-[#050a14] border border-white/[0.06] font-mono text-xs space-y-1 max-h-[500px] overflow-y-auto">
        {logs.map((log, i) => (
          <div key={i} className="flex gap-3">
            <span className="text-gray-500 flex-shrink-0">{log.time}</span>
            <span className="flex-shrink-0 w-12 text-right" style={{ color: levelColors[log.level] }}>[{log.level}]</span>
            <span className="text-gray-300">{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ACTIVITY TAB
// ═══════════════════════════════════════════════════════════════════════════════

export function ActivityTab({ agentName }: { agentName: string }) {
  const activities = [
    { icon: 'check', text: 'Completed task: Fix user session bug', time: 'Today, 10:15 AM', category: 'task' },
    { icon: 'git', text: 'Committed changes to auth_service.py', time: 'Today, 09:49 AM', category: 'code' },
    { icon: 'brain', text: 'Memory updated: Added 3 new insights from task execution', time: 'Today, 09:32 AM', category: 'memory' },
    { icon: 'play', text: 'Started task: Implement rate limiting middleware', time: 'Today, 09:21 AM', category: 'task' },
    { icon: 'pr', text: 'Reviewed pull request #128 — approved with comments', time: 'Yesterday, 04:30 PM', category: 'code' },
    { icon: 'deploy', text: 'Deployed auth module to staging environment', time: 'Yesterday, 03:15 PM', category: 'deploy' },
    { icon: 'check', text: 'Completed task: Database migration for users table', time: 'Yesterday, 01:20 PM', category: 'task' },
    { icon: 'brain', text: 'Learned: Team prefers explicit error responses', time: 'Yesterday, 11:00 AM', category: 'memory' },
    { icon: 'play', text: 'Woken from idle state — assigned to sprint backlog', time: '2 days ago, 09:00 AM', category: 'lifecycle' },
  ];

  const categoryColors: Record<string, string> = { task: '#22C55E', code: '#3B82F6', memory: '#8B5CF6', deploy: '#EC4899', lifecycle: '#F59E0B' };
  const iconMap: Record<string, any> = { check: CheckCircle2, git: GitCommit, brain: Brain, play: Play, pr: FileText, deploy: Rocket };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-white font-semibold">Activity Timeline — {agentName}</h3>
        <div className="flex gap-2">
          {Object.entries(categoryColors).map(([cat, color]) => (
            <span key={cat} className="flex items-center gap-1 text-[10px] text-gray-400 capitalize"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />{cat}</span>
          ))}
        </div>
      </div>
      <div className="space-y-0">
        {activities.map((a, i) => {
          const Icon = iconMap[a.icon] || CheckCircle2;
          return (
            <div key={i} className="flex gap-4 pb-4 relative">
              {i < activities.length - 1 && <div className="absolute left-[11px] top-6 bottom-0 w-px bg-white/[0.06]" />}
              <div className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center" style={{ backgroundColor: categoryColors[a.category] + '20' }}>
                <Icon size={12} style={{ color: categoryColors[a.category] }} />
              </div>
              <div className="flex-1 pt-0.5">
                <p className="text-xs text-gray-200">{a.text}</p>
                <p className="text-[10px] text-gray-500 mt-0.5">{a.time}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
