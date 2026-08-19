import { Card } from '@/components/common/Card';
import {
  GitBranch,
  LayoutGrid,
  Upload,
  Plus,
  Clipboard,
  Play,
  CheckCircle2,
  Clock,
  Zap,
  Pause,
  Square,
  Maximize2,
  Grid,
  Pencil,
  Copy,
  Lock,
  ZoomIn,
  ZoomOut,
  Minimize2,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
} from 'recharts';

// Static mock data - Pipelines page uses hardcoded data matching the design spec

// Sparkline data for stat cards
const sparklineData1 = [
  { v: 8 }, { v: 10 }, { v: 9 }, { v: 12 }, { v: 11 }, { v: 14 }, { v: 15 },
];
const sparklineData2 = [
  { v: 5 }, { v: 6 }, { v: 7 }, { v: 6 }, { v: 8 }, { v: 7 }, { v: 7 },
];
const sparklineData3 = [
  { v: 18 }, { v: 20 }, { v: 19 }, { v: 22 }, { v: 21 }, { v: 24 }, { v: 23 },
];
const sparklineData4 = [
  { v: 82 }, { v: 84 }, { v: 86 }, { v: 85 }, { v: 88 }, { v: 87 }, { v: 90 },
];
const sparklineData5 = [
  { v: 18 }, { v: 17 }, { v: 16 }, { v: 15 }, { v: 15 }, { v: 14 }, { v: 14 },
];
const sparklineData6 = [
  { v: 320 }, { v: 340 }, { v: 360 }, { v: 370 }, { v: 385 }, { v: 400 }, { v: 412 },
];



// Recent executions
const recentExecutions = [
  { date: 'May 16, 10:15 AM', status: 'Running', duration: '12m 42s' },
  { date: 'May 16, 09:02 AM', status: 'Completed', duration: '15m 11s' },
  { date: 'May 15, 07:45 PM', status: 'Completed', duration: '13m 08s' },
  { date: 'May 15, 03:22 PM', status: 'Failed', duration: '\u2014' },
  { date: 'May 15, 11:10 AM', status: 'Completed', duration: '14m 55s' },
];

// Pipeline templates
const pipelineTemplates = [
  { name: 'Bug Bounty Recon', category: 'Security', tasks: 8 },
  { name: 'Code Review Automation', category: 'DevOps', tasks: 6 },
  { name: 'Threat Intel Collection', category: 'Security', tasks: 5 },
  { name: 'Content Generation Flow', category: 'Research', tasks: 7 },
];

// Execution trends chart data
const executionTrendsData = [
  { date: 'May 10', success: 28, failed: 3 },
  { date: 'May 11', success: 32, failed: 2 },
  { date: 'May 12', success: 25, failed: 5 },
  { date: 'May 13', success: 30, failed: 4 },
  { date: 'May 14', success: 35, failed: 2 },
  { date: 'May 15', success: 27, failed: 3 },
  { date: 'May 16', success: 33, failed: 2 },
];

// Top pipeline runs
const topPipelineRuns = [
  { name: 'Bug Bounty Recon Pipeline', runs: 23 },
  { name: 'Code Review Automation', runs: 18 },
  { name: 'Threat Intel Collection', runs: 12 },
  { name: 'Content Generation Flow', runs: 8 },
  { name: 'Repo Security Audit', runs: 6 },
];

// Resource usage donut data
const resourceUsageData = [
  { name: 'Agent Time', value: 62, color: '#3b82f6' },
  { name: 'API Calls', value: 23, color: '#10b981' },
  { name: 'Memory Usage', value: 9, color: '#f59e0b' },
  { name: 'Other', value: 6, color: '#8b5cf6' },
];

