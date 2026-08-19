import { useParams } from 'react-router-dom';
import { Card } from '@/components/common/Card';
import {
  CheckCircle2,
  BarChart3,
  Clock,
  Layers,
  Signal,
  ArrowUpRight,
  ChevronDown,
  GitCommit,
  Brain,
  Play,
  CheckCircle,
  MessageSquare,
  Rocket,
  Edit,
  Plus,
  FileText,
  Eye,
  Power,
  ChevronRight,
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

// --- Static Mock Data ---

const performanceChartData = [
  { date: 'May 10', tasksCompleted: 65, successRate: 96 },
  { date: 'May 11', tasksCompleted: 72, successRate: 97 },
  { date: 'May 12', tasksCompleted: 60, successRate: 95 },
  { date: 'May 13', tasksCompleted: 85, successRate: 98 },
  { date: 'May 14', tasksCompleted: 78, successRate: 99 },
  { date: 'May 15', tasksCompleted: 92, successRate: 97 },
  { date: 'May 16', tasksCompleted: 95, successRate: 99 },
];

const skillsData = [
  { name: 'Python', proficiency: 95, color: '#8b5cf6', experience: '2.3 years', lastUsed: '2h ago' },
  { name: 'FastAPI', proficiency: 92, color: '#14b8a6', experience: '1.8 years', lastUsed: '1h ago' },
  { name: 'PostgreSQL', proficiency: 88, color: '#3b82f6', experience: '2.1 years', lastUsed: '3h ago' },
  { name: 'Docker', proficiency: 85, color: '#06b6d4', experience: '1.7 years', lastUsed: '5h ago' },
  { name: 'Redis', proficiency: 80, color: '#ef4444', experience: '1.4 years', lastUsed: '1d ago' },
];

const activityItems = [
  { icon: 'check', text: 'Completed task: Fix user session bug', time: '10:15 AM' },
  { icon: 'git', text: 'Committed changes to auth_service.py', time: '09:49 AM' },
  { icon: 'brain', text: 'Memory updated: Added 3 new insights', time: '09:32 AM' },
  { icon: 'play', text: 'Started task: Implement rate limiting', time: '09:21 AM' },
  { icon: 'pr', text: 'Reviewed pull request #128', time: 'Yesterday' },
  { icon: 'deploy', text: 'Deployed to staging environment', time: 'Yesterday' },
];

const taskQueue = [
  { name: 'Optimize database queries', priority: 'High', color: '#ef4444' },
  { name: 'API rate limiting implementation', priority: 'Medium', color: '#f59e0b' },
  { name: 'Write unit tests for payment module', priority: 'Low', color: '#10b981' },
];

const resourceUsage = [
  { name: 'CPU Usage', value: 34, color: '#ef4444', icon: 'cpu' },
  { name: 'Memory Usage', value: 62, color: '#8b5cf6', icon: 'memory' },
  { name: 'API Calls', value: 78, displayValue: '23.4K', color: '#f59e0b', icon: 'api' },
  { name: 'Disk I/O', value: 18, color: '#14b8a6', icon: 'disk' },
];

const capabilities = [
  'Python', 'FastAPI', 'PostgreSQL', 'Docker', 'Redis', 'REST API',
  'JWT', 'Authentication', 'Celery', 'Microservices', 'CI/CD', 'Git', 'Testing',
];

const agentInfo = {
  agentId: 'agent_alpha_001',
  role: 'Backend Developer',
  department: 'Development Zone',
  team: 'Core Engineering',
  supervisor: 'Navi Yanka',
  created: 'May 10, 2024, 09:15 AM',
  lastUpdated: 'May 16, 2024, 10:15 AM',
  status: 'Working',
};

const tabs = ['Overview', 'Skills', 'Memory', 'Tasks', 'Performance', 'Settings', 'Logs', 'Activity'];

// --- Component ---

export function AgentDetailPage() {
  const { id: _id } = useParams<{ id: string }>();

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-gray-400">Agents</span>
        <ChevronRight size={14} className="text-gray-500" />
        <span className="text-white font-medium">Alpha</span>
      </div>

      {/* Profile Header */}
      <Card padding="lg">
        <div className="flex flex-col lg:flex-row lg:items-center gap-6">
          {/* Avatar */}
          <div className="relative">
            <div className="w-20 h-20 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center">
              <span className="text-3xl font-bold text-white">A</span>
            </div>
            <div className="absolute bottom-0 right-0 w-5 h-5 bg-green-500 rounded-full border-2 border-dark-surface" />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-2xl font-bold text-white">Alpha</h1>
              <span className="flex items-center gap-1.5 text-xs text-green-400">
                <span className="w-2 h-2 rounded-full bg-green-400" />
                Working
              </span>
            </div>
            <span className="inline-block px-2.5 py-0.5 rounded-full text-xs font-medium bg-teal-500/20 text-teal-400 mb-2">
              Backend Developer Agent
            </span>
            <p className="text-sm text-gray-400 mb-4">
              Backend development specialist focused on building robust APIs, microservices, and scalable server-side solutions.
            </p>
            {/* Stats Row */}
            <div className="flex flex-wrap items-center gap-4 text-xs">
              <StatItem label="Role" value="Backend" />
              <Divider />
              <StatItem label="Primary Model" value="Gemini 1.5 Pro" />
              <Divider />
              <StatItem label="Version" value="v2.3.1" />
              <Divider />
              <StatItem label="Joined" value="May 12, 2024" />
              <Divider />
              <StatItem label="Reliability" value="98.6%" />
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-4 py-2 border border-teal-500 text-teal-400 rounded-lg text-sm font-medium hover:bg-teal-500/10 transition-colors">
              <MessageSquare size={16} />
              Talk to Agent
            </button>
            <button className="flex items-center gap-2 px-4 py-2 bg-white/[0.05] border border-white/[0.08] text-gray-300 rounded-lg text-sm font-medium hover:bg-white/[0.08] transition-colors">
              Actions
              <ChevronDown size={14} />
            </button>
          </div>
        </div>
      </Card>

      {/* Tab Navigation */}
      <div className="border-b border-white/[0.08]">
        <div className="flex items-center gap-6 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={`pb-3 text-sm font-medium whitespace-nowrap transition-colors ${
                tab === 'Overview'
                  ? 'text-teal-400 border-b-2 border-teal-400'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Three-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* LEFT SECTION */}
        <div className="lg:col-span-5 space-y-4">
          {/* Stat Cards */}
          <div className="grid grid-cols-2 gap-3">
            <MetricCard
              icon={<CheckCircle2 size={18} />}
              iconColor="text-green-400"
              label="Tasks Completed"
              value="1,248"
              change="+15% this week"
              changeUp
            />
            <MetricCard
              icon={<BarChart3 size={18} />}
              iconColor="text-purple-400"
              label="Success Rate"
              value="98.6%"
              change="+2.4%"
              changeUp
            />
            <MetricCard
              icon={<Clock size={18} />}
              iconColor="text-blue-400"
              label="Avg. Response Time"
              value="2.4s"
              change="-0.6s"
              changeUp
            />
            <MetricCard
              icon={<Layers size={18} />}
              iconColor="text-orange-400"
              label="Total Tokens (30d)"
              value="1.24M"
              change="+18.7%"
              changeUp
            />
            <MetricCard
              icon={<Signal size={18} />}
              iconColor="text-teal-400"
              label="Uptime (30d)"
              value="99.8%"
              change="+0.3%"
              changeUp
              className="col-span-2 sm:col-span-1"
            />
          </div>

          {/* Current Workload */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Current Workload</h3>
              <span className="flex items-center gap-1.5 text-xs text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                Live
              </span>
            </div>

            {/* Active Task */}
            <div className="bg-dark-bg rounded-lg p-3 border border-white/[0.05] mb-4">
              <p className="text-xs text-gray-400 mb-1">Active Task</p>
              <p className="text-sm text-white font-medium mb-1">Implement user authentication system</p>
              <p className="text-[10px] text-gray-500 mb-3">Task ID: task_7f2a9c4d &bull; Started 10:24 AM</p>
              <div className="h-2 bg-white/[0.08] rounded-full overflow-hidden mb-1">
                <div className="h-full bg-teal-500 rounded-full" style={{ width: '75%' }} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-teal-400">75%</span>
                <span className="text-[10px] text-gray-500">Est. 25m remaining</span>
              </div>
            </div>

            {/* Task Queue */}
            <div className="mb-3">
              <p className="text-xs text-gray-400 mb-2">Task Queue (3)</p>
              <div className="space-y-2">
                {taskQueue.map((task) => (
                  <div key={task.name} className="flex items-center justify-between">
                    <span className="text-xs text-gray-300">{task.name}</span>
                    <span className="flex items-center gap-1.5 text-[10px] text-gray-400">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: task.color }} />
                      {task.priority} Priority
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <button className="text-xs text-teal-400 hover:text-teal-300 transition-colors">
              View All Tasks &rarr;
            </button>
          </Card>

          {/* Skills & Proficiency */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Skills & Proficiency</h3>
              <button className="text-xs text-teal-400 hover:text-teal-300 transition-colors">
                View All Skills
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-400 border-b border-white/[0.05]">
                    <th className="text-left pb-2 font-medium">Skill</th>
                    <th className="text-left pb-2 font-medium">Proficiency</th>
                    <th className="text-left pb-2 font-medium">Experience</th>
                    <th className="text-left pb-2 font-medium">Last Used</th>
                  </tr>
                </thead>
                <tbody>
                  {skillsData.map((skill) => (
                    <tr key={skill.name} className="border-b border-white/[0.03]">
                      <td className="py-2.5 text-white font-medium">{skill.name}</td>
                      <td className="py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="w-20 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${skill.proficiency}%`, backgroundColor: skill.color }}
                            />
                          </div>
                          <span className="text-gray-400">{skill.proficiency}%</span>
                        </div>
                      </td>
                      <td className="py-2.5 text-gray-400">{skill.experience}</td>
                      <td className="py-2.5 text-gray-400">{skill.lastUsed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        {/* CENTER SECTION */}
        <div className="lg:col-span-4 space-y-4">
          {/* Performance Overview */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Performance Overview</h3>
              <button className="flex items-center gap-1 text-xs text-gray-400 bg-white/[0.05] px-2 py-1 rounded hover:bg-white/[0.08] transition-colors">
                7 Days
                <ChevronDown size={12} />
              </button>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-4 mb-4">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-green-400" />
                <span className="text-[10px] text-gray-400">Tasks Completed</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-purple-400" />
                <span className="text-[10px] text-gray-400">Success Rate %</span>
              </div>
            </div>

            {/* Chart */}
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={performanceChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis
                    dataKey="date"
                    stroke="#6b7280"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="#6b7280"
                    fontSize={10}
                    tickLine={false}
                    axisLine={false}
                    domain={[0, 100]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1b2e',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      color: '#fff',
                      fontSize: '11px',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="tasksCompleted"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={false}
                    name="Tasks Completed"
                  />
                  <Line
                    type="monotone"
                    dataKey="successRate"
                    stroke="#8b5cf6"
                    strokeWidth={2}
                    dot={false}
                    name="Success Rate %"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Stats below chart */}
            <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-white/[0.08]">
              <div>
                <p className="text-[10px] text-gray-400">Tasks / Day</p>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white font-semibold">28.4</span>
                  <div className="w-8 h-3">
                    <svg viewBox="0 0 32 12" className="w-full h-full">
                      <polyline
                        points="0,8 5,6 10,7 16,4 21,5 26,3 32,2"
                        fill="none"
                        stroke="#10b981"
                        strokeWidth="1.5"
                      />
                    </svg>
                  </div>
                </div>
              </div>
              <div>
                <p className="text-[10px] text-gray-400">Errors / Day</p>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white font-semibold">0.8</span>
                  <div className="w-8 h-3">
                    <svg viewBox="0 0 32 12" className="w-full h-full">
                      <polyline
                        points="0,4 5,6 10,5 16,8 21,6 26,9 32,7"
                        fill="none"
                        stroke="#ef4444"
                        strokeWidth="1.5"
                      />
                    </svg>
                  </div>
                </div>
              </div>
              <div>
                <p className="text-[10px] text-gray-400">Rework Rate</p>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white font-semibold">1.2%</span>
                  <div className="w-8 h-3">
                    <svg viewBox="0 0 32 12" className="w-full h-full">
                      <polyline
                        points="0,6 5,5 10,7 16,6 21,8 26,5 32,6"
                        fill="none"
                        stroke="#f59e0b"
                        strokeWidth="1.5"
                      />
                    </svg>
                  </div>
                </div>
              </div>
            </div>
          </Card>

          {/* Recent Activity */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Recent Activity</h3>
              <button className="text-xs text-teal-400 hover:text-teal-300 transition-colors">
                View All
              </button>
            </div>
            <div className="space-y-3">
              {activityItems.map((item, i) => (
                <div key={i} className="flex items-start gap-3">
                  <div className="mt-0.5">
                    <ActivityIcon type={item.icon} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-300">{item.text}</p>
                    <p className="text-[10px] text-gray-500 mt-0.5">{item.time}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* RIGHT SIDEBAR */}
        <div className="lg:col-span-3 space-y-4">
          {/* Agent Information */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Agent Information</h3>
              <button className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 transition-colors">
                <Edit size={12} />
                Edit
              </button>
            </div>
            <div className="space-y-3">
              <InfoRow label="Agent ID" value={agentInfo.agentId} />
              <InfoRow label="Role" value={agentInfo.role} />
              <InfoRow label="Department" value={agentInfo.department} />
              <InfoRow label="Team" value={agentInfo.team} />
              <InfoRow label="Supervisor" value={agentInfo.supervisor} />
              <InfoRow label="Created" value={agentInfo.created} />
              <InfoRow label="Last Updated" value={agentInfo.lastUpdated} />
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-400">Status</span>
                <span className="flex items-center gap-1.5 text-xs text-green-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                  {agentInfo.status}
                </span>
              </div>
            </div>
          </Card>

          {/* Resource Usage */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Resource Usage (30d)</h3>
              <button className="text-xs text-teal-400 hover:text-teal-300 transition-colors">
                View Details
              </button>
            </div>
            <div className="space-y-3">
              {resourceUsage.map((resource) => (
                <div key={resource.name}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-5 h-5 rounded flex items-center justify-center"
                        style={{ backgroundColor: `${resource.color}20` }}
                      >
                        <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: resource.color }} />
                      </div>
                      <span className="text-xs text-gray-300">{resource.name}</span>
                    </div>
                    <span className="text-xs text-white font-medium">
                      {resource.displayValue ?? `${resource.value}%`}
                    </span>
                  </div>
                  <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${resource.value}%`, backgroundColor: resource.color }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Agent Capabilities */}
          <Card padding="lg">
            <h3 className="text-white font-semibold text-sm mb-3">Agent Capabilities</h3>
            <div className="flex flex-wrap gap-2">
              {capabilities.map((cap) => (
                <span
                  key={cap}
                  className="px-2 py-1 text-[10px] text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-md"
                >
                  {cap}
                </span>
              ))}
              <span className="px-2 py-1 text-[10px] text-gray-500 bg-white/[0.03] border border-white/[0.05] rounded-md">
                +8 more
              </span>
            </div>
          </Card>

          {/* Quick Actions */}
          <Card padding="lg">
            <h3 className="text-white font-semibold text-sm mb-3">Quick Actions</h3>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <button className="flex items-center gap-2 px-3 py-2 text-xs text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-lg hover:bg-white/[0.08] transition-colors">
                <Plus size={14} className="text-teal-400" />
                Assign New Task
              </button>
              <button className="flex items-center gap-2 px-3 py-2 text-xs text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-lg hover:bg-white/[0.08] transition-colors">
                <ArrowUpRight size={14} className="text-purple-400" />
                Update Skills
              </button>
              <button className="flex items-center gap-2 px-3 py-2 text-xs text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-lg hover:bg-white/[0.08] transition-colors">
                <Eye size={14} className="text-blue-400" />
                View Memory
              </button>
              <button className="flex items-center gap-2 px-3 py-2 text-xs text-gray-300 bg-white/[0.05] border border-white/[0.08] rounded-lg hover:bg-white/[0.08] transition-colors">
                <FileText size={14} className="text-orange-400" />
                Performance Report
              </button>
            </div>
            <button className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors">
              <Power size={14} />
              Deactivate Agent
            </button>
          </Card>
        </div>
      </div>
    </div>
  );
}

// --- Helper Components ---

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-gray-400">{label}: </span>
      <span className="text-white font-medium">{value}</span>
    </div>
  );
}

function Divider() {
  return <span className="text-gray-600">|</span>;
}

function MetricCard({
  icon,
  iconColor,
  label,
  value,
  change,
  changeUp,
  className = '',
}: {
  icon: React.ReactNode;
  iconColor: string;
  label: string;
  value: string;
  change: string;
  changeUp: boolean;
  className?: string;
}) {
  return (
    <Card padding="md" className={className}>
      <div className="flex items-start justify-between mb-2">
        <div className={iconColor}>{icon}</div>
      </div>
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-lg font-bold text-white mt-0.5">{value}</p>
      <div className="flex items-center gap-1 mt-1">
        {changeUp ? (
          <ArrowUpRight size={10} className="text-green-400" />
        ) : (
          <ArrowUpRight size={10} className="text-green-400" />
        )}
        <span className="text-[10px] text-green-400">{change}</span>
      </div>
    </Card>
  );
}

function ActivityIcon({ type }: { type: string }) {
  switch (type) {
    case 'check':
      return <CheckCircle size={14} className="text-green-400" />;
    case 'git':
      return <GitCommit size={14} className="text-blue-400" />;
    case 'brain':
      return <Brain size={14} className="text-purple-400" />;
    case 'play':
      return <Play size={14} className="text-teal-400" />;
    case 'pr':
      return <FileText size={14} className="text-orange-400" />;
    case 'deploy':
      return <Rocket size={14} className="text-pink-400" />;
    default:
      return <CheckCircle size={14} className="text-gray-400" />;
  }
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px] text-gray-400">{label}</span>
      <span className="text-xs text-white">{value}</span>
    </div>
  );
}
