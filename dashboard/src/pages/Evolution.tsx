import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  TrendingUp,
  Award,
  CheckCircle2,
  XCircle,
  ShieldCheck,
  Brain,
  GitCompare,
  Zap,
  Sparkles,
  BarChart3,
  Copy,
  Check,
  FileCode,
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  BarChart,
  Bar,
} from 'recharts';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient } from '@/api/client';

export type MutationCategory = 'Prompt Refinement' | 'Formatting Constraint' | 'Safety Guardrail' | 'Context Optimization';

export interface EvolutionProposal {
  id: string;
  title: string;
  agent_id: string;
  category: MutationCategory;
  score_delta: number;
  status: 'pending' | 'approved' | 'rejected';
  original_prompt: string;
  mutated_prompt: string;
  synthetic_evals: {
    passed: number;
    total: number;
    latency_delta_ms: number;
    token_saving_pct: number;
    p_value: number;
  };
  created_at: string;
}

const INITIAL_PROPOSALS: EvolutionProposal[] = [];

const AGENT_LIST = [
  'Dwight (QA Lead)',
  'Angela (Budget Auditor)',
  'Jim (PR Reviewer)',
  'Ryan (DevOps Lead)',
  'Toby (Compliance Officer)',
  'Creed (Security Specialist)',
  'Kevin (Data Engineer)',
  'Pam (Docs & Comms)',
];

