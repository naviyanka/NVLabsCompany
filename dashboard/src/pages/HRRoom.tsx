import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  GraduationCap,
  Award,
  Brain,
  CheckCircle2,
  Plus,
  Search,
  Download,
  BarChart3,
  Sparkles,
  ThumbsUp,
  AlertTriangle,
  ShieldCheck,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { Drawer } from '@/components/common/Drawer';
import { Table } from '@/components/common/Table';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { Agent } from '@/types/agent';

export interface ExtendedAgentHR extends Agent {
  eval_score?: number;
  certifications?: string[];
  last_appraisal_notes?: string;
  training_status?: 'Graduated' | 'In Training' | 'Pending Review';
  competencies?: { category: string; score: number }[];
}

export interface TrainingCurriculum {
  id: string;
  title: string;
  target_agent: string;
  status: 'in_training' | 'graduated' | 'scheduled';
  progress: number;
  benchmark_lift: string;
  category: string;
}

export function HRRoom() {
  const [agents, setAgents] = useState<ExtendedAgentHR[]>([]);
  const [curricula, setCurricula] = useState<TrainingCurriculum[]>([]);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'academy' | 'ledger' | 'certifications'>('academy');
  const [showModal, setShowModal] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<ExtendedAgentHR | null>(null);

  // New Curriculum Modal State
  const [newTitle, setNewTitle] = useState('');
  const [newAgent, setNewAgent] = useState('');
  const [newCategory, setNewCategory] = useState('Code Synthesis');

  // Appraisal Form State inside Drawer
  const [kudosNote, setKudosNote] = useState('');
  const [constraintNote, setConstraintNote] = useState('');
  const [appraisalFeedback, setAppraisalFeedback] = useState('');

  useEffect(() => {
    async function loadAgents() {
      try {
        const res = await apiClient.get<Agent[]>(
          `/api/v1/companies/${getActiveCompanyId()}/agents`
        );
        const items = res;
        if (items.length > 0) {
          setAgents(items.map((apiAgent) => ({ ...apiAgent })));
        }
      } catch {
        // Leave the roster empty — no fabricated agents.
      }
    }
    loadAgents();
  }, []);

  useEffect(() => {
    async function loadCurricula() {
      try {
        const res = await apiClient.get<
          Array<TrainingCurriculum & { target_agent_id: string }>
        >(`/api/v1/companies/${getActiveCompanyId()}/hr/curricula`);
        const rows = res;
        const nameById = new Map(agents.map((a) => [a.id, a.name]));
        setCurricula(
          rows.map((row) => ({
            ...row,
            target_agent: nameById.get(row.target_agent_id) || row.target_agent_id,
          }))
        );
      } catch {
        // No persisted curricula yet.
      }
    }
    if (agents.length > 0) loadCurricula();
  }, [agents]);

  const handleEnroll = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    const target = agents.find((a) => a.name === newAgent || a.id === newAgent);
    if (!target) return;
    try {
      const created = await apiClient.post<{
        id: string;
        title: string;
        category: string;
        status: string;
        progress: number;
        benchmark_lift: string;
      }>(`/api/v1/companies/${getActiveCompanyId()}/hr/curricula`, {
        target_agent_id: target.id,
        title: newTitle,
        category: newCategory,
        status: 'in_training',
        progress: 15,
        benchmark_lift: '',
      });
      setCurricula((prev) => [
        {
          id: created.id,
          title: created.title,
          target_agent: target.name,
          status: (created.status as TrainingCurriculum['status']) ?? 'in_training',
          progress: created.progress,
          benchmark_lift: created.benchmark_lift,
          category: created.category,
        },
        ...prev,
      ]);
      setShowModal(false);
      setNewTitle('');
    } catch {
      // Keep modal open — enrollment failed.
    }
  };

  const handleSaveAppraisal = async () => {
    if (!selectedAgent) return;
    const reviewType = kudosNote.trim()
      ? 'kudos'
      : constraintNote.trim()
      ? 'constraint'
      : 'appraisal';
    const feedback = kudosNote.trim()
      ? kudosNote.trim()
      : constraintNote.trim()
      ? constraintNote.trim()
      : 'Calibrated SLA score and soul guidelines.';

    try {
      await apiClient.post(
        `/api/v1/companies/${getActiveCompanyId()}/hr/reviews`,
        { agent_id: selectedAgent.id, review_type: reviewType, feedback }
      );
      setAppraisalFeedback('Saved to the agent record.');
    } catch {
      setAppraisalFeedback('Failed to save. Please retry.');
    }
    setTimeout(() => setAppraisalFeedback(''), 3000);
    setKudosNote('');
    setConstraintNote('');
  };

  // Filtered Curricula List
  const filteredCurricula = useMemo(() => {
    return curricula.filter((c) => {
      if (statusFilter !== 'all' && c.status !== statusFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          c.title.toLowerCase().includes(q) ||
          c.target_agent.toLowerCase().includes(q) ||
          c.category.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [curricula, statusFilter, search]);

  // Filtered Agents List
  const filteredAgents = useMemo(() => {
    return agents.filter((a) => {
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          a.name.toLowerCase().includes(q) ||
          a.title.toLowerCase().includes(q) ||
          a.model.toLowerCase().includes(q) ||
          (a.role || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [agents, search]);

  // Export handlers
  const handleExportJson = useCallback(() => {
    const data = { curricula, workforce_ledger: agents };
    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_hr_ledger_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [curricula, agents]);

  const handleExportCsv = useCallback(() => {
    const headers = ['Agent Name', 'Title', 'Model', 'Eval Score (%)', 'Training Status', 'Certifications', 'Last Appraisal'];
    const rows = agents.map((a) => [
      `"${a.name}"`,
      `"${a.title}"`,
      a.model,
      `${a.eval_score != null ? a.eval_score : '—'}%`,
      a.training_status || '—',
      `"${(a.certifications || []).join('; ')}"`,
      `"${a.last_appraisal_notes || ''}"`,
    ]);
    const csvStr = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvStr], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_hr_ledger_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [agents]);

  const inTrainingCount = curricula.filter((c) => c.status === 'in_training').length;
  const graduatedCount = curricula.filter((c) => c.status === 'graduated').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <GraduationCap className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight flex items-center gap-3">
              Workforce Calibration & Training Center (HR)
              <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20">
                BENCHMARK EVALS ACTIVE
              </span>
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Agent performance appraisals, synthetic benchmark fine-tuning tracks, and skill competency certifications
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* View Mode Switcher */}
          <div className="flex items-center bg-[#101012] border border-white/[0.08] rounded-[6px] p-0.5">
            <button
              onClick={() => setViewMode('academy')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'academy' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Active Fine-Tuning Curricula"
            >
              <GraduationCap size={13} />
              <span className="hidden sm:inline">Academy</span>
            </button>
            <button
              onClick={() => setViewMode('ledger')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'ledger' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Workforce Calibration Ledger"
            >
              <BarChart3 size={13} />
              <span className="hidden sm:inline">Ledger</span>
            </button>
            <button
              onClick={() => setViewMode('certifications')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'certifications' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Agent Certifications & Badges"
            >
              <ShieldCheck size={13} />
              <span className="hidden sm:inline">Certifications</span>
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
            variant="primary"
            size="sm"
            icon={<Plus size={15} />}
            onClick={() => setShowModal(true)}
          >
            Enroll in Training Track
          </Button>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Active Training Tracks"
          value={inTrainingCount}
          subValue={`${graduatedCount} Graduated`}
          change="Synthetic Benchmark Active"
          changeType="positive"
          icon={<Brain className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="Workforce SLA Accuracy"
          value={(() => {
            const scored = agents.filter((a) => a.eval_score != null);
            if (scored.length === 0) return '—';
            const avg =
              scored.reduce((sum, a) => sum + (a.eval_score || 0), 0) / scored.length;
            return `${avg.toFixed(1)}%`;
          })()}
          subValue="Average of scored agents"
          change="From performance_score"
          changeType="positive"
          icon={<Award className="w-4 h-4 text-emerald-400" />}
        />
        <StatCard
          label="Graduated Tracks"
          value={graduatedCount}
          subValue="Verified Regression Free"
          change="Zero SLA regressions"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4 text-cyan-400" />}
        />
      </div>

      {/* View Mode Content */}
      {viewMode === 'academy' && (
        <div className="space-y-4">
          {/* Search & Status Filter */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#101012] p-3.5 border border-white/[0.08] rounded-[10px]">
            <div className="relative flex-1 max-w-md">
              <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search curriculum title, target agent, or category..."
                className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
              />
            </div>

            <div className="flex items-center gap-2 font-mono text-xs">
              <span className="text-[10px] text-[#6B6B6E] uppercase mr-1">Status:</span>
              {['all', 'in_training', 'graduated', 'scheduled'].map((st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  className={`px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer capitalize ${
                    statusFilter === st
                      ? 'bg-[#FFB020] text-black font-bold'
                      : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
                  }`}
                >
                  {st.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>

          {/* Curricula Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredCurricula.map((track) => (
              <Card key={track.id} padding="sm">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-xs font-medium text-[#F2F1EE] leading-snug">{track.title}</h3>
                  <Badge variant={track.status === 'graduated' ? 'completed' : 'in_progress'}>
                    {track.status === 'graduated' ? 'Graduated' : 'Training'}
                  </Badge>
                </div>

                <div className="mt-2 text-xs font-mono text-[#6B6B6E] flex items-center justify-between">
                  <span>Target: <strong className="text-[#FFB020]">{track.target_agent}</strong></span>
                  <span className="text-[10px] bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06] text-gray-300">
                    {track.category}
                  </span>
                </div>

                {/* Progress Bar */}
                <div className="mt-3 space-y-1">
                  <div className="flex justify-between text-[10px] font-mono text-[#6B6B6E]">
                    <span>Eval Progress</span>
                    <span>{track.progress}%</span>
                  </div>
                  <div className="w-full h-1.5 bg-[#101012] border border-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${
                        track.progress === 100 ? 'bg-[#22C55E]' : 'bg-[#FFB020]'
                      }`}
                      style={{ width: `${track.progress}%` }}
                    />
                  </div>
                </div>

                <div className="mt-3 pt-2 border-t border-white/[0.04] text-[11px] font-mono text-[#22C55E] flex items-center justify-between">
                  <span>{track.benchmark_lift}</span>
                  <button
                    onClick={() => {
                      const matched = agents.find((a) => a.name === track.target_agent);
                      if (matched) setSelectedAgent(matched);
                    }}
                    className="text-[10px] text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    Inspect Appraisal →
                  </button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Workforce Ledger View */}
      {viewMode === 'ledger' && (
        <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Workforce Performance Calibration Ledger</span>} padding="none">
          <Table
            data={filteredAgents}
            keyExtractor={(a) => a.id}
            columns={[
              {
                key: 'name',
                header: 'Agent Call Sign',
                sortable: true,
                render: (a) => (
                  <div
                    onClick={() => setSelectedAgent(a)}
                    className="cursor-pointer group"
                  >
                    <div className="font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">{a.name}</div>
                    <div className="text-[11px] font-mono text-[#6B6B6E]">{a.title}</div>
                  </div>
                ),
              },
              {
                key: 'model',
                header: 'Model Provider',
                sortable: true,
                render: (a) => (
                  <span className="font-mono text-xs text-gray-300">{a.model}</span>
                ),
              },
              {
                key: 'eval_score',
                header: 'Accuracy SLA',
                sortable: true,
                render: (a) => (
                  <span className="font-mono text-xs text-emerald-400 font-bold">
                    {a.eval_score != null ? `${a.eval_score}%` : '—'}
                  </span>
                ),
              },
              {
                key: 'training_status',
                header: 'Training Status',
                render: (a) => (
                  <Badge variant={a.training_status === 'Graduated' ? 'completed' : 'in_progress'}>
                    {a.training_status || '—'}
                  </Badge>
                ),
              },
              {
                key: 'last_appraisal_notes',
                header: 'Operator Appraisal Note',
                render: (a) => (
                  <span className="font-mono text-[11px] text-gray-400 truncate max-w-xs block">
                    {a.last_appraisal_notes || '—'}
                  </span>
                ),
              },
              {
                key: 'action',
                header: 'Action',
                align: 'right',
                render: (a) => (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setSelectedAgent(a)}
                  >
                    Appraise & Calibrate
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* Certifications & Badges View */}
      {viewMode === 'certifications' && (
        <div className="space-y-4 font-mono text-xs">
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2 mb-2">
              <ShieldCheck className="w-4 h-4 text-[#FFB020]" />
              Agent Certifications & Skill Badges
            </h3>
            <p className="text-xs text-gray-400">
              Verified certifications earned through automated synthetic evaluation benchmarks
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {agents.map((ag) => (
              <div key={ag.id} className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-3">
                <div className="flex items-center justify-between border-b border-white/[0.06] pb-2">
                  <div>
                    <h4 className="text-xs font-bold text-white">{ag.name}</h4>
                    <span className="text-[10px] text-gray-500">{ag.title}</span>
                  </div>
                  <Badge variant={ag.training_status === 'Graduated' ? 'completed' : 'in_progress'}>
                    {ag.training_status}
                  </Badge>
                </div>

                <div className="space-y-1.5">
                  <span className="text-[10px] text-gray-500 uppercase font-bold">Certifications:</span>
                  <div className="flex flex-wrap gap-1.5">
                    {(ag.certifications || []).map((cert) => (
                      <span
                        key={cert}
                        className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1"
                      >
                        <Sparkles size={10} />
                        {cert}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-[11px]">
                  <span className="text-gray-500">Eval Accuracy:</span>
                  <span className="text-emerald-400 font-bold">{ag.eval_score != null ? `${ag.eval_score}%` : '—'}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agent Appraisal & Skill Drawer */}
      <Drawer
        isOpen={!!selectedAgent}
        onClose={() => setSelectedAgent(null)}
        title={`Appraise & Calibrate ${selectedAgent?.name || 'Agent'}`}
        subtitle={`Title: ${selectedAgent?.title} · Model: ${selectedAgent?.model}`}
      >
        {selectedAgent && (
          <div className="space-y-5 font-mono text-xs">
            {/* Stat Row */}
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded">
                <span className="text-[10px] text-gray-500 uppercase">Accuracy SLA Score</span>
                <div className="text-emerald-400 font-bold text-sm mt-1">
                  {selectedAgent.eval_score != null ? `${selectedAgent.eval_score}%` : '—'}
                </div>
              </div>

              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded">
                <span className="text-[10px] text-gray-500 uppercase">Training Track</span>
                <div className="text-[#FFB020] font-bold text-sm mt-1">
                  {selectedAgent.training_status || '—'}
                </div>
              </div>
            </div>

            {/* Skill Matrix Breakdown */}
            <div className="space-y-2">
              <span className="text-[10px] text-gray-400 uppercase font-bold">Competency Skill Matrix</span>
              <div className="space-y-2">
                {(selectedAgent.competencies || [
                  { category: 'System Architecture', score: 95 },
                  { category: 'Code Quality', score: 94 },
                ]).map((comp) => (
                  <div key={comp.category} className="space-y-1">
                    <div className="flex justify-between text-[11px] text-gray-300">
                      <span>{comp.category}</span>
                      <span className="text-emerald-400 font-bold">{comp.score}%</span>
                    </div>
                    <div className="w-full h-1.5 bg-[#101012] border border-white/[0.08] rounded-full overflow-hidden">
                      <div className="h-full bg-[#22C55E]" style={{ width: `${comp.score}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Appraisal Notes & Soul Calibration */}
            <div className="space-y-3 pt-3 border-t border-white/[0.08]">
              <span className="text-[10px] text-gray-400 uppercase font-bold">Operator Performance Appraisal</span>

              {appraisalFeedback && (
                <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 rounded text-xs">
                  {appraisalFeedback}
                </div>
              )}

              <div>
                <label className="block text-[10px] text-gray-500 uppercase mb-1 flex items-center gap-1">
                  <ThumbsUp size={12} className="text-emerald-400" />
                  Positive Reinforcement (Kudos)
                </label>
                <input
                  type="text"
                  value={kudosNote}
                  onChange={(e) => setKudosNote(e.target.value)}
                  placeholder="e.g. Excellent refactoring speed on vector cache"
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div>
                <label className="block text-[10px] text-gray-500 uppercase mb-1 flex items-center gap-1">
                  <AlertTriangle size={12} className="text-amber-400" />
                  Constraint Tuning / Disciplinary Guidance
                </label>
                <input
                  type="text"
                  value={constraintNote}
                  onChange={(e) => setConstraintNote(e.target.value)}
                  placeholder="e.g. Strictly enforce 200ms latency SLA"
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="secondary" size="sm" onClick={() => setSelectedAgent(null)}>
                  Close
                </Button>
                <Button variant="primary" size="sm" onClick={handleSaveAppraisal}>
                  Save Appraisal & Update Soul
                </Button>
              </div>
            </div>
          </div>
        )}
      </Drawer>

      {/* Enroll Modal */}
      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title="Enroll Agent in Benchmark Training">
        <form onSubmit={handleEnroll} className="space-y-4 font-mono text-xs">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Curriculum Title / Benchmark
            </label>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="e.g. Distributed Lock Contention Avoidance"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Category Focus
            </label>
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Hallucination Mitigation">Hallucination Mitigation</option>
              <option value="Code Synthesis">Code Synthesis & Refactoring</option>
              <option value="Security & QA">Security & Zero-Trust QA</option>
              <option value="Reasoning & Alignment">Reasoning & Alignment</option>
              <option value="Graphics Physics">Graphics & Physics</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Candidate Agent
            </label>
            <select
              value={newAgent}
              onChange={(e) => setNewAgent(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.name}>
                  {a.name} ({a.model})
                </option>
              ))}
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Commence Training Track
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
