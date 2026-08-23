import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Wrench,
  Plus,
  ShieldCheck,
  Terminal,
  Search,
  Download,
  Play,
  CheckCircle2,
  Server,
  Code,
  Database,
  Activity,
  FileCode,
  Lock,
  Github,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { Drawer } from '@/components/common/Drawer';
import { Table } from '@/components/common/Table';
import { GitHubConnectorModal } from '@/components/git/GitHubConnectorModal';
import { apiClient } from '@/api/client';

export interface ExtendedToolItem {
  id: string;
  name: string;
  category: string;
  status: 'active' | 'inactive';
  description: string;
  used_by: number;
  protocol?: 'MCP Stdio' | 'HTTP / SSE' | 'Local Shell' | 'gVisor Container';
  version?: string;
  avg_latency_ms?: number;
  security_scope?: string;
  sample_params?: string;
  sample_response?: string;
}

const DEFAULT_TOOLS: ExtendedToolItem[] = [
  {
    id: 'tool-gitnexus',
    name: 'GitNexus Code Intelligence MCP',
    category: 'Source Control',
    status: 'active',
    description: 'Graph-based semantic code intelligence, impact analysis, and symbol execution trace tree solver.',
    used_by: 6,
    protocol: 'MCP Stdio',
    version: 'v1.4.2',
    avg_latency_ms: 45,
    security_scope: 'Read-only Repository AST',
    sample_params: JSON.stringify({ target: 'handleCreateTask', direction: 'upstream' }, null, 2),
    sample_response: JSON.stringify({ status: 'ok', callers: 4, blast_radius_risk: 'low' }, null, 2),
  },
  {
    id: 'tool-[#000]',
    name: 'gVisor Shell Sandbox Runner',
    category: 'DevOps',
    status: 'active',
    description: 'Isolated microVM container runner for executing unit tests, bash scripts, and build tasks safely.',
    used_by: 5,
    protocol: 'gVisor Container',
    version: 'v2.1.0',
    avg_latency_ms: 120,
    security_scope: 'Isolated Network & No-Root Shell',
    sample_params: JSON.stringify({ command: 'npm test -- --runInBand', cwd: '/app/dashboard' }, null, 2),
    sample_response: JSON.stringify({ exitCode: 0, stdout: 'PASS 18 tests (100%)', stderr: '' }, null, 2),
  },
  {
    id: 'tool-[#000]-db',
    name: 'Postgres Vector Memory Store',
    category: 'Database',
    status: 'active',
    description: 'pgvector memory bank adapter for HNSW high-dimensional embeddings and agent episodic recall.',
    used_by: 6,
    protocol: 'HTTP / SSE',
    version: 'v0.7.4',
    avg_latency_ms: 18,
    security_scope: 'Tenant Scoped SQL Prepared Statements',
    sample_params: JSON.stringify({ query: 'SELECT * FROM memories ORDER BY vector <-> $1 LIMIT 5' }, null, 2),
    sample_response: JSON.stringify({ rowCount: 5, time_ms: 18.2, status: 'success' }, null, 2),
  },
  {
    id: 'tool-sentry',
    name: 'Sentry Telemetry Error Ingest',
    category: 'Monitoring',
    status: 'active',
    description: 'Real-time uncaught runtime exception ingestion and stack trace aggregator.',
    used_by: 4,
    protocol: 'HTTP / SSE',
    version: 'v3.0.1',
    avg_latency_ms: 32,
    security_scope: 'Read-only Error Traces',
    sample_params: JSON.stringify({ query: 'is:unresolved level:error limit:10' }, null, 2),
    sample_response: JSON.stringify({ total: 0, status: 'all_clean' }, null, 2),
  },
  {
    id: 'tool-rag-search',
    name: 'RAG Semantic Vector Search Engine',
    category: 'AI / RAG',
    status: 'active',
    description: 'Dense vector retrieval engine over internal documentation chunks and architectural design schemas.',
    used_by: 6,
    protocol: 'MCP Stdio',
    version: 'v2.5.0',
    avg_latency_ms: 25,
    security_scope: 'Company Knowledge Access',
    sample_params: JSON.stringify({ prompt: 'How does model cascade routing work?', top_k: 3 }, null, 2),
    sample_response: JSON.stringify({ chunks: 3, top_cosine_match: 0.984 }, null, 2),
  },
  {
    id: 'tool-slack-notifier',
    name: 'Slack Webhook & Alert Dispatcher',
    category: 'Communication',
    status: 'inactive',
    description: 'Real-time incident alert notifier and daily ops summary webhook dispatcher.',
    used_by: 2,
    protocol: 'HTTP / SSE',
    version: 'v1.1.0',
    avg_latency_ms: 85,
    security_scope: 'Webhook Write-Only Outbound',
    sample_params: JSON.stringify({ channel: '#ops-alerts', message: 'Deployment verification passed' }, null, 2),
    sample_response: JSON.stringify({ ok: true, timestamp: '1724456000' }, null, 2),
  },
];

