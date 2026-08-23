import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  MessageSquare,
  Cpu,
  Activity,
  DollarSign,
  Send,
  Play,
  Pause,
  Award,
  ArrowLeft,
  Database,
} from 'lucide-react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Tabs } from '@/components/common/Tabs';
import { Skeleton } from '@/components/common/Skeleton';
import { apiClient } from '@/api/client';
import type { Agent } from '@/types/agent';

interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: string;
}

interface AgentMemory {
  id: string;
  scope: string;
  content: string;
  importance: number;
  created_at: string;
}

const telemetryGraphData = [
  { time: '08:00', tokens: 12000, latency: 42 },
  { time: '10:00', tokens: 28000, latency: 38 },
  { time: '12:00', tokens: 45000, latency: 35 },
  { time: '14:00', tokens: 62000, latency: 32 },
  { time: '16:00', tokens: 39000, latency: 36 },
  { time: '18:00', tokens: 21000, latency: 40 },
];

const defaultAgentFallbackMap: Record<string, Agent> = {
  'agent-atlas': { id: 'agent-atlas', company_id: '00000000-0000-4000-8000-000000000001', name: 'Atlas-01', title: 'Chief Executive Officer', role: 'ceo', department_id: 'dept-exec', team_id: null, manager_id: null, status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['strategy', 'executive oversight', 'delegation'], responsibilities: 'Executive leadership and company velocity', objectives: 'Maintain organizational roadmap', budget_monthly_cents: 50000, spent_monthly_cents: 18450, performance_score: 98, soul_description: 'Visionary and decisive executive model tasked with overarching resource allocation and inter-department delegation.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  'agent-nova': { id: 'agent-nova', company_id: '00000000-0000-4000-8000-000000000001', name: 'Nova-02', title: 'Chief Technology Officer', role: 'cto', department_id: 'dept-eng', team_id: null, manager_id: 'agent-atlas', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['architecture', 'system design', 'code review'], responsibilities: 'Technical leadership and system resilience', objectives: 'Decoupled, zero-latency microservices', budget_monthly_cents: 40000, spent_monthly_cents: 22100, performance_score: 96, soul_description: 'Pragmatic and architectural engineer with high standards for type safety, modular microservices, and observability.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  'agent-bolt': { id: 'agent-bolt', company_id: '00000000-0000-4000-8000-000000000001', name: 'Bolt-03', title: 'Senior Backend Engineer', role: 'engineer', department_id: 'dept-eng', team_id: 'team-backend', manager_id: 'agent-nova', status: 'active', adapter_type: 'openai', model: 'gpt-4o', capabilities: ['node.js', 'redis', 'postgresql', 'distributed systems'], responsibilities: 'Backend microservices & vector cache layer', objectives: 'Sub-millisecond API responses', budget_monthly_cents: 30000, spent_monthly_cents: 14200, performance_score: 94, soul_description: 'Speed-first problem solver specialized in database indexing, caching strategies, and concurrency.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  'agent-pixel': { id: 'agent-pixel', company_id: '00000000-0000-4000-8000-000000000001', name: 'Pixel-04', title: 'Frontend & 3D Specialist', role: 'engineer', department_id: 'dept-eng', team_id: 'team-frontend', manager_id: 'agent-nova', status: 'active', adapter_type: 'openai', model: 'gpt-4o', capabilities: ['react', 'three.js', 'shaders', 'tailwind'], responsibilities: 'OpenOffice 2D & 3D isometric interface', objectives: 'Silky smooth 60fps rendering', budget_monthly_cents: 25000, spent_monthly_cents: 9800, performance_score: 92, soul_description: 'Detail-obsessed visual craftsman combining shader mechanics, reactive rendering, and spatial collision geometry.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  'agent-sage': { id: 'agent-sage', company_id: '00000000-0000-4000-8000-000000000001', name: 'Sage-05', title: 'AI Research Lead', role: 'researcher', department_id: 'dept-ai', team_id: 'team-eval', manager_id: 'agent-atlas', status: 'idle', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['evals', 'rag', 'prompt distillation', 'safety'], responsibilities: 'Model benchmarking and multi-agent coordination', objectives: 'Optimal token-to-accuracy efficiency', budget_monthly_cents: 40000, spent_monthly_cents: 18900, performance_score: 97, soul_description: 'Methodical researcher running ablation studies and continuous accuracy evals.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  'agent-forge': { id: 'agent-forge', company_id: '00000000-0000-4000-8000-000000000001', name: 'Forge-06', title: 'DevOps & Infrastructure Lead', role: 'devops', department_id: 'dept-ops', team_id: 'team-infra', manager_id: 'agent-nova', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['k8s', 'terraform', 'ci/cd', 'observability'], responsibilities: 'Multi-region cluster stability and automated rollouts', objectives: '99.99% uptime for AI inference fleet', budget_monthly_cents: 35000, spent_monthly_cents: 16500, performance_score: 95, soul_description: 'Unyielding reliability guardian ensuring high availability and zero deployment downtime.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  'agent-shield': { id: 'agent-shield', company_id: '00000000-0000-4000-8000-000000000001', name: 'Shield-07', title: 'Security & QA Auditor', role: 'qa', department_id: 'dept-ops', team_id: 'team-qa-sec', manager_id: 'agent-forge', status: 'active', adapter_type: 'openai', model: 'gpt-4o-mini', capabilities: ['penetration testing', 'rbac auditing', 'rate-limiting'], responsibilities: 'Automated policy enforcement & vulnerability scanning', objectives: 'Zero critical security regressions', budget_monthly_cents: 15000, spent_monthly_cents: 7200, performance_score: 93, soul_description: 'Vigilant security watchdog with strict compliance gates and automated test suites.', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
};

export function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<Agent | null>(() => (id && defaultAgentFallbackMap[id]) ? defaultAgentFallbackMap[id] : null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('chat');
  
  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { id: 'msg-init', sender: 'agent', text: 'Telemetry synchronization active. All systems operational.', timestamp: new Date(Date.now() - 300000).toISOString() }
  ]);
  const [inputPrompt, setInputPrompt] = useState('');
  const [sendingChat, setSendingChat] = useState(false);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Memories
  const [memories, setMemories] = useState<AgentMemory[]>([
    { id: 'mem-1', scope: 'work', content: 'Optimized vector cache layer reducing p99 latency to 32ms', importance: 5, created_at: new Date(Date.now() - 3600000 * 2).toISOString() },
    { id: 'mem-2', scope: 'work', content: 'Coordinated model routing fallback between Claude 3.7 and GPT-4o', importance: 4, created_at: new Date(Date.now() - 3600000 * 5).toISOString() },
  ]);

  useEffect(() => {
    let isMounted = true;
    async function loadAgentData() {
      if (!id) return;
      try {
        const [agentData, chatData, memoryData] = await Promise.allSettled([
          apiClient.get<Agent>(`/api/v1/companies/00000000-0000-4000-8000-000000000001/agents/${id}`),
          apiClient.get<ChatMessage[]>(`/api/v1/agents/${id}/chat`),
          apiClient.get<{ items: AgentMemory[] }>(`/api/v1/agents/${id}/memory`),
        ]);
        if (!isMounted) return;
        if (agentData.status === 'fulfilled' && agentData.value) {
          setAgent(agentData.value);
        } else if (!agent && defaultAgentFallbackMap[id]) {
          setAgent(defaultAgentFallbackMap[id]);
        }
        if (chatData.status === 'fulfilled' && Array.isArray(chatData.value) && chatData.value.length > 0) {
          setChatMessages(chatData.value);
        }
        if (memoryData.status === 'fulfilled' && memoryData.value?.items?.length) {
          setMemories(memoryData.value.items);
        }
      } catch (err) {
        // Use fallback silently
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadAgentData();
    return () => {
      isMounted = false;
    };
  }, [id]);

  useEffect(() => {
    if (activeTab === 'chat') {
      chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [chatMessages, activeTab]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputPrompt.trim() || !id || sendingChat) return;

    const userText = inputPrompt;
    setInputPrompt('');
    setSendingChat(true);

    const tempUserMsg: ChatMessage = {
      id: `usr-${Date.now()}`,
      sender: 'user',
      text: userText,
      timestamp: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, tempUserMsg]);

    try {
      const res = await apiClient.post<{ message: ChatMessage; history: ChatMessage[] }>(
        `/api/v1/agents/${id}/chat`,
        { prompt: userText }
      );
      if (res?.history) {
        setChatMessages(res.history);
      } else if (res?.message) {
        setChatMessages((prev) => [...prev, res.message]);
      }
    } catch (err) {
      console.error('Failed to send command to agent', err);
    } finally {
      setSendingChat(false);
    }
  };

  const handleTrainAgent = async () => {
    if (!id || !agent) return;
    try {
      const res = await apiClient.post<{ success: boolean; new_score: number }>(`/api/v1/agents/${id}/train`);
      if (res?.new_score) {
        setAgent((prev) => (prev ? { ...prev, performance_score: res.new_score } : prev));
      }
    } catch (err) {
      console.error('Training module trigger failed', err);
    }
  };

  const handleToggleStatus = async () => {
    if (!id || !agent) return;
    const nextStatus = agent.status === 'active' ? 'idle' : 'active';
    try {
      await apiClient.patch(`/api/v1/companies/00000000-0000-4000-8000-000000000001/agents/${id}`, {
        status: nextStatus,
      });
      setAgent((prev) => (prev ? { ...prev, status: nextStatus } : prev));
    } catch (err) {
      console.error('Failed to update agent status', err);
    }
  };

  if (loading) {
    return <Skeleton variant="card" count={3} />;
  }

  if (!agent) {
    return (
      <div className="p-8 text-center bg-[#141416] border border-white/[0.08] rounded-[10px] text-xs font-mono text-[#6B6B6E]">
        Agent not found.
        <div className="mt-3">
          <Button variant="secondary" size="sm" onClick={() => navigate('/agents')}>
            Return to Directory
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Header Card */}
      <div className="p-6 bg-[#141416] border border-white/[0.08] rounded-[10px] flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-start gap-4">
          <button
            onClick={() => navigate('/agents')}
            className="p-2 rounded-[6px] bg-white/[0.04] text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.08] transition-colors cursor-pointer shrink-0"
            aria-label="Back to agents"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>

          <div className="w-12 h-12 rounded-[6px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-base font-bold font-mono text-[#FFB020] shrink-0">
            {agent.name.substring(0, 2).toUpperCase()}
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-lg font-display font-medium text-[#F2F1EE] tracking-tight">
                {agent.name}
              </h1>
              <Badge variant={agent.status as any}>{agent.status}</Badge>
            </div>
            <div className="text-xs font-mono text-[#6B6B6E]">
              {agent.title} · <span className="uppercase text-[#A8A8AB]">{agent.role}</span>
            </div>
            <div className="text-[11px] font-mono text-[#A8A8AB]">
              Model: <span className="text-[#FFB020]">{agent.model}</span>
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2.5 shrink-0">
          <Button
            variant={agent.status === 'active' ? 'secondary' : 'primary'}
            size="sm"
            icon={agent.status === 'active' ? <Pause size={14} /> : <Play size={14} />}
            onClick={handleToggleStatus}
          >
            {agent.status === 'active' ? 'Pause Execution' : 'Wake Agent'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            icon={<Award size={14} className="text-[#FFB020]" />}
            onClick={handleTrainAgent}
          >
            Train (+Score)
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Performance Index"
          value={`${agent.performance_score ?? 94}%`}
          subValue="Telemetry Benchmark"
          change="+3% score gain MTD"
          changeType="positive"
          icon={<Activity className="w-4 h-4" />}
        />
        <StatCard
          label="Monthly Spend"
          value={`$${((agent.spent_monthly_cents ?? 0) / 100).toFixed(2)}`}
          subValue={`/ $${((agent.budget_monthly_cents ?? 30000) / 100).toFixed(0)}`}
          change="Within allocated cap"
          changeType="neutral"
          icon={<DollarSign className="w-4 h-4" />}
        />
        <StatCard
          label="Context & Memory"
          value={`${memories.length} Entries`}
          subValue="Episodic Graph"
          change="Last compact 2d ago"
          changeType="neutral"
          icon={<Database className="w-4 h-4" />}
        />
      </div>

      {/* Navigation Tabs */}
      <Tabs
        activeTab={activeTab}
        onChange={setActiveTab}
        tabs={[
          { id: 'chat', label: 'Operator Console & Live Chat', icon: <MessageSquare size={14} /> },
          { id: 'dossier', label: 'Soul & Capabilities Dossier', icon: <Cpu size={14} /> },
          { id: 'memory', label: 'Context Memory Entries', icon: <Database size={14} />, count: memories.length },
          { id: 'telemetry', label: 'Token Consumption Telemetry', icon: <Activity size={14} /> },
        ]}
      />

      {/* Tab Panels */}
      {activeTab === 'chat' && (
        <Card padding="none">
          <div className="h-[420px] flex flex-col bg-[#101012] rounded-[10px] overflow-hidden">
            {/* Chat Messages Log */}
            <div className="flex-1 p-4 overflow-y-auto space-y-3">
              {chatMessages.length === 0 ? (
                <div className="h-full flex items-center justify-center text-xs font-mono text-[#6B6B6E]">
                  Send a command or prompt to initiate conversation with {agent.name}.
                </div>
              ) : (
                chatMessages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex flex-col max-w-xl ${
                      msg.sender === 'user' ? 'ml-auto items-end' : 'mr-auto items-start'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 mb-1 text-[10px] font-mono text-[#6B6B6E]">
                      <span>{msg.sender === 'user' ? 'Operator' : agent.name}</span>
                      <span>·</span>
                      <span>
                        {new Date(msg.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                    </div>
                    <div
                      className={`p-3 rounded-[8px] text-xs leading-relaxed font-mono ${
                        msg.sender === 'user'
                          ? 'bg-[#FFB020] text-[#0A0A0B] font-medium'
                          : 'bg-[#1C1C1F] text-[#F2F1EE] border border-white/[0.08]'
                      }`}
                    >
                      {msg.text}
                    </div>
                  </div>
                ))
              )}
              <div ref={chatBottomRef} />
            </div>

            {/* Chat Input Bar */}
            <form
              onSubmit={handleSendMessage}
              className="p-3 bg-[#141416] border-t border-white/[0.08] flex items-center gap-2"
            >
              <input
                type="text"
                value={inputPrompt}
                onChange={(e) => setInputPrompt(e.target.value)}
                placeholder={`Instruct ${agent.name}... (e.g. "Optimize circuit breaker threshold")`}
                className="flex-1 px-3 py-2 bg-[#101012] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] font-sans"
              />
              <Button
                variant="primary"
                size="sm"
                type="submit"
                loading={sendingChat}
                icon={<Send size={14} />}
              >
                Send
              </Button>
            </form>
          </div>
        </Card>
      )}

      {activeTab === 'dossier' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Core Objectives & Responsibilities</span>}>
            <div className="space-y-4 text-xs font-sans">
              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Responsibilities</label>
                <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-[#F2F1EE] leading-relaxed">
                  {agent.responsibilities || 'Execute assigned domain tasks with high fidelity.'}
                </div>
              </div>

              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Strategic Objectives</label>
                <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-[#F2F1EE] leading-relaxed">
                  {agent.objectives || 'Maintain fast operational velocity and low error rate.'}
                </div>
              </div>

              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Persona & Soul Descriptor</label>
                <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-[#A8A8AB] leading-relaxed italic">
                  "{agent.soul_description || 'Pragmatic, disciplined autonomous agent.'}"
                </div>
              </div>
            </div>
          </Card>

          <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Capabilities & Model Envelope</span>}>
            <div className="space-y-4">
              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-2">Capability Envelopes</label>
                <div className="flex flex-wrap gap-1.5">
                  {(agent.capabilities || ['general_execution']).map((cap) => (
                    <span
                      key={cap}
                      className="px-2.5 py-1 bg-white/[0.04] border border-white/[0.08] text-xs font-mono text-[#FFB020] rounded-[4px]"
                    >
                      {cap}
                    </span>
                  ))}
                </div>
              </div>

              <div className="pt-3 border-t border-white/[0.06] space-y-2 text-xs font-mono">
                <div className="flex justify-between text-[#A8A8AB]">
                  <span>Adapter Adapter</span>
                  <span className="text-[#F2F1EE]">{agent.adapter_type}</span>
                </div>
                <div className="flex justify-between text-[#A8A8AB]">
                  <span>LLM Backbone</span>
                  <span className="text-[#F2F1EE]">{agent.model}</span>
                </div>
                <div className="flex justify-between text-[#A8A8AB]">
                  <span>Monthly Budget Cap</span>
                  <span className="text-[#F2F1EE]">${((agent.budget_monthly_cents ?? 0) / 100).toFixed(2)}</span>
                </div>
              </div>
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'memory' && (
        <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Agent Long-Term Memory Bank</span>}>
          <div className="space-y-3">
            {memories.length === 0 ? (
              <div className="p-8 text-center text-xs font-mono text-[#6B6B6E]">
                No persistent memory entries recorded for this agent yet.
              </div>
            ) : (
              memories.map((mem) => (
                <div key={mem.id} className="p-3.5 bg-[#101012] border border-white/[0.06] rounded-[6px] space-y-1.5">
                  <div className="flex items-center justify-between text-[11px] font-mono">
                    <span className="text-[#FFB020] uppercase font-medium">{mem.scope}</span>
                    <span className="text-[#6B6B6E]">Importance: {(mem.importance * 100).toFixed(0)}%</span>
                  </div>
                  <p className="text-xs text-[#F2F1EE] font-sans leading-relaxed">{mem.content}</p>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {activeTab === 'telemetry' && (
        <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Recent Token Consumption & Latency (ms)</span>}>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={telemetryGraphData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="#222" strokeDasharray="2 2" vertical={false} />
                <XAxis dataKey="time" stroke="#6B6B6E" tick={{ fontSize: 10, fill: '#6B6B6E' }} />
                <YAxis stroke="#6B6B6E" tick={{ fontSize: 10, fill: '#6B6B6E' }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1C1C1F', borderColor: '#333', borderRadius: 6, fontSize: 11, color: '#F2F1EE' }}
                  labelStyle={{ color: '#FFB020', fontFamily: 'monospace' }}
                />
                <Line type="monotone" dataKey="latency" stroke="#FFB020" strokeWidth={2} dot={{ r: 3, fill: '#FFB020' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
    </div>
  );
}
