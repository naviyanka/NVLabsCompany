import { useState, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useApi } from '@/hooks/useApi';
import { agentsApi } from '@/api/agents';
import type { Agent } from '@/types/agent';
import {
  ChevronRight,
  ChevronDown,
  ArrowLeft,
  Play,
  Pause,
  Trash2,
  Edit,
  Cpu,
  Activity,
  Zap,
  Coffee,
  AlertTriangle,
  WifiOff,
  Clock,
  CheckCircle2,
  BarChart3,
  Layers,
  Signal,
  ArrowUpRight,
  GitCommit,
  Brain,
  FileText,
  Rocket,
  MessageSquare,
  Eye,
  Plus,
  Power,
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { SkillsTab, MemoryTab, TasksTab, PerformanceTab, SettingsTab, LogsTab, ActivityTab } from './AgentDetailTabs';
const STATUS_CONFIG: Record<string, { label: string; color: string; icon: any }> = {
  idle: { label: 'Idle', color: '#3B82F6', icon: Coffee },
  ready: { label: 'Ready', color: '#22C55E', icon: Zap },
  executing: { label: 'Working', color: '#22C55E', icon: Activity },
  paused: { label: 'Paused', color: '#EAB308', icon: Coffee },
  error: { label: 'Error', color: '#EF4444', icon: AlertTriangle },
  terminated: { label: 'Terminated', color: '#64748B', icon: WifiOff },
};

// Deterministic mock performance data from agent name seed
function generatePerfData(name: string) {
  const seed = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  return Array.from({ length: 7 }, (_, i) => ({
    date: `May ${10 + i}`,
    tasksCompleted: 50 + ((seed * (i + 1)) % 45),
    successRate: 90 + ((seed * (i + 2)) % 10),
  }));
}

const ACTIVITY_ITEMS = [
  { icon: 'check', text: 'Completed assigned task', time: '10:15 AM' },
  { icon: 'git', text: 'Committed code changes', time: '09:49 AM' },
  { icon: 'brain', text: 'Memory updated: new insights', time: '09:32 AM' },
  { icon: 'play', text: 'Started new task execution', time: '09:21 AM' },
  { icon: 'pr', text: 'Reviewed pull request', time: 'Yesterday' },
  { icon: 'deploy', text: 'Deployed to staging', time: 'Yesterday' },
];

const TABS = ['Overview', 'Skills', 'Memory', 'Tasks', 'Performance', 'Settings', 'Logs', 'Activity'];

export function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [actionLoading, setActionLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('Overview');
  const [showActions, setShowActions] = useState(false);
  const [showTalkModal, setShowTalkModal] = useState(false);
  const [talkMessage, setTalkMessage] = useState('');
  const [talkResponse, setTalkResponse] = useState<string | null>(null);

  const { data: agent, loading, error, refetch } = useApi<Agent>(
    () => agentsApi.get(id!),
    [id],
  );

  const perfData = useMemo(() => agent ? generatePerfData(agent.name) : [], [agent]);

  const handleWake = useCallback(async () => {
    if (!id) return;
    setActionLoading(true);
    try { await agentsApi.wake(id); refetch(); } catch (err: any) { alert(err.message); }
    finally { setActionLoading(false); }
  }, [id, refetch]);

  const handlePause = useCallback(async () => {
    if (!id) return;
    setActionLoading(true);
    try { await agentsApi.pause(id); refetch(); } catch (err: any) { alert(err.message); }
    finally { setActionLoading(false); }
  }, [id, refetch]);

  const handleDelete = useCallback(async () => {
    if (!id || !agent) return;
    if (!confirm(`Delete "${agent.name}"? This cannot be undone.`)) return;
    setActionLoading(true);
    try { await agentsApi.delete(id); navigate('/agents'); } catch (err: any) { alert(err.message); }
    finally { setActionLoading(false); }
  }, [id, agent, navigate]);

  const handleTalk = useCallback(() => {
    setShowTalkModal(true);
    setTalkMessage('');
    setTalkResponse(null);
  }, []);

  const handleSendMessage = useCallback(async () => {
    if (!talkMessage.trim() || !agent) return;
    setTalkResponse(`[${agent.name}]: I received your message: "${talkMessage}". As a ${agent.role} agent using ${agent.model || agent.adapter_type}, I'm ready to help. (Note: Real LLM response requires agent execution — this is a preview.)`);
  }, [talkMessage, agent]);

  const handleAssignTask = useCallback(() => {
    navigate('/tasks');
  }, [navigate]);

  const handleViewMemory = useCallback(() => {
    navigate('/memory');
  }, [navigate]);

  if (loading) return <div className="flex justify-center py-20"><div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" /></div>;
  if (error || !agent) return <div className="p-8 text-center"><AlertTriangle size={32} className="mx-auto text-red-400 mb-3" /><p className="text-white">Agent not found</p><button onClick={() => navigate('/agents')} className="mt-3 text-sm text-primary-400">← Back</button></div>;

  const sc = STATUS_CONFIG[agent.status] || STATUS_CONFIG.idle;
  const StatusIcon = sc.icon;
  const canWake = agent.status === 'idle' || agent.status === 'paused';
  const canPause = agent.status === 'ready' || agent.status === 'executing';
  const budgetPct = agent.budget_monthly_cents > 0 ? Math.round((agent.spent_monthly_cents / agent.budget_monthly_cents) * 100) : 0;

  // Skills derived from capabilities
  const skills = (agent.capabilities || []).map((cap, i) => ({
    name: cap.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    proficiency: 95 - i * 5,
    color: ['#8b5cf6', '#14b8a6', '#3b82f6', '#06b6d4', '#ef4444', '#f59e0b', '#22c55e'][i % 7],
    experience: `${(2.5 - i * 0.3).toFixed(1)} years`,
    lastUsed: ['2h ago', '1h ago', '3h ago', '5h ago', '1d ago'][i % 5],
  }));

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/agents')} className="text-gray-400 hover:text-white transition-colors">Agents</button>
        <ChevronRight size={14} className="text-gray-500" />
        <span className="text-white font-medium">{agent.name}</span>
      </div>

      {/* ═══ Profile Header ═══ */}
      <div className="p-6 rounded-xl bg-white/[0.03] border border-white/[0.06]">
        <div className="flex flex-col lg:flex-row lg:items-center gap-6">
          {/* Avatar */}
          <div className="relative flex-shrink-0">
            <div className="w-20 h-20 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center">
              <span className="text-3xl font-bold text-white">{agent.name.charAt(0)}</span>
            </div>
            <div className="absolute bottom-0 right-0 w-5 h-5 rounded-full border-2 border-[#0B1626]" style={{ backgroundColor: sc.color }} />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-2xl font-bold text-white">{agent.name}</h1>
              <span className="flex items-center gap-1.5 text-xs" style={{ color: sc.color }}>
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: sc.color }} />
                {sc.label}
              </span>
            </div>
            <span className="inline-block px-2.5 py-0.5 rounded-full text-xs font-medium bg-teal-500/20 text-teal-400 mb-2">
              {agent.title || agent.role} Agent
            </span>
            <p className="text-sm text-gray-400 mb-4">{agent.soul_description || agent.responsibilities || 'AI agent ready for tasks.'}</p>
            <div className="flex flex-wrap items-center gap-4 text-xs text-gray-400">
              <span><span className="text-gray-500">Role:</span> <span className="text-white">{agent.role}</span></span>
              <span className="text-gray-600">|</span>
              <span><span className="text-gray-500">Model:</span> <span className="text-white">{agent.model || agent.adapter_type}</span></span>
              <span className="text-gray-600">|</span>
              <span><span className="text-gray-500">Joined:</span> <span className="text-white">{new Date(agent.created_at).toLocaleDateString()}</span></span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <button onClick={handleTalk} className="flex items-center gap-2 px-4 py-2 border border-teal-500 text-teal-400 rounded-lg text-sm font-medium hover:bg-teal-500/10 transition-colors">
              <MessageSquare size={16} /> Talk to Agent
            </button>
            <div className="relative">
              <button onClick={() => setShowActions(!showActions)} className="flex items-center gap-2 px-4 py-2 bg-white/[0.05] border border-white/[0.08] text-gray-300 rounded-lg text-sm font-medium hover:bg-white/[0.08] transition-colors">
                Actions <ChevronDown size={14} />
              </button>
              {showActions && (
                <div className="absolute right-0 top-full mt-1 w-48 bg-[#0B1626] border border-white/10 rounded-lg shadow-2xl z-30 py-1">
                  {canWake && <DropItem icon={<Play size={14} className="text-green-400" />} label="Wake Agent" onClick={() => { handleWake(); setShowActions(false); }} />}
                  {canPause && <DropItem icon={<Pause size={14} className="text-yellow-400" />} label="Pause Agent" onClick={() => { handlePause(); setShowActions(false); }} />}
                  <DropItem icon={<Plus size={14} className="text-teal-400" />} label="Assign Task" onClick={() => { handleAssignTask(); setShowActions(false); }} />
                  <DropItem icon={<Eye size={14} className="text-blue-400" />} label="View Memory" onClick={() => { handleViewMemory(); setShowActions(false); }} />
                  <DropItem icon={<Edit size={14} className="text-gray-400" />} label="Edit Agent" onClick={() => { navigate(`/agents`); setShowActions(false); }} />
                  <div className="border-t border-white/[0.06] my-1" />
                  <DropItem icon={<Power size={14} className="text-red-400" />} label="Delete Agent" onClick={() => { handleDelete(); setShowActions(false); }} danger />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ═══ Tabs ═══ */}
      <div className="border-b border-white/[0.08]">
        <div className="flex items-center gap-6 overflow-x-auto">
          {TABS.map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className={`pb-3 text-sm font-medium whitespace-nowrap transition-colors ${tab === activeTab ? 'text-teal-400 border-b-2 border-teal-400' : 'text-gray-400 hover:text-gray-200'}`}>
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* ═══ Tab Content ═══ */}
      {activeTab === 'Skills' && <SkillsTab skills={skills} capabilities={agent.capabilities || []} />}
      {activeTab === 'Memory' && <MemoryTab agentId={agent.id} agentName={agent.name} />}
      {activeTab === 'Tasks' && <TasksTab agentName={agent.name} />}
      {activeTab === 'Performance' && <PerformanceTab perfData={perfData} agentName={agent.name} />}
      {activeTab === 'Settings' && <SettingsTab agent={agent} refetch={refetch} />}
      {activeTab === 'Logs' && <LogsTab agentName={agent.name} />}
      {activeTab === 'Activity' && <ActivityTab agentName={agent.name} />}
      {activeTab === 'Overview' && (
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* LEFT */}
        <div className="lg:col-span-5 space-y-4">
          {/* Stat Cards */}
          <div className="grid grid-cols-2 gap-3">
            <MetricCard icon={<CheckCircle2 size={18} />} iconColor="text-green-400" label="Tasks Completed" value="1,248" change="+15% this week" />
            <MetricCard icon={<BarChart3 size={18} />} iconColor="text-purple-400" label="Success Rate" value="98.6%" change="+2.4%" />
            <MetricCard icon={<Clock size={18} />} iconColor="text-blue-400" label="Avg. Response Time" value="2.4s" change="-0.6s" />
            <MetricCard icon={<Layers size={18} />} iconColor="text-orange-400" label="Total Tokens (30d)" value="1.24M" change="+18.7%" />
            <MetricCard icon={<Signal size={18} />} iconColor="text-teal-400" label="Uptime (30d)" value="99.8%" change="+0.3%" className="col-span-2 sm:col-span-1" />
          </div>

          {/* Current Workload */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Current Workload</h3>
              <span className="flex items-center gap-1.5 text-xs text-green-400"><span className="w-1.5 h-1.5 rounded-full bg-green-400" />Live</span>
            </div>
            <div className="bg-dark-bg rounded-lg p-3 border border-white/[0.05] mb-4">
              <p className="text-xs text-gray-400 mb-1">Active Task</p>
              <p className="text-sm text-white font-medium mb-1">{agent.responsibilities?.split(',')[0] || 'Processing assigned work'}</p>
              <p className="text-[10px] text-gray-500 mb-3">Task ID: task_7f2a9c &bull; Started 10:24 AM</p>
              <div className="h-2 bg-white/[0.08] rounded-full overflow-hidden mb-1"><div className="h-full bg-teal-500 rounded-full" style={{ width: '75%' }} /></div>
              <div className="flex items-center justify-between"><span className="text-[10px] text-teal-400">75%</span><span className="text-[10px] text-gray-500">Est. 25m remaining</span></div>
            </div>
            <p className="text-xs text-gray-400 mb-2">Task Queue (3)</p>
            <div className="space-y-2 mb-3">
              {[{ name: 'Optimize database queries', color: '#ef4444', p: 'High' }, { name: 'API rate limiting', color: '#f59e0b', p: 'Medium' }, { name: 'Write unit tests', color: '#10b981', p: 'Low' }].map(t => (
                <div key={t.name} className="flex items-center justify-between"><span className="text-xs text-gray-300">{t.name}</span><span className="flex items-center gap-1.5 text-[10px] text-gray-400"><span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: t.color }} />{t.p} Priority</span></div>
              ))}
            </div>
            <button onClick={() => navigate('/tasks')} className="text-xs text-teal-400 hover:text-teal-300">View All Tasks →</button>
          </div>

          {/* Skills Table */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Skills & Proficiency</h3>
              <button className="text-xs text-teal-400">View All Skills</button>
            </div>
            <table className="w-full text-xs">
              <thead><tr className="text-gray-400 border-b border-white/[0.05]"><th className="text-left pb-2">Skill</th><th className="text-left pb-2">Proficiency</th><th className="text-left pb-2">Experience</th><th className="text-left pb-2">Last Used</th></tr></thead>
              <tbody>
                {skills.slice(0, 5).map(s => (
                  <tr key={s.name} className="border-b border-white/[0.03]">
                    <td className="py-2.5 text-white font-medium">{s.name}</td>
                    <td className="py-2.5"><div className="flex items-center gap-2"><div className="w-20 h-1.5 bg-white/[0.08] rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${s.proficiency}%`, backgroundColor: s.color }} /></div><span className="text-gray-400">{s.proficiency}%</span></div></td>
                    <td className="py-2.5 text-gray-400">{s.experience}</td>
                    <td className="py-2.5 text-gray-400">{s.lastUsed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* CENTER */}
        <div className="lg:col-span-4 space-y-4">
          {/* Performance Chart */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Performance Overview</h3>
              <button className="flex items-center gap-1 text-xs text-gray-400 bg-white/[0.05] px-2 py-1 rounded">7 Days <ChevronDown size={12} /></button>
            </div>
            <div className="flex items-center gap-4 mb-4">
              <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-green-400" /><span className="text-[10px] text-gray-400">Tasks Completed</span></div>
              <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-purple-400" /><span className="text-[10px] text-gray-400">Success Rate %</span></div>
            </div>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={perfData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" stroke="#6b7280" fontSize={10} tickLine={false} axisLine={false} />
                  <YAxis stroke="#6b7280" fontSize={10} tickLine={false} axisLine={false} domain={[0, 100]} />
                  <Tooltip contentStyle={{ backgroundColor: '#1a1b2e', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', color: '#fff', fontSize: '11px' }} />
                  <Line type="monotone" dataKey="tasksCompleted" stroke="#10b981" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="successRate" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-white/[0.08]">
              <MiniStat label="Tasks / Day" value="28.4" color="#10b981" />
              <MiniStat label="Errors / Day" value="0.8" color="#ef4444" />
              <MiniStat label="Rework Rate" value="1.2%" color="#f59e0b" />
            </div>
          </div>

          {/* Recent Activity */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Recent Activity</h3>
              <button className="text-xs text-teal-400">View All</button>
            </div>
            <div className="space-y-3">
              {ACTIVITY_ITEMS.map((item, i) => (
                <div key={i} className="flex items-start gap-3">
                  <ActivityIcon type={item.icon} />
                  <div className="flex-1"><p className="text-xs text-gray-300">{item.text}</p><p className="text-[10px] text-gray-500 mt-0.5">{item.time}</p></div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT SIDEBAR */}
        <div className="lg:col-span-3 space-y-4">
          {/* Agent Information */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Agent Information</h3>
              <button className="text-xs text-gray-400 hover:text-white"><Edit size={12} /> Edit</button>
            </div>
            <div className="space-y-2.5">
              <InfoRow label="Agent ID" value={agent.id.substring(0, 16) + '...'} />
              <InfoRow label="Role" value={agent.title || agent.role} />
              <InfoRow label="Department" value={agent.department_id ? 'Engineering' : 'Unassigned'} />
              <InfoRow label="Team" value={agent.team_id ? 'Core Team' : 'Unassigned'} />
              <InfoRow label="Supervisor" value="Navi Yanka" />
              <InfoRow label="Created" value={new Date(agent.created_at).toLocaleString()} />
              <InfoRow label="Last Updated" value={new Date(agent.updated_at).toLocaleString()} />
              <div className="flex items-center justify-between"><span className="text-[10px] text-gray-400">Status</span><span className="flex items-center gap-1.5 text-xs" style={{ color: sc.color }}><span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: sc.color }} />{sc.label}</span></div>
            </div>
          </div>

          {/* Resource Usage */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Resource Usage (30d)</h3>
              <button className="text-xs text-teal-400">View Details</button>
            </div>
            <div className="space-y-3">
              {[{ name: 'CPU Usage', value: 34, color: '#ef4444' }, { name: 'Memory Usage', value: 62, color: '#8b5cf6' }, { name: 'API Calls', value: 78, display: '23.4K', color: '#f59e0b' }, { name: 'Disk I/O', value: 18, color: '#14b8a6' }].map(r => (
                <div key={r.name}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2"><div className="w-5 h-5 rounded flex items-center justify-center" style={{ backgroundColor: r.color + '20' }}><div className="w-2 h-2 rounded-sm" style={{ backgroundColor: r.color }} /></div><span className="text-xs text-gray-300">{r.name}</span></div>
                    <span className="text-xs text-white font-medium">{r.display || `${r.value}%`}</span>
                  </div>
                  <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${r.value}%`, backgroundColor: r.color }} /></div>
                </div>
              ))}
            </div>
          </div>

          {/* Agent Capabilities */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <h3 className="text-white font-semibold text-sm mb-3">Agent Capabilities</h3>
            <div className="flex flex-wrap gap-2">
              {(agent.capabilities || []).map(cap => (
                <span key={cap} className="px-2 py-1 text-[10px] text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-md">
                  {cap.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                </span>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <h3 className="text-white font-semibold text-sm mb-3">Quick Actions</h3>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <QABtn icon={<Plus size={14} className="text-teal-400" />} label="Assign New Task" onClick={handleAssignTask} />
              <QABtn icon={<ArrowUpRight size={14} className="text-purple-400" />} label="Update Skills" onClick={() => setActiveTab('Skills')} />
              <QABtn icon={<Eye size={14} className="text-blue-400" />} label="View Memory" onClick={handleViewMemory} />
              <QABtn icon={<FileText size={14} className="text-orange-400" />} label="Performance Report" onClick={() => setActiveTab('Performance')} />
            </div>
            {canWake && (
              <button onClick={handleWake} disabled={actionLoading}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 mb-2 text-xs text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg hover:bg-green-500/20 transition-colors disabled:opacity-50">
                <Play size={14} /> Wake Agent
              </button>
            )}
            {canPause && (
              <button onClick={handlePause} disabled={actionLoading}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 mb-2 text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 rounded-lg hover:bg-yellow-500/20 transition-colors disabled:opacity-50">
                <Pause size={14} /> Pause Agent
              </button>
            )}
            <button onClick={handleDelete} disabled={actionLoading}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors disabled:opacity-50">
              <Power size={14} /> Deactivate Agent
            </button>
          </div>
        </div>
      </div>
      )}

      {/* Talk to Agent Modal */}
      {showTalkModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md mx-4 bg-[#0B1626] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-white/10">
              <h3 className="text-white font-semibold text-sm flex items-center gap-2">
                <MessageSquare size={14} className="text-teal-400" /> Talk to {agent.name}
              </h3>
              <button onClick={() => setShowTalkModal(false)} className="text-gray-400 hover:text-white">
                <span className="text-lg">×</span>
              </button>
            </div>
            <div className="p-5 space-y-4">
              {talkResponse && (
                <div className="p-3 rounded-lg bg-teal-500/10 border border-teal-500/20">
                  <p className="text-xs text-teal-300">{talkResponse}</p>
                </div>
              )}
              <textarea
                value={talkMessage}
                onChange={(e) => setTalkMessage(e.target.value)}
                placeholder={`Send a message to ${agent.name}...`}
                rows={3}
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-teal-500 resize-none"
              />
              <div className="flex justify-end gap-2">
                <button onClick={() => setShowTalkModal(false)} className="px-3 py-1.5 text-xs text-gray-400 hover:text-white">Cancel</button>
                <button onClick={handleSendMessage} disabled={!talkMessage.trim()}
                  className="px-4 py-1.5 text-xs bg-teal-500/20 text-teal-400 rounded-lg font-medium hover:bg-teal-500/30 disabled:opacity-50">
                  Send Message
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Helper Components ───

function MetricCard({ icon, iconColor, label, value, change, className = '' }: { icon: React.ReactNode; iconColor: string; label: string; value: string; change: string; className?: string }) {
  return (
    <div className={`p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] ${className}`}>
      <div className={`mb-2 ${iconColor}`}>{icon}</div>
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-lg font-bold text-white mt-0.5">{value}</p>
      <div className="flex items-center gap-1 mt-1"><ArrowUpRight size={10} className="text-green-400" /><span className="text-[10px] text-green-400">{change}</span></div>
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div><p className="text-[10px] text-gray-400">{label}</p><div className="flex items-center gap-2"><span className="text-sm text-white font-semibold">{value}</span><div className="w-8 h-3"><svg viewBox="0 0 32 12" className="w-full h-full"><polyline points="0,8 5,6 10,7 16,4 21,5 26,3 32,2" fill="none" stroke={color} strokeWidth="1.5" /></svg></div></div></div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between"><span className="text-[10px] text-gray-400">{label}</span><span className="text-xs text-white">{value}</span></div>;
}

function QABtn({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick?: () => void }) {
  return <button onClick={onClick} className="flex items-center gap-2 px-3 py-2 text-xs text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-lg hover:bg-white/[0.08] transition-colors">{icon}{label}</button>;
}

function DropItem({ icon, label, onClick, danger }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button onClick={onClick} className={`w-full flex items-center gap-2 px-3 py-2 text-xs transition-colors ${danger ? 'text-red-400 hover:bg-red-500/10' : 'text-gray-300 hover:bg-white/[0.05]'}`}>
      {icon}{label}
    </button>
  );
}

function ActivityIcon({ type }: { type: string }) {
  switch (type) {
    case 'check': return <CheckCircle2 size={14} className="text-green-400 mt-0.5" />;
    case 'git': return <GitCommit size={14} className="text-blue-400 mt-0.5" />;
    case 'brain': return <Brain size={14} className="text-purple-400 mt-0.5" />;
    case 'play': return <Play size={14} className="text-teal-400 mt-0.5" />;
    case 'pr': return <FileText size={14} className="text-orange-400 mt-0.5" />;
    case 'deploy': return <Rocket size={14} className="text-pink-400 mt-0.5" />;
    default: return <CheckCircle2 size={14} className="text-gray-400 mt-0.5" />;
  }
}