export function Pipelines() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch size={24} className="text-indigo-400" />
            <h1 className="text-2xl font-bold text-white">Pipelines</h1>
          </div>
          <p className="text-sm text-gray-400 mt-1">Orchestrate complex workflows with your AI agents</p>
        </div>
        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] text-gray-300 text-sm rounded-lg hover:bg-dark-card transition-colors">
            <LayoutGrid size={16} />
            Templates
          </button>
          <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] text-gray-300 text-sm rounded-lg hover:bg-dark-card transition-colors">
            <Upload size={16} />
            Import Pipeline
          </button>
          <button className="flex items-center gap-2 px-3 py-2 bg-[#10b981] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
            <Plus size={16} />
            New Pipeline
          </button>
        </div>
      </div>

      {/* Stat Cards Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
        <PipelineStatCard
          label="Total Pipelines"
          value="15"
          change="\u2191 7 this month"
          changeColor="text-green-400"
          icon={<Clipboard size={18} />}
          iconBg="bg-[#ec4899]"
          sparkData={sparklineData1}
          sparkColor="#ec4899"
        />
        <PipelineStatCard
          label="Running"
          value="7"
          change="Live now"
          changeColor="text-green-400"
          badge
          icon={<Play size={18} />}
          iconBg="bg-[#3b82f6]"
          sparkData={sparklineData2}
          sparkColor="#3b82f6"
        />
        <PipelineStatCard
          label="Completed (24h)"
          value="23"
          change="\u2191 18%"
          changeColor="text-green-400"
          icon={<CheckCircle2 size={18} />}
          iconBg="bg-[#10b981]"
          sparkData={sparklineData3}
          sparkColor="#10b981"
        />
        <PipelineStatCard
          label="Success Rate"
          value="89.6%"
          change="\u2191 6.3%"
          changeColor="text-green-400"
          icon={<CheckCircle2 size={18} />}
          iconBg="bg-[#14b8a6]"
          sparkData={sparklineData4}
          sparkColor="#14b8a6"
        />
        <PipelineStatCard
          label="Avg. Duration"
          value="14m 32s"
          change="\u2193 8.4%"
          changeColor="text-green-400"
          icon={<Clock size={18} />}
          iconBg="bg-[#3b82f6]"
          sparkData={sparklineData5}
          sparkColor="#3b82f6"
        />
        <PipelineStatCard
          label="Total Executions"
          value="412"
          change="\u2191 26%"
          changeColor="text-green-400"
          icon={<Zap size={18} />}
          iconBg="bg-[#8b5cf6]"
          sparkData={sparklineData6}
          sparkColor="#8b5cf6"
        />
      </div>

      {/* Pipeline Studio + Right Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Pipeline Studio */}
        <Card className="lg:col-span-8" padding="none">
          <div className="p-6">
            {/* Studio Header */}
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <h3 className="text-white font-semibold text-lg">Pipeline Studio</h3>
                <span className="flex items-center gap-1.5 text-xs text-green-400">
                  <span className="h-2 w-2 rounded-full bg-green-400" />
                  Live Execution
                </span>
              </div>
            </div>
            {/* Sub-header */}
            <div className="flex items-center gap-3 mb-1">
              <h4 className="text-white font-medium">Bug Bounty Recon Pipeline</h4>
              <span className="px-2 py-0.5 text-xs font-medium bg-green-500/20 text-green-400 rounded">Running</span>
              <Pencil size={14} className="text-gray-400 cursor-pointer hover:text-gray-300" />
            </div>
            {/* Info line */}
            <p className="text-xs text-gray-400 mb-4">
              Started: May 16, 2024 10:15 AM &bull; Triggered by: Agent Alpha
            </p>
            {/* Control bar */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <button className="p-1.5 bg-dark-bg border border-white/[0.08] rounded hover:bg-dark-card transition-colors">
                  <Play size={14} className="text-gray-300" />
                </button>
                <button className="p-1.5 bg-dark-bg border border-white/[0.08] rounded hover:bg-dark-card transition-colors">
                  <Pause size={14} className="text-gray-300" />
                </button>
                <button className="p-1.5 bg-dark-bg border border-white/[0.08] rounded hover:bg-dark-card transition-colors">
                  <Square size={14} className="text-gray-300" />
                </button>
                <button className="p-1.5 bg-dark-bg border border-white/[0.08] rounded hover:bg-dark-card transition-colors">
                  <Maximize2 size={14} className="text-gray-300" />
                </button>
                <button className="p-1.5 bg-dark-bg border border-white/[0.08] rounded hover:bg-dark-card transition-colors">
                  <Grid size={14} className="text-gray-300" />
                </button>
              </div>
              <button className="px-3 py-1.5 text-xs text-gray-300 bg-dark-bg border border-white/[0.08] rounded hover:bg-dark-card transition-colors">
                View Logs
              </button>
            </div>
          </div>

          {/* Flow Visualization */}
          <div className="relative bg-dark-bg border-t border-b border-white/[0.05] px-6 py-4">
            <svg viewBox="0 0 950 260" className="w-full h-auto" preserveAspectRatio="xMidYMid meet">
              {/* Connection lines */}
              <line x1="130" y1="90" x2="180" y2="90" stroke="#4b5563" strokeWidth="2" />
              <line x1="290" y1="90" x2="340" y2="90" stroke="#4b5563" strokeWidth="2" />
              <line x1="450" y1="90" x2="500" y2="90" stroke="#4b5563" strokeWidth="2" />
              <line x1="610" y1="90" x2="660" y2="90" stroke="#4b5563" strokeWidth="2" />
              <line x1="770" y1="90" x2="820" y2="90" stroke="#4b5563" strokeWidth="2" />
              {/* Branch connection from Port Scan to Content Discovery */}
              <path d="M 395 110 L 395 180" stroke="#4b5563" strokeWidth="2" fill="none" />

              {/* Node 1: TRIGGER */}
              <g>
                <rect x="20" y="50" width="110" height="80" rx="6" fill="#1e2035" stroke="#4b5563" strokeWidth="1" />
                <text x="75" y="67" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">TRIGGER</text>
                <text x="75" y="84" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">New Target</text>
                <text x="75" y="98" textAnchor="middle" fill="#9ca3af" fontSize="8">target.com</text>
                <circle cx="55" cy="115" r="6" fill="#10b981" opacity="0.2" />
                <path d="M 52 115 L 54 117 L 58 113" stroke="#10b981" strokeWidth="1.5" fill="none" />
                <text x="70" y="118" fill="#9ca3af" fontSize="7">2m 15s</text>
              </g>

              {/* Node 2: Subdomain Enum */}
              <g>
                <rect x="180" y="50" width="110" height="80" rx="6" fill="#1e2035" stroke="#4b5563" strokeWidth="1" />
                <text x="235" y="67" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">AGENT TASK</text>
                <text x="235" y="84" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">Subdomain Enum</text>
                <text x="235" y="98" textAnchor="middle" fill="#9ca3af" fontSize="8">Agent: Nova</text>
                <circle cx="215" cy="115" r="6" fill="#10b981" opacity="0.2" />
                <path d="M 212 115 L 214 117 L 218 113" stroke="#10b981" strokeWidth="1.5" fill="none" />
                <text x="230" y="118" fill="#9ca3af" fontSize="7">3m 42s</text>
              </g>

              {/* Node 3: Port Scan */}
              <g>
                <rect x="340" y="50" width="110" height="80" rx="6" fill="#1e2035" stroke="#4b5563" strokeWidth="1" />
                <text x="395" y="67" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">AGENT TASK</text>
                <text x="395" y="84" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">Port Scan</text>
                <text x="395" y="98" textAnchor="middle" fill="#9ca3af" fontSize="8">Agent: Vector</text>
                <circle cx="375" cy="115" r="6" fill="#10b981" opacity="0.2" />
                <path d="M 372 115 L 374 117 L 378 113" stroke="#10b981" strokeWidth="1.5" fill="none" />
                <text x="390" y="118" fill="#9ca3af" fontSize="7">2m 05s</text>
              </g>

              {/* Node 4: Tech Fingerprint */}
              <g>
                <rect x="500" y="50" width="110" height="80" rx="6" fill="#1e2035" stroke="#4b5563" strokeWidth="1" />
                <text x="555" y="67" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">AGENT TASK</text>
                <text x="555" y="84" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">Tech Fingerprint</text>
                <text x="555" y="98" textAnchor="middle" fill="#9ca3af" fontSize="8">Agent: Cipher</text>
                <circle cx="535" cy="115" r="6" fill="#10b981" opacity="0.2" />
                <path d="M 532 115 L 534 117 L 538 113" stroke="#10b981" strokeWidth="1.5" fill="none" />
                <text x="550" y="118" fill="#9ca3af" fontSize="7">0m 33s</text>
              </g>

              {/* Node 5: Vulnerability Scan */}
              <g>
                <rect x="660" y="50" width="110" height="80" rx="6" fill="#1e2035" stroke="#4b5563" strokeWidth="1" />
                <text x="715" y="67" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">PARALLEL GROUP</text>
                <text x="715" y="84" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">Vulnerability Scan</text>
                <text x="715" y="98" textAnchor="middle" fill="#9ca3af" fontSize="8">3 Tasks</text>
                <circle cx="695" cy="115" r="6" fill="#10b981" opacity="0.2" />
                <path d="M 692 115 L 694 117 L 698 113" stroke="#10b981" strokeWidth="1.5" fill="none" />
                <text x="710" y="118" fill="#9ca3af" fontSize="7">1m 33s</text>
              </g>

              {/* Node 6: Generate Report (running) */}
              <g>
                <rect x="820" y="50" width="110" height="80" rx="6" fill="#1e2035" stroke="#3b82f6" strokeWidth="1.5" />
                <text x="875" y="67" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">AGGREGATE</text>
                <text x="875" y="84" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">Generate Report</text>
                <text x="875" y="98" textAnchor="middle" fill="#9ca3af" fontSize="8">Agent: Alpha</text>
                <circle cx="860" cy="115" r="6" fill="#3b82f6" opacity="0.3" />
                <circle cx="860" cy="115" r="3" fill="#3b82f6" />
                <text x="875" y="118" fill="#9ca3af" fontSize="7">...</text>
              </g>

              {/* Branch Node: Content Discovery */}
              <g>
                <rect x="340" y="150" width="110" height="80" rx="6" fill="#1e2035" stroke="#4b5563" strokeWidth="1" />
                <text x="395" y="167" textAnchor="middle" fill="#9ca3af" fontSize="8" fontWeight="bold">AGENT TASK</text>
                <text x="395" y="184" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="500">Content Discovery</text>
                <text x="395" y="198" textAnchor="middle" fill="#9ca3af" fontSize="8">Agent: Omega</text>
                <circle cx="375" cy="215" r="6" fill="#10b981" opacity="0.2" />
                <path d="M 372 215 L 374 217 L 378 213" stroke="#10b981" strokeWidth="1.5" fill="none" />
                <text x="390" y="218" fill="#9ca3af" fontSize="7">4m 11s</text>
              </g>
            </svg>

            {/* Zoom controls */}
            <div className="absolute left-8 bottom-14 flex flex-col gap-1">
              <button className="p-1 bg-dark-surface border border-white/[0.08] rounded text-gray-400 hover:text-white">
                <ZoomIn size={12} />
              </button>
              <button className="p-1 bg-dark-surface border border-white/[0.08] rounded text-gray-400 hover:text-white">
                <ZoomOut size={12} />
              </button>
              <button className="p-1 bg-dark-surface border border-white/[0.08] rounded text-gray-400 hover:text-white">
                <Minimize2 size={12} />
              </button>
            </div>

            {/* Lock icon */}
            <div className="absolute left-8 bottom-4">
              <Lock size={12} className="text-gray-500" />
            </div>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 px-6 py-3">
            <FlowLegend color="bg-green-400" label="Completed" />
            <FlowLegend color="bg-blue-400" label="In Progress" />
            <FlowLegend color="bg-gray-400" label="Pending" />
            <FlowLegend color="bg-red-400" label="Failed" />
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-gray-500 line-through" />
              <span className="text-[10px] text-gray-400 line-through">Skipped</span>
            </span>
          </div>
        </Card>

        {/* Right Sidebar */}
        <Card className="lg:col-span-4" padding="none">
          {/* Tabs */}
          <div className="flex border-b border-white/[0.08]">
            <button className="px-4 py-3 text-sm font-medium text-white border-b-2 border-blue-500">
              Details
            </button>
            <button className="px-4 py-3 text-sm font-medium text-gray-400 hover:text-gray-300">
              Executions
            </button>
            <button className="px-4 py-3 text-sm font-medium text-gray-400 hover:text-gray-300">
              Settings
            </button>
          </div>

          {/* Details Tab Content */}
          <div className="p-5 space-y-5">
            {/* Pipeline name & status */}
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h4 className="text-white font-semibold">Bug Bounty Recon Pipeline</h4>
                <span className="px-2 py-0.5 text-xs font-medium bg-green-500/20 text-green-400 rounded">Running</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>ID: pipe_7f2a9b4d</span>
                <Copy size={12} className="text-gray-500 cursor-pointer hover:text-gray-300" />
              </div>
            </div>

            {/* Description */}
            <div>
              <h5 className="text-xs text-gray-400 uppercase tracking-wide mb-1">Description</h5>
              <p className="text-sm text-gray-300 leading-relaxed">
                Automated reconnaissance pipeline for bug bounty engagements. Performs enumeration, scanning and generates comprehensive report.
              </p>
            </div>

            {/* Metadata */}
            <div>
              <h5 className="text-xs text-gray-400 uppercase tracking-wide mb-2">Metadata</h5>
              <div className="space-y-2">
                <MetadataRow label="Created by" value="Navi/Hitmics" />
                <MetadataRow label="Created" value="May 10, 2024" />
                <MetadataRow label="Last Executed" value="May 16, 2024 10:15 AM" />
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">Pipeline Status</span>
                  <span className="px-2 py-0.5 text-xs font-medium bg-green-500/20 text-green-400 rounded">Healthy</span>
                </div>
              </div>
            </div>

            {/* Recent Executions */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h5 className="text-xs text-gray-400 uppercase tracking-wide">Recent Executions</h5>
                <span className="text-xs text-blue-400 cursor-pointer hover:text-blue-300">View All</span>
              </div>
              <div className="space-y-2">
                {recentExecutions.map((exec, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-gray-400">{exec.date}</span>
                    <span className={`px-2 py-0.5 rounded font-medium ${
                      exec.status === 'Running' ? 'bg-green-500/20 text-green-400' :
                      exec.status === 'Completed' ? 'bg-green-500/20 text-green-400' :
                      'bg-red-500/20 text-red-400'
                    }`}>
                      {exec.status}
                    </span>
                    <span className="text-gray-400 w-16 text-right">{exec.duration}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Bottom Four-Column Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Column 1: Pipeline Templates */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Pipeline Templates</h3>
            <span className="text-xs text-blue-400 cursor-pointer hover:text-blue-300">View All</span>
          </div>
          <div className="space-y-3">
            {pipelineTemplates.map((template) => (
              <div key={template.name} className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">{template.name}</p>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                    template.category === 'Security' ? 'bg-red-500/20 text-red-400' :
                    template.category === 'DevOps' ? 'bg-blue-500/20 text-blue-400' :
                    'bg-purple-500/20 text-purple-400'
                  }`}>
                    {template.category}
                  </span>
                </div>
                <span className="text-xs text-gray-400">{template.tasks} Tasks</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-blue-400 mt-4 cursor-pointer hover:text-blue-300">Browse All Templates</p>
        </Card>

        {/* Column 2: Execution Trends */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Execution Trends</h3>
            <span className="text-[10px] text-gray-400 bg-dark-bg border border-white/[0.08] px-2 py-0.5 rounded">7 Days</span>
          </div>
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={executionTrendsData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis
                  dataKey="date"
                  stroke="#6b7280"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="#6b7280"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                  domain={[0, 40]}
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
                <Line type="monotone" dataKey="success" stroke="#10b981" strokeWidth={2} dot={false} name="Success" />
                <Line type="monotone" dataKey="failed" stroke="#ef4444" strokeWidth={2} dot={false} name="Failed" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="flex items-center gap-4 mt-2">
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-green-500" />
              <span className="text-[10px] text-gray-400">Success</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-red-500" />
              <span className="text-[10px] text-gray-400">Failed</span>
            </div>
          </div>
        </Card>

        {/* Column 3: Top Pipeline Runs (24h) */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Top Pipeline Runs (24h)</h3>
          </div>
          <div className="space-y-3">
            {topPipelineRuns.map((pipeline) => (
              <div key={pipeline.name} className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 truncate">{pipeline.name}</p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full"
                      style={{ width: `${(pipeline.runs / 23) * 100}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400 w-6 text-right">{pipeline.runs}</span>
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-blue-400 mt-4 cursor-pointer hover:text-blue-300">View All Pipelines</p>
        </Card>

        {/* Column 4: Resource Usage (24h) */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-white font-semibold text-sm">Resource Usage (24h)</h3>
          </div>
          <div className="h-36 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={resourceUsageData}
                  cx="50%"
                  cy="50%"
                  innerRadius={40}
                  outerRadius={60}
                  dataKey="value"
                  stroke="none"
                >
                  {resourceUsageData.map((entry, index) => (
                    <Cell key={index} fill={entry.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            {/* Center text */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-xs font-bold text-white">1.24M</span>
              <span className="text-[9px] text-gray-400">Total Tokens</span>
            </div>
          </div>
          {/* Legend */}
          <div className="grid grid-cols-2 gap-1 mt-2">
            {resourceUsageData.map((item) => (
              <div key={item.name} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                <span className="text-[10px] text-gray-400">{item.name}: {item.value}%</span>
              </div>
            ))}
          </div>
          {/* Total cost */}
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/[0.08]">
            <span className="text-xs text-gray-400">Total Cost:</span>
            <div className="flex items-center gap-1">
              <span className="text-sm text-white font-semibold">$42.68</span>
              <span className="text-[10px] text-green-400">{'\u2191'} 7%</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

// Helper components

function PipelineStatCard({
  label,
  value,
  change,
  changeColor,
  badge,
  icon,
  iconBg,
  sparkData,
  sparkColor,
}: {
  label: string;
  value: string;
  change: string;
  changeColor: string;
  badge?: boolean;
  icon: React.ReactNode;
  iconBg: string;
  sparkData: Array<{ v: number }>;
  sparkColor: string;
}) {
  return (
    <Card padding="lg">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-xs text-gray-400 mb-1">{label}</p>
          <p className="text-xl font-bold text-white">{value}</p>
          {badge ? (
            <span className={`inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 text-[10px] font-medium rounded bg-green-500/20 ${changeColor}`}>
              {change}
            </span>
          ) : (
            <span className={`text-xs ${changeColor} mt-1 block`}>{change}</span>
          )}
        </div>
        <div className={`w-9 h-9 ${iconBg} rounded-lg flex items-center justify-center text-white`}>
          {icon}
        </div>
      </div>
      {/* Sparkline */}
      <div className="h-8 mt-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={sparkData}>
            <defs>
              <linearGradient id={`spark-${label.replace(/[^a-zA-Z]/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={sparkColor} stopOpacity={0.3} />
                <stop offset="95%" stopColor={sparkColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="v"
              stroke={sparkColor}
              fill={`url(#spark-${label.replace(/[^a-zA-Z]/g, '')})`}
              strokeWidth={1.5}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function FlowLegend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      <span className="text-[10px] text-gray-400">{label}</span>
    </div>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-gray-400">{label}</span>
      <span className="text-xs text-white">{value}</span>
    </div>
  );
}
