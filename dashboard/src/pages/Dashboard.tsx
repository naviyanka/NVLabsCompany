import { Card } from '@/components/common/Card';
import {
  Sparkles,
  Bot,
  ClipboardList,
  Waves,
  Flame,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
  Play,
  Plus,
  Send,
  GitCommit,
  CheckCircle2,
  AlertCircle,
  Zap,
  Brain,
} from 'lucide-react';
import {
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from 'recharts';

// Token & Cost chart data
const tokenCostData = Array.from({ length: 25 }, (_, i) => {
  const hour = i;
  const baseTokens = 80000 + Math.sin(i * 0.5) * 40000 + Math.random() * 20000;
  const baseCost = 30 + Math.sin(i * 0.4) * 20 + Math.random() * 10;
  return {
    time: `${String(hour).padStart(2, '0')}:00`,
    tokens: Math.round(baseTokens),
    cost: Math.round(baseCost * 100) / 100,
  };
});

// Pipeline data
const pipelines = [
  { name: 'Bug Bounty Recon Pipeline', progress: 85, color: '#f59e0b' },
  { name: 'Code Review Automation', progress: 62, color: '#10b981' },
  { name: 'Threat Intel Collector', progress: 45, color: '#14b8a6' },
  { name: 'Content Generation Flow', progress: 30, color: '#8b5cf6' },
];

// Activity data
const activities = [
  { time: '10:24 AM', text: 'Agent Alpha completed task Subdomain Enumeration', icon: <CheckCircle2 size={14} />, color: 'text-green-400' },
  { time: '10:23 AM', text: 'Pipeline Bug Bounty Recon progressed to 85%', icon: <Flame size={14} />, color: 'text-orange-400' },
  { time: '10:22 AM', text: 'Agent Nova memory updated (2.4 MB)', icon: <Brain size={14} />, color: 'text-purple-400' },
  { time: '10:21 AM', text: 'Code pushed to nvlabsorg/core', icon: <GitCommit size={14} />, color: 'text-blue-400' },
  { time: '10:20 AM', text: 'New task assigned to Agent Cipher', icon: <AlertCircle size={14} />, color: 'text-red-400' },
];

// Task data
const recentTasks = [
  { name: 'Analyze target.com', agent: 'Omega', progress: 75, time: '10:24 AM' },
  { name: 'Generate report v2', agent: 'Nova', progress: 60, time: '10:22 AM' },
  { name: 'Monitor endpoints', agent: 'Cipher', progress: 45, time: '10:20 AM' },
  { name: 'Update dependencies', agent: 'Hash', progress: 30, time: '10:18 AM' },
];

// Top agents data
const topAgents = [
  { name: 'Alpha', score: 96, backend: 'Gemini 1.5 Pro', color: 'from-green-400 to-green-600' },
  { name: 'Hash', score: 89, backend: 'Claude 3.5 Sonnet', color: 'from-blue-400 to-blue-600' },
  { name: 'Nova', score: 85, backend: 'GPT-4o', color: 'from-purple-400 to-purple-600' },
  { name: 'Cipher', score: 78, backend: 'Gemini 1.5 Flash', color: 'from-orange-400 to-orange-600' },
];

// Office zones for the visualization
const officeZones = [
  { name: 'Planning Zone', x: 5, y: 5, w: 90, h: 50, borderColor: '#14b8a6' },
  { name: 'DevOps Zone', x: 5, y: 65, w: 70, h: 50, borderColor: '#f59e0b' },
  { name: 'Development Zone', x: 105, y: 5, w: 100, h: 60, borderColor: '#10b981' },
  { name: 'Meeting Area', x: 215, y: 5, w: 80, h: 55, borderColor: '#ec4899' },
  { name: 'Analysis Zone', x: 5, y: 125, w: 90, h: 50, borderColor: '#3b82f6' },
  { name: 'Support Zone', x: 105, y: 75, w: 85, h: 50, borderColor: '#8b5cf6' },
  { name: 'HQ Terminal', x: 200, y: 70, w: 95, h: 55, borderColor: '#6b7280' },
];

// Agent dots for the office visualization
const agentDots = [
  { x: 30, y: 25, color: '#10b981' },
  { x: 55, y: 35, color: '#10b981' },
  { x: 75, y: 20, color: '#eab308' },
  { x: 25, y: 80, color: '#10b981' },
  { x: 50, y: 90, color: '#10b981' },
  { x: 130, y: 25, color: '#10b981' },
  { x: 155, y: 40, color: '#eab308' },
  { x: 180, y: 30, color: '#10b981' },
  { x: 240, y: 25, color: '#ef4444' },
  { x: 260, y: 35, color: '#10b981' },
  { x: 30, y: 145, color: '#10b981' },
  { x: 60, y: 150, color: '#6b7280' },
  { x: 130, y: 95, color: '#10b981' },
  { x: 155, y: 100, color: '#eab308' },
  { x: 230, y: 90, color: '#10b981' },
  { x: 255, y: 100, color: '#10b981' },
];

export function Dashboard() {
  return (
    <div className="space-y-6">
      {/* (A) Page Title */}
      <div>
        <div className="flex items-center gap-2">
          <Sparkles size={24} className="text-indigo-400" />
          <h1 className="text-2xl font-bold text-white">NVLabs Mission Control</h1>
        </div>
        <p className="text-sm text-gray-400 mt-1">Monitor. Orchestrate. Scale.</p>
      </div>

      {/* (B) Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          label="Active Agents"
          value="24"
          total="/32"
          change="+12%"
          changeUp
          icon={<Bot size={20} />}
          iconBg="bg-[#8b5cf6]"
        />
        <StatCard
          label="Active Tasks"
          value="18"
          total="/50"
          change="+8%"
          changeUp
          icon={<ClipboardList size={20} />}
          iconBg="bg-[#3b82f6]"
        />
        <StatCard
          label="Pipelines"
          value="7"
          total="/15"
          change="+5%"
          changeUp
          icon={<Waves size={20} />}
          iconBg="bg-[#10b981]"
        />
        <StatCard
          label="Token Usage (24h)"
          value="1.24M"
          change="-3%"
          changeUp={false}
          icon={<Flame size={20} />}
          iconBg="bg-[#f59e0b]"
        />
        <StatCard
          label="Est. Spend (24h)"
          value="$42.68"
          change="+7%"
          changeUp
          icon={<DollarSign size={20} />}
          iconBg="bg-[#ec4899]"
        />
      </div>

      {/* (C) Three-column section */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Agent Network */}
        <Card className="lg:col-span-5" padding="lg">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-white font-semibold">Agent Network</h3>
              <p className="text-xs text-gray-400">24 Active Agents</p>
            </div>
            <a href="/office" className="text-xs text-blue-400 hover:text-blue-300">
              View Office &rarr;
            </a>
          </div>
          {/* Office visualization */}
          <div className="bg-[#0f1117] rounded-lg p-3 border border-white/[0.05]">
            <svg viewBox="0 0 300 185" className="w-full h-auto">
              {officeZones.map((zone) => (
                <g key={zone.name}>
                  <rect
                    x={zone.x}
                    y={zone.y}
                    width={zone.w}
                    height={zone.h}
                    fill="none"
                    stroke={zone.borderColor}
                    strokeWidth="1"
                    strokeOpacity="0.5"
                    rx="3"
                  />
                  <text
                    x={zone.x + 4}
                    y={zone.y + 12}
                    fill={zone.borderColor}
                    fontSize="6"
                    opacity="0.8"
                  >
                    {zone.name}
                  </text>
                </g>
              ))}
              {agentDots.map((dot, i) => (
                <circle key={i} cx={dot.x} cy={dot.y} r="3" fill={dot.color} opacity="0.9" />
              ))}
            </svg>
          </div>
          {/* Legend */}
          <div className="flex items-center gap-4 mt-3">
            <LegendDot color="bg-green-400" label="Working" />
            <LegendDot color="bg-yellow-400" label="Idle" />
            <LegendDot color="bg-red-400" label="Review" />
            <LegendDot color="bg-gray-400" label="Offline" />
          </div>
        </Card>

        {/* Pipeline Execution */}
        <Card className="lg:col-span-4" padding="lg">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-white font-semibold">Pipeline Execution</h3>
              <p className="text-xs text-gray-400">7 Running Pipelines</p>
            </div>
            <a href="/pipelines" className="text-xs text-blue-400 hover:text-blue-300">
              View All &rarr;
            </a>
          </div>
          <div className="space-y-4">
            {pipelines.map((pipeline) => (
              <div key={pipeline.name}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-gray-300">{pipeline.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">{pipeline.progress}%</span>
                    <Play size={12} className="text-gray-400" />
                  </div>
                </div>
                <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${pipeline.progress}%`, backgroundColor: pipeline.color }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-4">+ 3 More Pipelines</p>
        </Card>

        {/* Live Activity */}
        <Card className="lg:col-span-3" padding="lg">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-white font-semibold">Live Activity</h3>
              <div className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                <p className="text-xs text-gray-400">All Systems Live</p>
              </div>
            </div>
            <span className="text-[10px] text-gray-400 bg-white/[0.05] px-2 py-0.5 rounded">All</span>
          </div>
          <div className="space-y-3">
            {activities.map((activity, i) => (
              <div key={i} className="flex gap-2">
                <div className={`mt-0.5 ${activity.color}`}>{activity.icon}</div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 leading-relaxed">{activity.text}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{activity.time}</p>
                </div>
              </div>
            ))}
          </div>
          <a href="/activity" className="text-xs text-blue-400 hover:text-blue-300 mt-4 block">
            View All Activity &rarr;
          </a>
        </Card>
      </div>

      {/* (D) Quick Actions */}
      <div className="flex flex-wrap gap-3">
        <button className="flex items-center gap-2 px-4 py-2 bg-[#10b981] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          <Plus size={16} /> Add Agent
        </button>
        <button className="flex items-center gap-2 px-4 py-2 bg-[#3b82f6] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          <Plus size={16} /> Create Task
        </button>
        <button className="flex items-center gap-2 px-4 py-2 bg-[#f59e0b] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          <Plus size={16} /> New Pipeline
        </button>
        <button className="flex items-center gap-2 px-4 py-2 bg-[#ec4899] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          Open HR Room
        </button>
        <button className="flex items-center gap-2 px-4 py-2 bg-[#8b5cf6] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          View Office
        </button>
      </div>

      {/* (E) Bottom Two-Column: Recent Tasks + Top Agents */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Recent Tasks */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold">Recent Tasks</h3>
            <a href="/tasks" className="text-xs text-blue-400 hover:text-blue-300">View All &rarr;</a>
          </div>
          <div className="space-y-3">
            {recentTasks.map((task) => (
              <div key={task.name} className="flex items-center gap-3">
                <div className="w-8 h-8 bg-white/[0.05] rounded-lg flex items-center justify-center">
                  <Zap size={14} className="text-indigo-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white font-medium truncate">{task.name}</p>
                  <p className="text-[10px] text-gray-500">Agent: {task.agent}</p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full"
                      style={{ width: `${task.progress}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400 w-8">{task.progress}%</span>
                </div>
                <span className="text-[10px] text-gray-500">{task.time}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Agents */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold">Top Agents</h3>
            <a href="/agents" className="text-xs text-blue-400 hover:text-blue-300">View All &rarr;</a>
          </div>
          <div className="space-y-3">
            {topAgents.map((agent) => (
              <div key={agent.name} className="flex items-center gap-3">
                <div className={`w-8 h-8 bg-gradient-to-br ${agent.color} rounded-full flex items-center justify-center`}>
                  <span className="text-white text-xs font-bold">{agent.name[0]}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white font-medium">{agent.name}</p>
                  <p className="text-[10px] text-gray-500">Backend: {agent.backend}</p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full"
                      style={{ width: `${agent.score}%` }}
                    />
                  </div>
                  <span className="text-xs text-green-400 w-8">{agent.score}%</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* (F) Token & Cost Overview */}
      <Card padding="lg">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white font-semibold">Token & Cost Overview</h3>
          <span className="text-[10px] text-gray-400 bg-white/[0.05] px-2 py-0.5 rounded">24 Hours</span>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={tokenCostData}>
              <defs>
                <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis
                dataKey="time"
                stroke="#6b7280"
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                yAxisId="tokens"
                orientation="left"
                stroke="#6b7280"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}K`}
                domain={[0, 200000]}
              />
              <YAxis
                yAxisId="cost"
                orientation="right"
                stroke="#6b7280"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `$${v}`}
                domain={[0, 80]}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a1b2e',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: '8px',
                  color: '#fff',
                  fontSize: '12px',
                }}
              />
              <Area
                yAxisId="tokens"
                type="monotone"
                dataKey="tokens"
                stroke="#3b82f6"
                fill="url(#tokenGradient)"
                strokeWidth={2}
              />
              <Line
                yAxisId="cost"
                type="monotone"
                dataKey="cost"
                stroke="#f97316"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-white/[0.08]">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-blue-500" />
            <span className="text-xs text-gray-400">Total Tokens: 1.24M</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-orange-500" />
            <span className="text-xs text-gray-400">Total Cost: $42.68</span>
          </div>
        </div>
      </Card>

      {/* (G) Command Bar */}
      <div className="relative">
        <div className="flex items-center bg-[#1a1b2e] border border-white/[0.08] rounded-xl px-4 py-3">
          <span className="text-[10px] text-gray-500 bg-[#0f1117] border border-white/[0.08] rounded px-1.5 py-0.5 mr-3">
            Ctrl K
          </span>
          <input
            type="text"
            placeholder="Ask NVLabs anything..."
            className="flex-1 bg-transparent text-sm text-gray-300 placeholder-gray-500 focus:outline-none"
          />
          <button className="ml-3 p-2 bg-[#14b8a6] rounded-lg hover:opacity-90 transition-opacity">
            <Send size={16} className="text-white" />
          </button>
        </div>
      </div>
    </div>
  );
}

// Helper components
function StatCard({
  label,
  value,
  total,
  change,
  changeUp,
  icon,
  iconBg,
}: {
  label: string;
  value: string;
  total?: string;
  change: string;
  changeUp: boolean;
  icon: React.ReactNode;
  iconBg: string;
}) {
  return (
    <Card padding="lg">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
          <p className="text-xl font-bold text-white mt-1">
            {value}
            {total && <span className="text-sm text-gray-500 font-normal">{total}</span>}
          </p>
          <div className="flex items-center gap-1 mt-1">
            {changeUp ? (
              <ArrowUpRight size={12} className="text-green-400" />
            ) : (
              <ArrowDownRight size={12} className="text-red-400" />
            )}
            <span className={`text-xs ${changeUp ? 'text-green-400' : 'text-red-400'}`}>
              {change}
            </span>
          </div>
        </div>
        <div className={`w-10 h-10 ${iconBg} rounded-lg flex items-center justify-center text-white`}>
          {icon}
        </div>
      </div>
    </Card>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      <span className="text-[10px] text-gray-400">{label}</span>
    </div>
  );
}