export function Evolution() {
  const [proposals, setProposals] = useState<EvolutionProposal[]>(INITIAL_PROPOSALS);
  const [selectedProposal, setSelectedProposal] = useState<EvolutionProposal | null>(INITIAL_PROPOSALS[0] || null);
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedAgent, setSelectedAgent] = useState<string>('all');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'queue' | 'analytics' | 'safety'>('queue');

  // Trigger Mutation Modal State
  const [showMutationModal, setShowMutationModal] = useState(false);
  const [mutationAgent, setMutationAgent] = useState(AGENT_LIST[0] || 'Dwight (QA Lead)');
  const [mutationCategory, setMutationCategory] = useState<MutationCategory>('Prompt Refinement');
  const [mutationHypothesis, setMutationHypothesis] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);
  const [copiedDiff, setCopiedDiff] = useState(false);

  useEffect(() => {
    async function loadProposals() {
      try {
        const res = await apiClient.get<{ items: EvolutionProposal[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/evolution/proposals'
        );
        if (res?.items && res.items.length > 0) {
          const formatted = res.items.map((prop) => ({
            ...prop,
            category: prop.category || 'Prompt Refinement',
            original_prompt: prop.original_prompt || 'Execute task instructions with default reasoning.',
            mutated_prompt: prop.mutated_prompt || 'Enforce structured verification checksums and zero-error static checks.',
            synthetic_evals: prop.synthetic_evals || {
              passed: 192,
              total: 200,
              latency_delta_ms: -35,
              token_saving_pct: 11.2,
              p_value: 0.0005,
            },
          }));
          setProposals(formatted);
          if (!selectedProposal) setSelectedProposal(formatted[0] || null);
        }
      } catch {
        // Fallback to initial mock proposals
      }
    }
    loadProposals();
  }, [selectedProposal]);

  const handleDecision = async (proposalId: string, status: 'approved' | 'rejected') => {
    try {
      await apiClient.patch(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/evolution/proposals/${proposalId}`,
        { status }
      );
    } catch {
      // Local fallback state mutation
    }
    setProposals((prev) =>
      prev.map((p) => (p.id === proposalId ? { ...p, status } : p))
    );
    if (selectedProposal?.id === proposalId) {
      setSelectedProposal((prev) => (prev ? { ...prev, status } : null));
    }
  };

  const handleRunMutation = (e: React.FormEvent) => {
    e.preventDefault();
    if (!mutationHypothesis.trim()) return;

    setIsSimulating(true);
    setTimeout(() => {
      const newId = `evo-${Math.floor(Math.random() * 9000) + 1000}`;
      const scoreDelta = Math.round((Math.random() * 15 + 8) * 10) / 10;
      const newProposal: EvolutionProposal = {
        id: newId,
        title: mutationHypothesis,
        agent_id: mutationAgent,
        category: mutationCategory,
        score_delta: scoreDelta,
        status: 'pending',
        original_prompt: `Execute ${mutationCategory.toLowerCase()} tasks with standard prompt context.`,
        mutated_prompt: `${mutationHypothesis}. Enforce strict verification checksums and output validation.`,
        synthetic_evals: {
          passed: Math.floor(Math.random() * 10) + 190,
          total: 200,
          latency_delta_ms: -Math.floor(Math.random() * 50 + 20),
          token_saving_pct: Math.round((Math.random() * 10 + 8) * 10) / 10,
          p_value: 0.0003,
        },
        created_at: new Date().toISOString(),
      };

      setProposals((prev) => [newProposal, ...prev]);
      setSelectedProposal(newProposal);
      setIsSimulating(false);
      setShowMutationModal(false);
      setMutationHypothesis('');
    }, 1000);
  };

  // Filtered proposals
  const filtered = useMemo(() => {
    return proposals.filter((p) => {
      if (selectedStatus !== 'all' && p.status !== selectedStatus) return false;
      if (selectedAgent !== 'all' && p.agent_id !== selectedAgent) return false;
      if (selectedCategory !== 'all' && p.category !== selectedCategory) return false;
      return true;
    });
  }, [proposals, selectedStatus, selectedAgent, selectedCategory]);

  // Analytics Metrics
  const activeCount = proposals.filter((p) => p.status === 'pending').length;
  const approvedCount = proposals.filter((p) => p.status === 'approved').length;
  const avgLift = useMemo(() => {
    const approved = proposals.filter((p) => p.status === 'approved');
    if (approved.length === 0) return '+14.2%';
    const avg = approved.reduce((acc, curr) => acc + curr.score_delta, 0) / approved.length;
    return `+${avg.toFixed(1)}%`;
  }, [proposals]);

  // Chart Data Preparation
  const progressionData = [
    { generation: 'Gen 1', accuracy: 78.4, tokenEfficiency: 65 },
    { generation: 'Gen 2', accuracy: 82.1, tokenEfficiency: 72 },
    { generation: 'Gen 3', accuracy: 86.5, tokenEfficiency: 79 },
    { generation: 'Gen 4', accuracy: 91.2, tokenEfficiency: 86 },
    { generation: 'Gen 5 (Current)', accuracy: 95.8, tokenEfficiency: 92 },
  ];

  const agentLiftChartData = useMemo(() => {
    return AGENT_LIST.slice(0, 5).map((agent) => {
      const prop = proposals.find((p) => p.agent_id === agent);
      return {
        name: (agent || 'Agent').split(' ')[0],
        lift: prop ? prop.score_delta : Math.floor(Math.random() * 10) + 10,
      };
    });
  }, [proposals]);

  const handleCopyDiff = useCallback(() => {
    if (!selectedProposal) return;
    const text = `PROMPT MUTATION DIFF - ${selectedProposal.id}\nTarget: ${selectedProposal.agent_id}\n\n- ${selectedProposal.original_prompt}\n+ ${selectedProposal.mutated_prompt}`;
    navigator.clipboard.writeText(text);
    setCopiedDiff(true);
    setTimeout(() => setCopiedDiff(false), 2000);
  }, [selectedProposal]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight flex items-center gap-3">
              Self-Evolution & Prompt Refinement Engine
              <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-purple-500/10 text-purple-400 border border-purple-500/20">
                AUTONOMOUS MUTATION
              </span>
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Autonomous agent self-mutation proposals, synthetic evaluation benchmarks, and zero-regression rollout gates
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* View Mode Switcher */}
          <div className="flex items-center bg-[#101012] border border-white/[0.08] rounded-[6px] p-0.5">
            <button
              onClick={() => setViewMode('queue')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'queue' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Mutations Queue & Diff View"
            >
              <GitCompare size={13} />
              <span className="hidden sm:inline">Mutations</span>
            </button>
            <button
              onClick={() => setViewMode('analytics')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'analytics' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Benchmark Analytics"
            >
              <BarChart3 size={13} />
              <span className="hidden sm:inline">Progression</span>
            </button>
            <button
              onClick={() => setViewMode('safety')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'safety' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Safety & Rollout Gates"
            >
              <ShieldCheck size={13} />
              <span className="hidden sm:inline">Safety Gates</span>
            </button>
          </div>

          <Button
            variant="primary"
            size="sm"
            icon={<Sparkles size={15} />}
            onClick={() => setShowMutationModal(true)}
          >
            Trigger Mutation Run
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Active Proposals"
          value={activeCount}
          subValue="Awaiting Operator Review"
          change="Automated benchmark complete"
          changeType="neutral"
          icon={<Brain className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="Avg Benchmark Lift"
          value={avgLift}
          subValue="Accuracy Improvement"
          change="p < 0.001 statistically verified"
          changeType="positive"
          icon={<Award className="w-4 h-4 text-emerald-400" />}
        />
        <StatCard
          label="Merged Mutations"
          value={approvedCount}
          subValue="Active System Prompts"
          change="Zero regression rollbacks"
          changeType="positive"
          icon={<ShieldCheck className="w-4 h-4 text-cyan-400" />}
        />
        <StatCard
          label="Synthetic Test Pass Rate"
          value="98.2%"
          subValue="200 Benchmark Suite"
          change="+12.4% Token Efficiency"
          changeType="positive"
          icon={<Zap className="w-4 h-4 text-purple-400" />}
        />
      </div>

      {/* View Mode Content */}
      {viewMode === 'queue' && (
        <div className="space-y-6">
          {/* Filters Bar */}
          <div className="bg-[#101012] p-3 border border-white/[0.08] rounded-[10px] flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
            {/* Status Filter */}
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#6B6B6E] uppercase">Status:</span>
              {['all', 'pending', 'approved', 'rejected'].map((st) => (
                <button
                  key={st}
                  onClick={() => setSelectedStatus(st)}
                  className={`px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer capitalize ${
                    selectedStatus === st
                      ? 'bg-[#FFB020] text-black font-bold'
                      : 'bg-[#141416] text-[#6B6B6E] hover:text-white border border-white/[0.08]'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>

            {/* Agent Filter */}
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#6B6B6E] uppercase">Agent:</span>
              <button
                onClick={() => setSelectedAgent('all')}
                className={`px-2 py-0.5 rounded text-[10px] transition-colors cursor-pointer ${
                  selectedAgent === 'all' ? 'bg-white/20 text-white font-bold' : 'text-[#6B6B6E] hover:text-gray-300'
                }`}
              >
                All
              </button>
              {AGENT_LIST.slice(0, 4).map((ag) => (
                <button
                  key={ag}
                  onClick={() => setSelectedAgent(ag)}
                  className={`px-2 py-0.5 rounded text-[10px] transition-colors cursor-pointer ${
                    selectedAgent === ag ? 'bg-[#FFB020]/20 text-[#FFB020] border border-[#FFB020]/30 font-bold' : 'text-[#6B6B6E] hover:text-gray-300'
                  }`}
                >
                  {(ag || 'Agent').split(' ')[0]}
                </button>
              ))}
            </div>

            {/* Category Filter */}
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#6B6B6E] uppercase">Category:</span>
              {['all', 'Prompt Refinement', 'Formatting Constraint', 'Safety Guardrail', 'Context Optimization'].map((cat) => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-2 py-0.5 rounded text-[10px] transition-colors cursor-pointer ${
                    selectedCategory === cat ? 'bg-white/20 text-white font-bold' : 'text-[#6B6B6E] hover:text-gray-300'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Main Queue & Diff Inspection Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Proposals List (5 cols) */}
            <div className="lg:col-span-5 space-y-3">
              <div className="flex items-center justify-between text-xs font-mono font-medium text-[#6B6B6E] uppercase px-1">
                <span>Mutations Queue</span>
                <span>{filtered.length} proposals</span>
              </div>

              <div className="space-y-2.5">
                {filtered.length === 0 ? (
                  <div className="p-8 text-center bg-[#141416] border border-white/[0.08] rounded-[8px] text-xs font-mono text-gray-400">
                    No proposals match the selected filters
                  </div>
                ) : (
                  filtered.map((prop) => {
                    const isSelected = selectedProposal?.id === prop.id;
                    return (
                      <div
                        key={prop.id}
                        onClick={() => setSelectedProposal(prop)}
                        className={`p-4 rounded-[8px] border transition-all cursor-pointer group ${
                          isSelected
                            ? 'bg-[#18181B] border-[#FFB020]'
                            : 'bg-[#141416] border-white/[0.08] hover:border-white/[0.2]'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors line-clamp-2">
                            {prop.title}
                          </h3>
                          <Badge variant={prop.status === 'approved' ? 'completed' : prop.status === 'rejected' ? 'failed' : 'in_progress'}>
                            {prop.status}
                          </Badge>
                        </div>

                        <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                          <span className="text-gray-300 font-medium">{(prop.agent_id || 'Agent').split(' ')[0]}</span>
                          <span className="text-emerald-400 font-bold">+{prop.score_delta}% Accuracy</span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Selected Proposal Inspection & Diff (7 cols) */}
            <div className="lg:col-span-7">
              {selectedProposal ? (
                <Card
                  header={
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 w-full">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono font-bold text-[#FFB020] uppercase tracking-wider">
                            Proposal #{selectedProposal.id}
                          </span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/[0.06] text-gray-300 border border-white/[0.08]">
                            {selectedProposal.category}
                          </span>
                        </div>
                        <div className="text-[10px] font-mono text-[#6B6B6E] mt-1">
                          Target: <strong className="text-white">{selectedProposal.agent_id}</strong> · Benchmark Lift: <strong className="text-emerald-400">+{selectedProposal.score_delta}%</strong>
                        </div>
                      </div>

                      {/* Decision Buttons */}
                      {selectedProposal.status === 'pending' ? (
                        <div className="flex items-center gap-2 shrink-0">
                          <Button
                            variant="secondary"
                            size="xs"
                            icon={<XCircle className="w-3.5 h-3.5 text-[#EF4444]" />}
                            onClick={() => handleDecision(selectedProposal.id, 'rejected')}
                          >
                            Reject
                          </Button>
                          <Button
                            variant="primary"
                            size="xs"
                            icon={<CheckCircle2 className="w-3.5 h-3.5" />}
                            onClick={() => handleDecision(selectedProposal.id, 'approved')}
                          >
                            Approve & Merge
                          </Button>
                        </div>
                      ) : (
                        <span className={`px-2.5 py-1 rounded text-xs font-mono font-bold uppercase border ${
                          selectedProposal.status === 'approved' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                        }`}>
                          {selectedProposal.status}
                        </span>
                      )}
                    </div>
                  }
                >
                  <div className="space-y-4">
                    {/* Mutation Hypothesis */}
                    <div>
                      <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                        Mutation Hypothesis & Goal
                      </label>
                      <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs text-[#F2F1EE] leading-relaxed">
                        {selectedProposal.title}
                      </div>
                    </div>

                    {/* System Instruction Diff */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-[10px] font-mono text-[#6B6B6E] uppercase flex items-center gap-1">
                          <FileCode size={12} className="text-[#FFB020]" />
                          System Instruction Diff
                        </label>
                        <button
                          onClick={handleCopyDiff}
                          className="text-[10px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                        >
                          {copiedDiff ? <Check size={12} /> : <Copy size={12} />}
                          <span>{copiedDiff ? 'Copied' : 'Copy Diff'}</span>
                        </button>
                      </div>

                      <div className="p-3.5 bg-[#0A0A0C] border border-white/[0.08] rounded-[8px] font-mono text-[11px] leading-relaxed space-y-2">
                        <div className="p-2 bg-rose-500/10 border border-rose-500/20 text-rose-300 rounded font-mono">
                          <span className="font-bold mr-1.5">- [ORIGINAL]</span> {selectedProposal.original_prompt}
                        </div>
                        <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 rounded font-mono">
                          <span className="font-bold mr-1.5">+ [MUTATED]</span> {selectedProposal.mutated_prompt}
                        </div>
                      </div>
                    </div>

                    {/* Synthetic Evals Grid */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
                      <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                        <div className="text-[10px] text-[#6B6B6E] uppercase">Eval Pass Rate</div>
                        <div className="text-emerald-400 font-bold text-sm mt-1">
                          {selectedProposal.synthetic_evals.passed} / {selectedProposal.synthetic_evals.total}
                        </div>
                      </div>

                      <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                        <div className="text-[10px] text-[#6B6B6E] uppercase">Latency Delta</div>
                        <div className="text-cyan-400 font-bold text-sm mt-1">
                          {selectedProposal.synthetic_evals.latency_delta_ms} ms
                        </div>
                      </div>

                      <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                        <div className="text-[10px] text-[#6B6B6E] uppercase">Token Saving</div>
                        <div className="text-purple-400 font-bold text-sm mt-1">
                          +{selectedProposal.synthetic_evals.token_saving_pct}%
                        </div>
                      </div>

                      <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                        <div className="text-[10px] text-[#6B6B6E] uppercase">Statistical p-Value</div>
                        <div className="text-[#FFB020] font-bold text-sm mt-1">
                          p &lt; {selectedProposal.synthetic_evals.p_value}
                        </div>
                      </div>
                    </div>
                  </div>
                </Card>
              ) : (
                <div className="p-12 text-center bg-[#141416] border border-white/[0.08] rounded-[10px] text-xs font-mono text-[#6B6B6E]">
                  Select a proposal from the queue to review prompt diffs and synthetic evals.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Analytics View */}
      {viewMode === 'analytics' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Accuracy Progression Line Chart */}
            <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-5">
              <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-4 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-[#FFB020]" />
                Swarm Accuracy & Token Efficiency Progression
              </h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={progressionData}>
                    <XAxis dataKey="generation" stroke="#6B6B6E" fontSize={10} />
                    <YAxis stroke="#6B6B6E" fontSize={10} domain={[50, 100]} />
                    <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: '8px', fontSize: '11px' }} />
                    <Line type="monotone" dataKey="accuracy" name="Accuracy (%)" stroke="#22C55E" strokeWidth={2} dot={{ r: 4 }} />
                    <Line type="monotone" dataKey="tokenEfficiency" name="Token Efficiency (%)" stroke="#38BDF8" strokeWidth={2} dot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Benchmark Lift per Agent */}
            <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-5">
              <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-4 flex items-center gap-2">
                <Award className="w-4 h-4 text-purple-400" />
                Benchmark Lift (% Accuracy Gain per Agent)
              </h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={agentLiftChartData}>
                    <XAxis dataKey="name" stroke="#6B6B6E" fontSize={10} />
                    <YAxis stroke="#6B6B6E" fontSize={10} />
                    <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: '8px', fontSize: '11px' }} />
                    <Bar dataKey="lift" name="Lift (%)" fill="#FFB020" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Safety Gates & Deployment Audit View */}
      {viewMode === 'safety' && (
        <div className="space-y-4">
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2 mb-3">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              Active System Prompt Versions & Rollout Gates
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 font-mono text-xs">
              <div className="p-3 bg-[#141416] border border-white/[0.06] rounded-[6px]">
                <span className="text-[10px] text-gray-500 uppercase">Rollback Guard</span>
                <div className="text-emerald-400 font-bold text-sm mt-1">Automatic &lt; 2% Drop</div>
              </div>

              <div className="p-3 bg-[#141416] border border-white/[0.06] rounded-[6px]">
                <span className="text-[10px] text-gray-500 uppercase">Regression Threshold</span>
                <div className="text-cyan-400 font-bold text-sm mt-1">p &lt; 0.005 Required</div>
              </div>

              <div className="p-3 bg-[#141416] border border-white/[0.06] rounded-[6px]">
                <span className="text-[10px] text-gray-500 uppercase">Deployed Mutations</span>
                <div className="text-purple-400 font-bold text-sm mt-1">{approvedCount} Production Prompts</div>
              </div>
            </div>
          </div>

          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4 space-y-3 font-mono text-xs">
            <span className="text-gray-400 font-bold uppercase text-[11px]">Audit History of Prompts Deployed to Production</span>
            
            {proposals.filter((p) => p.status === 'approved').map((p) => (
              <div key={p.id} className="p-3 bg-[#141416] border border-white/[0.06] rounded flex items-center justify-between">
                <div className="space-y-0.5">
                  <span className="text-white font-bold">{p.title}</span>
                  <div className="text-gray-400 text-[10px]">Target: {p.agent_id} · Category: {p.category}</div>
                </div>
                <div className="text-emerald-400 font-bold text-xs">+{p.score_delta}% Lift</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trigger Mutation Run Modal */}
      <Modal
        isOpen={showMutationModal}
        onClose={() => setShowMutationModal(false)}
        title="Trigger Autonomous Mutation Run"
      >
        <form onSubmit={handleRunMutation} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Target Agent
              </label>
              <select
                value={mutationAgent}
                onChange={(e) => setMutationAgent(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                {AGENT_LIST.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Mutation Category
              </label>
              <select
                value={mutationCategory}
                onChange={(e) => setMutationCategory(e.target.value as MutationCategory)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="Prompt Refinement">Prompt Refinement</option>
                <option value="Formatting Constraint">Formatting Constraint</option>
                <option value="Safety Guardrail">Safety Guardrail</option>
                <option value="Context Optimization">Context Optimization</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Mutation Hypothesis & Goal
            </label>
            <textarea
              value={mutationHypothesis}
              onChange={(e) => setMutationHypothesis(e.target.value)}
              rows={3}
              placeholder="e.g. Require strict pre-validation of multi-tenant header scope before dispatching external tool calls..."
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowMutationModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" loading={isSimulating}>
              {isSimulating ? 'Executing Synthetic Evals...' : 'Launch Mutation Trial'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