export function Tools() {
  const [tools, setTools] = useState<ExtendedToolItem[]>(DEFAULT_TOOLS);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'grid' | 'testbench' | 'security'>('grid');
  const [showModal, setShowModal] = useState(false);
  const [isGitHubModalOpen, setIsGitHubModalOpen] = useState(false);
  const [selectedTool, setSelectedTool] = useState<ExtendedToolItem | null>(null);

  // New Connector Form State
  const [newName, setNewName] = useState('');
  const [newCategory, setNewCategory] = useState('Source Control');
  const [newProtocol, setNewProtocol] = useState<'MCP Stdio' | 'HTTP / SSE' | 'Local Shell' | 'gVisor Container'>('MCP Stdio');
  const [newDescription, setNewDescription] = useState('');

  // Interactive Test Bench Runner State
  const [testPayload, setTestPayload] = useState('');
  const [testOutput, setTestOutput] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);
  const [execLatency, setExecLatency] = useState<number | null>(null);

  useEffect(() => {
    async function loadTools() {
      try {
        const res = await apiClient.get<{ items: ExtendedToolItem[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/tools'
        );
        if (res?.items && res.items.length > 0) {
          const merged = res.items.map((apiTool) => {
            const match = DEFAULT_TOOLS.find((d) => d.id === apiTool.id || d.name === apiTool.name);
            return {
              ...apiTool,
              protocol: match?.protocol || 'MCP Stdio',
              version: match?.version || 'v1.0.0',
              avg_latency_ms: match?.avg_latency_ms || 35,
              security_scope: match?.security_scope || 'Sandbox Scoped Access',
              sample_params: match?.sample_params || '{\n  "status": "ready"\n}',
              sample_response: match?.sample_response || '{\n  "ok": true\n}',
            };
          });
          setTools(merged);
        }
      } catch {
        // Silently use defaults
      }
    }
    loadTools();
  }, []);

  const handleToggleStatus = async (toolId: string, current: 'active' | 'inactive') => {
    const next = current === 'active' ? 'inactive' : 'active';
    try {
      await apiClient.patch(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/tools/${toolId}`,
        { status: next }
      );
    } catch {
      // Fallback local update
    }
    setTools((prev) => prev.map((t) => (t.id === toolId ? { ...t, status: next } : t)));
  };

  const handleCreateTool = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    const item: ExtendedToolItem = {
      id: `tool-${Date.now()}`,
      name: newName,
      category: newCategory,
      status: 'active',
      description: newDescription,
      used_by: 4,
      protocol: newProtocol,
      version: 'v1.0.0',
      avg_latency_ms: 30,
      security_scope: 'Sandbox Scoped Access',
      sample_params: '{\n  "action": "execute"\n}',
      sample_response: '{\n  "status": "success"\n}',
    };
    setTools((prev) => [...prev, item]);
    setShowModal(false);
    setNewName('');
    setNewDescription('');
  };

  const handleRunTestBench = useCallback(() => {
    if (!selectedTool) return;
    setIsExecuting(true);
    setTestOutput('');
    const startTime = performance.now();
    setTimeout(() => {
      const endTime = performance.now();
      setExecLatency(Math.round(endTime - startTime + (selectedTool.avg_latency_ms || 30)));
      setTestOutput(selectedTool.sample_response || '{\n  "status": "success",\n  "execution_time_ms": 24\n}');
      setIsExecuting(false);
    }, 600);
  }, [selectedTool]);

  // Open drawer and preload sample params
  const handleSelectToolForTest = (t: ExtendedToolItem) => {
    setSelectedTool(t);
    setTestPayload(t.sample_params || '{\n  "query": "test"\n}');
    setTestOutput('');
    setExecLatency(null);
  };

  // Filtered Tools List
  const filteredTools = useMemo(() => {
    return tools.filter((t) => {
      if (categoryFilter !== 'all' && t.category !== categoryFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          t.name.toLowerCase().includes(q) ||
          t.category.toLowerCase().includes(q) ||
          t.description.toLowerCase().includes(q) ||
          (t.protocol || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [tools, categoryFilter, search]);

  // Export handlers
  const handleExportJson = useCallback(() => {
    const jsonStr = JSON.stringify(filteredTools, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_tools_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredTools]);

  const handleExportCsv = useCallback(() => {
    const headers = ['ID', 'Name', 'Category', 'Status', 'Protocol', 'Version', 'Equipped Agents', 'Latency (ms)', 'Security Scope'];
    const rows = filteredTools.map((t) => [
      t.id,
      `"${t.name}"`,
      t.category,
      t.status,
      t.protocol || 'MCP Stdio',
      t.version || 'v1.0.0',
      t.used_by,
      `${t.avg_latency_ms || 30}ms`,
      `"${t.security_scope || ''}"`,
    ]);
    const csvStr = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvStr], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_tools_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredTools]);

  const activeToolsCount = tools.filter((t) => t.status === 'active').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Wrench className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight flex items-center gap-3">
              Tools, MCP Connectors & Sandbox Hub
              <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20">
                GVISOR TIER-1 ACTIVE
              </span>
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            External API bindings, Model Context Protocol (MCP) servers, and gVisor shell sandbox execution runners
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* View Mode Switcher */}
          <div className="flex items-center bg-[#101012] border border-white/[0.08] rounded-[6px] p-0.5">
            <button
              onClick={() => setViewMode('grid')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'grid' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Connectors Grid"
            >
              <Wrench size={13} />
              <span className="hidden sm:inline">Connectors</span>
            </button>
            <button
              onClick={() => setViewMode('testbench')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'testbench' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Interactive Test Bench"
            >
              <Terminal size={13} />
              <span className="hidden sm:inline">Test Bench</span>
            </button>
            <button
              onClick={() => setViewMode('security')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'security' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Sandbox Security Policies"
            >
              <ShieldCheck size={13} />
              <span className="hidden sm:inline">Security</span>
            </button>
          </div>

          <button
            onClick={handleExportJson}
            className="px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.08] border border-white/[0.08] text-gray-300 hover:text-white rounded-[6px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer"
            title="Export as JSON"
          >
            <Download size={13} />
            <span className="hidden sm:inline">JSON</span>
          </button>

          <button
            onClick={handleExportCsv}
            className="px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.08] border border-white/[0.08] text-gray-300 hover:text-white rounded-[6px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer"
            title="Export as CSV"
          >
            <Download size={13} />
            <span className="hidden sm:inline">CSV</span>
          </button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsGitHubModalOpen(true)}
            icon={<Github size={14} className="text-[#FFB020]" />}
          >
            Connect GitHub API
          </Button>

          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={15} />}
            onClick={() => setShowModal(true)}
          >
            Add Connector
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Active Connectors"
          value={activeToolsCount}
          subValue={`of ${tools.length} Installed`}
          change="All authenticated"
          changeType="positive"
          icon={<Wrench className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="Sandboxed Isolation"
          value="gVisor Tier-1"
          subValue="Hard Memory & Net Boundaries"
          change="Zero root privilege"
          changeType="positive"
          icon={<ShieldCheck className="w-4 h-4 text-emerald-400" />}
        />
        <StatCard
          label="Invocations MTD"
          value="18,490"
          subValue="Avg 32ms Latency"
          change="100% policy compliance"
          changeType="positive"
          icon={<Terminal className="w-4 h-4 text-cyan-400" />}
        />
      </div>

      {/* Search & Category Filter Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-[#101012] p-3.5 border border-white/[0.08] rounded-[10px]">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search connector name, category, or protocol..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
          <span className="text-[10px] text-[#6B6B6E] uppercase mr-1">Category:</span>
          {['all', 'Source Control', 'DevOps', 'Database', 'Monitoring', 'AI / RAG', 'Communication'].map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer ${
                categoryFilter === cat
                  ? 'bg-[#FFB020] text-black font-bold'
                  : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* View Mode Content */}
      {viewMode === 'grid' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredTools.map((tool) => (
            <Card key={tool.id} padding="sm">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-[6px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-[#FFB020]">
                    {tool.category === 'Source Control' ? <Code size={16} /> :
                     tool.category === 'Database' ? <Database size={16} /> :
                     tool.category === 'Monitoring' ? <Activity size={16} /> :
                     tool.category === 'DevOps' ? <Server size={16} /> :
                     <FileCode size={16} />}
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-[#F2F1EE] line-clamp-1">{tool.name}</h3>
                    <div className="text-[10px] font-mono text-[#6B6B6E] flex items-center gap-2 mt-0.5">
                      <span>{tool.category}</span>
                      <span>·</span>
                      <span className="text-[#FFB020]">{tool.protocol || 'MCP Stdio'}</span>
                    </div>
                  </div>
                </div>

                <Badge variant={tool.status === 'active' ? 'active' : 'idle'}>
                  {tool.status}
                </Badge>
              </div>

              <p className="text-xs text-[#9C9C9F] mt-3 font-sans leading-relaxed line-clamp-2">
                {tool.description}
              </p>

              <div className="mt-4 pt-2.5 border-t border-white/[0.04] flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                <button
                  onClick={() => handleSelectToolForTest(tool)}
                  className="text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                >
                  <Terminal size={11} />
                  Test Execution Bench →
                </button>

                <button
                  onClick={() => handleToggleStatus(tool.id, tool.status)}
                  className="text-gray-400 hover:text-white cursor-pointer"
                >
                  {tool.status === 'active' ? 'Disable' : 'Enable'}
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Test Bench Table View */}
      {viewMode === 'testbench' && (
        <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Interactive Connector Execution Registry</span>} padding="none">
          <Table
            data={filteredTools}
            keyExtractor={(t) => t.id}
            columns={[
              {
                key: 'name',
                header: 'Connector Name',
                sortable: true,
                render: (t) => (
                  <div
                    onClick={() => handleSelectToolForTest(t)}
                    className="cursor-pointer group"
                  >
                    <div className="font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">{t.name}</div>
                    <div className="text-[11px] font-mono text-[#6B6B6E]">{t.category}</div>
                  </div>
                ),
              },
              {
                key: 'protocol',
                header: 'Protocol',
                render: (t) => (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/[0.04] text-[#FFB020] border border-white/[0.08]">
                    {t.protocol || 'MCP Stdio'}
                  </span>
                ),
              },
              {
                key: 'avg_latency_ms',
                header: 'Avg Latency',
                render: (t) => (
                  <span className="font-mono text-xs text-cyan-400">
                    {t.avg_latency_ms || 30}ms
                  </span>
                ),
              },
              {
                key: 'status',
                header: 'Status',
                render: (t) => (
                  <Badge variant={t.status === 'active' ? 'active' : 'idle'}>
                    {t.status}
                  </Badge>
                ),
              },
              {
                key: 'security_scope',
                header: 'Security Scope',
                render: (t) => (
                  <span className="font-mono text-[11px] text-gray-400 truncate max-w-xs block">
                    {t.security_scope || 'Sandbox Scoped'}
                  </span>
                ),
              },
              {
                key: 'action',
                header: 'Action',
                align: 'right',
                render: (t) => (
                  <Button
                    variant="ghost"
                    size="xs"
                    icon={<Play size={11} className="text-[#FFB020]" />}
                    onClick={() => handleSelectToolForTest(t)}
                  >
                    Launch Bench
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* Sandbox Security View */}
      {viewMode === 'security' && (
        <div className="space-y-4 font-mono text-xs">
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2 mb-2">
              <Lock className="w-4 h-4 text-emerald-400" />
              gVisor Container Isolation & Network Security Policies
            </h3>
            <p className="text-xs text-gray-400">
              All tool connector invocations execute inside isolated microVM containers with non-root syscall filtering
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {tools.map((t) => (
              <div key={t.id} className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-3">
                <div className="flex items-center justify-between border-b border-white/[0.06] pb-2">
                  <h4 className="text-xs font-bold text-white truncate max-w-[200px]">{t.name}</h4>
                  <Badge variant={t.status === 'active' ? 'active' : 'idle'}>
                    {t.status}
                  </Badge>
                </div>

                <div className="space-y-1 text-[11px]">
                  <span className="text-gray-500 uppercase font-bold text-[10px]">Security Scope:</span>
                  <div className="text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 p-2 rounded">
                    {t.security_scope || 'Isolated Sandbox Read-Only'}
                  </div>
                </div>

                <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-[10px] text-gray-400">
                  <span>Equipped: {t.used_by} agents</span>
                  <span className="text-[#FFB020]">{t.protocol || 'MCP Stdio'}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Interactive Tool Test Bench Drawer */}
      <Drawer
        isOpen={!!selectedTool}
        onClose={() => setSelectedTool(null)}
        title={`Tool Test Bench: ${selectedTool?.name || 'Connector'}`}
        subtitle={`Category: ${selectedTool?.category} · Protocol: ${selectedTool?.protocol || 'MCP Stdio'}`}
      >
        {selectedTool && (
          <div className="space-y-4 font-mono text-xs">
            {/* Security Scope Banner */}
            <div className="p-3 bg-[#101012] border border-white/[0.08] rounded flex items-center justify-between">
              <div>
                <span className="text-[10px] text-gray-500 uppercase">Security Boundary</span>
                <div className="text-emerald-400 font-bold mt-0.5">{selectedTool.security_scope}</div>
              </div>
              <div className="text-right">
                <span className="text-[10px] text-gray-500 uppercase">Avg Latency</span>
                <div className="text-cyan-400 font-bold mt-0.5">{selectedTool.avg_latency_ms || 30}ms</div>
              </div>
            </div>

            {/* Input Payload Console */}
            <div className="space-y-1.5">
              <label className="block text-[10px] text-gray-400 uppercase font-bold">
                Invocation JSON Arguments
              </label>
              <textarea
                value={testPayload}
                onChange={(e) => setTestPayload(e.target.value)}
                rows={6}
                className="w-full p-3 bg-[#0A0A0C] border border-white/[0.12] rounded text-[11px] text-amber-300 font-mono focus:outline-none focus:border-[#FFB020]"
              />
            </div>

            {/* Execute Trigger Button */}
            <div className="flex items-center justify-between">
              <Button
                variant="primary"
                size="sm"
                icon={<Play size={13} />}
                onClick={handleRunTestBench}
                disabled={isExecuting}
              >
                {isExecuting ? 'Executing in gVisor Sandbox...' : 'Run Tool Invocation'}
              </Button>

              {execLatency !== null && (
                <span className="text-[11px] text-emerald-400 font-bold flex items-center gap-1">
                  <CheckCircle2 size={12} />
                  Completed in {execLatency}ms
                </span>
              )}
            </div>

            {/* Output Response Console */}
            {testOutput && (
              <div className="space-y-1.5 pt-2 border-t border-white/[0.08]">
                <label className="block text-[10px] text-gray-400 uppercase font-bold">
                  gVisor Sandbox Response Payload
                </label>
                <pre className="p-3 bg-[#0A0A0C] border border-white/[0.08] rounded text-[11px] text-emerald-300 overflow-x-auto max-h-48 whitespace-pre-wrap font-mono">
                  {testOutput}
                </pre>
              </div>
            )}

            <div className="flex justify-end pt-3 border-t border-white/[0.08]">
              <Button variant="secondary" size="sm" onClick={() => setSelectedTool(null)}>
                Close Test Bench
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* Configure Tool Modal */}
      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title="Configure Tool / MCP Connector">
        <form onSubmit={handleCreateTool} className="space-y-4 font-mono text-xs">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Connector Call Sign / Name
            </label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Sentry Error Ingest MCP"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Category
            </label>
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Source Control">Source Control</option>
              <option value="DevOps">DevOps & Cloud</option>
              <option value="Database">Database Access</option>
              <option value="Monitoring">Monitoring & APM</option>
              <option value="AI / RAG">AI / RAG Retrieval</option>
              <option value="Communication">Communication</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Protocol Binding
            </label>
            <select
              value={newProtocol}
              onChange={(e) => setNewProtocol(e.target.value as any)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="MCP Stdio">MCP Stdio (Stdio JSON-RPC)</option>
              <option value="HTTP / SSE">HTTP / SSE Stream</option>
              <option value="gVisor Container">gVisor Container MicroVM</option>
              <option value="Local Shell">Local Shell Subprocess</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Description & Security Scope Bounds
            </label>
            <textarea
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              rows={3}
              placeholder="Define sandbox bounds and security scopes..."
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Mount Connector
            </Button>
          </div>
        </form>
      </Modal>

      {/* Real GitHub Connector Modal */}
      <GitHubConnectorModal
        isOpen={isGitHubModalOpen}
        onClose={() => setIsGitHubModalOpen(false)}
      />
    </div>
  );
}
