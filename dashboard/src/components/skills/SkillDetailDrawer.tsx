import { useState } from 'react';
import {
  X,
  Sparkles,
  Users,
  ShieldCheck,
  Play,
  FileText,
  Settings,
  Trash2,
  Check,
  Copy,
  AlertCircle,
  Code2,
  Terminal,
  FileArchive,
  Github,
  Loader2,
} from 'lucide-react';
import type { SkillItem, SkillTestResult } from '@/types/skill';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';

interface SkillDetailDrawerProps {
  skill: SkillItem | null;
  allAgents: { id: string; name: string; role: string; avatar_url?: string }[];
  onClose: () => void;
  onSkillUpdated: (updated: SkillItem) => void;
  onSkillDeleted: (skillId: string) => void;
}

export function SkillDetailDrawer({
  skill,
  allAgents,
  onClose,
  onSkillUpdated,
  onSkillDeleted,
}: SkillDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'agents' | 'test' | 'settings'>('overview');
  const [isDeleting, setIsDeleting] = useState(false);
  const [copied, setCopied] = useState(false);

  // Test sandbox states
  const [testInput, setTestInput] = useState('{\n  "query": "Find dead code symbols in dashboard"\n}');
  const [isRunningTest, setIsRunningTest] = useState(false);
  const [testResult, setTestResult] = useState<SkillTestResult | null>(null);

  // Equipped agents state
  const [equippedAgents, setEquippedAgents] = useState<string[]>(skill?.equipped_agents || []);
  const [isSavingAgents, setIsSavingAgents] = useState(false);
  const [agentSaveMsg, setAgentSaveMsg] = useState<string | null>(null);

  if (!skill) return null;

  const handleCopyMarkdown = () => {
    if (skill.instructions_md) {
      navigator.clipboard.writeText(skill.instructions_md);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleToggleAgent = (agentName: string) => {
    setEquippedAgents((prev) =>
      prev.includes(agentName) ? prev.filter((a) => a !== agentName) : [...prev, agentName]
    );
  };

  const handleSaveAgents = async () => {
    setIsSavingAgents(true);
    setAgentSaveMsg(null);
    try {
      const updated = await apiClient.patch<SkillItem>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/skills/${skill.id}`,
        { equipped_agents: equippedAgents }
      );
      onSkillUpdated(updated);
      setAgentSaveMsg('Agent skill assignments saved successfully!');
    } catch (err: any) {
      setAgentSaveMsg(err?.detail || 'Failed to update agent assignments');
    } finally {
      setIsSavingAgents(false);
    }
  };

  const handleRunSandboxTest = async () => {
    setIsRunningTest(true);
    setTestResult(null);
    try {
      const res = await apiClient.post<SkillTestResult>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/skills/${skill.id}/test`,
        { test_input: testInput }
      );
      setTestResult(res);
    } catch (err: any) {
      setTestResult({
        success: false,
        output: '',
        execution_ms: 45,
        error: err?.detail || 'Sandbox execution error',
      });
    } finally {
      setIsRunningTest(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Are you sure you want to uninstall skill "${skill.name}"?`)) return;
    setIsDeleting(true);
    try {
      await apiClient.delete(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/skills/${skill.id}`
      );
      onSkillDeleted(skill.id);
      onClose();
    } finally {
      setIsDeleting(false);
    }
  };

  const getSourceIcon = (source: string) => {
    switch (source) {
      case 'zip':
        return <FileArchive size={14} className="text-amber-400" />;
      case 'command':
        return <Terminal size={14} className="text-[#00FF66]" />;
      case 'github':
        return <Github size={14} className="text-purple-400" />;
      default:
        return <Code2 size={14} className="text-cyan-400" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end">
      <div className="w-full max-w-2xl bg-[#0A0A0C] border-l border-white/[0.1] h-full flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-white/[0.08] flex items-center justify-between bg-[#101012]">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#FFB020]/10 border border-[#FFB020]/30 rounded-[8px]">
              <Sparkles className="w-5 h-5 text-[#FFB020]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-medium text-white">{skill.name}</h2>
                <Badge variant="active">{skill.category}</Badge>
              </div>
              <p className="text-xs text-[#6B6B6E] font-mono mt-0.5 flex items-center gap-2">
                <span className="flex items-center gap-1">
                  {getSourceIcon(skill.source_type)} {skill.source_type.toUpperCase()}
                </span>
                <span>• v{skill.version}</span>
                <span>• By {skill.author}</span>
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-1 px-4 border-b border-white/[0.08] bg-[#0E0E10]">
          <button
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-2.5 text-xs font-mono border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'overview'
                ? 'border-[#FFB020] text-[#FFB020] font-medium'
                : 'border-transparent text-[#6B6B6E] hover:text-white'
            }`}
          >
            <FileText size={13} /> Overview & Code
          </button>
          <button
            onClick={() => setActiveTab('agents')}
            className={`px-3 py-2.5 text-xs font-mono border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'agents'
                ? 'border-[#FFB020] text-[#FFB020] font-medium'
                : 'border-transparent text-[#6B6B6E] hover:text-white'
            }`}
          >
            <Users size={13} /> Equipped Agents ({equippedAgents.length})
          </button>
          <button
            onClick={() => setActiveTab('test')}
            className={`px-3 py-2.5 text-xs font-mono border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'test'
                ? 'border-[#FFB020] text-[#FFB020] font-medium'
                : 'border-transparent text-[#6B6B6E] hover:text-white'
            }`}
          >
            <Play size={13} /> Test Sandbox
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`px-3 py-2.5 text-xs font-mono border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'settings'
                ? 'border-[#FFB020] text-[#FFB020] font-medium'
                : 'border-transparent text-[#6B6B6E] hover:text-white'
            }`}
          >
            <Settings size={13} /> Settings & Logs
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* TAB 1: OVERVIEW & CODE */}
          {activeTab === 'overview' && (
            <div className="space-y-4 font-sans">
              {/* Description Card */}
              <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
                <div className="text-xs font-mono uppercase text-[#A8A8AB]">Description</div>
                <p className="text-xs text-gray-300 leading-relaxed">{skill.description}</p>
              </div>

              {/* Skill Metrics */}
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px]">
                  <div className="text-[10px] font-mono text-[#6B6B6E] uppercase">30D Invocations</div>
                  <div className="text-sm font-bold font-mono text-white mt-0.5">
                    {skill.call_count_30d.toLocaleString()}
                  </div>
                </div>
                <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px]">
                  <div className="text-[10px] font-mono text-[#6B6B6E] uppercase">Success Rate</div>
                  <div className="text-sm font-bold font-mono text-emerald-400 mt-0.5">
                    {skill.success_rate}
                  </div>
                </div>
                <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px]">
                  <div className="text-[10px] font-mono text-[#6B6B6E] uppercase">Avg Speed</div>
                  <div className="text-sm font-bold font-mono text-[#FFB020] mt-0.5">
                    {skill.avg_execution_ms} ms
                  </div>
                </div>
              </div>

              {/* Instructions / SKILL.md */}
              {skill.instructions_md && (
                <div className="p-3 bg-[#101012] border border-white/[0.08] rounded-[8px] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono uppercase text-[#A8A8AB]">
                      SKILL.md Instructions & Prompt Rules
                    </span>
                    <button
                      onClick={handleCopyMarkdown}
                      className="p-1 text-gray-400 hover:text-white flex items-center gap-1 text-[11px] font-mono"
                    >
                      {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                      {copied ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                  <pre className="p-3 bg-[#08080A] border border-white/[0.06] rounded text-[11px] font-mono text-gray-300 max-h-56 overflow-y-auto whitespace-pre-wrap">
                    {skill.instructions_md}
                  </pre>
                </div>
              )}

              {/* Parameters JSON Schema */}
              {skill.parameters_json && (
                <div className="p-3 bg-[#101012] border border-white/[0.08] rounded-[8px] space-y-2">
                  <span className="text-xs font-mono uppercase text-[#A8A8AB]">
                    Parameters Schema (JSON)
                  </span>
                  <pre className="p-3 bg-[#08080A] border border-white/[0.06] rounded text-[11px] font-mono text-emerald-400 max-h-40 overflow-y-auto whitespace-pre-wrap">
                    {skill.parameters_json}
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: EQUIPPED AGENTS */}
          {activeTab === 'agents' && (
            <div className="space-y-4 font-sans">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-bold text-white uppercase font-mono">
                    Equip / Un-equip Agents
                  </h3>
                  <p className="text-[11px] text-gray-500">
                    Selected agents will automatically gain access to execute this skill in their workflow
                  </p>
                </div>
                <Button
                  variant="primary"
                  size="xs"
                  onClick={handleSaveAgents}
                  disabled={isSavingAgents}
                >
                  {isSavingAgents ? 'Saving...' : 'Save Assignments'}
                </Button>
              </div>

              {agentSaveMsg && (
                <div className="p-2.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-mono">
                  {agentSaveMsg}
                </div>
              )}

              <div className="space-y-2 max-h-96 overflow-y-auto">
                {allAgents.map((agent) => {
                  const isEquipped = equippedAgents.includes(agent.name) || equippedAgents.includes(agent.id);
                  return (
                    <div
                      key={agent.id}
                      onClick={() => handleToggleAgent(agent.name)}
                      className={`p-3 rounded-[8px] border flex items-center justify-between cursor-pointer transition-colors ${
                        isEquipped
                          ? 'bg-[#FFB020]/10 border-[#FFB020]/40'
                          : 'bg-[#141416] border-white/[0.06] hover:border-white/[0.15]'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-7 h-7 rounded-full bg-[#1A1A1E] border border-white/[0.1] flex items-center justify-center font-mono text-xs font-bold text-white">
                          {agent.name.substring(0, 2)}
                        </div>
                        <div>
                          <div className="text-xs font-medium text-white">{agent.name}</div>
                          <div className="text-[10px] text-gray-500 font-mono">{agent.role}</div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {isEquipped && (
                          <span className="px-2 py-0.5 rounded bg-[#FFB020] text-[#0A0A0B] font-bold font-mono text-[10px]">
                            EQUIPPED
                          </span>
                        )}
                        <input
                          type="checkbox"
                          checked={isEquipped}
                          onChange={() => {}}
                          className="w-4 h-4 rounded border-gray-600 text-[#FFB020] focus:ring-0 cursor-pointer"
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* TAB 3: TEST SANDBOX */}
          {activeTab === 'test' && (
            <div className="space-y-4 font-sans">
              <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-bold text-white uppercase flex items-center gap-2">
                    <Play size={13} className="text-[#FFB020]" /> Sandbox Execution Payload
                  </span>
                  <Button
                    variant="primary"
                    size="xs"
                    onClick={handleRunSandboxTest}
                    disabled={isRunningTest}
                    icon={isRunningTest ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                  >
                    {isRunningTest ? 'Executing...' : 'Run Test'}
                  </Button>
                </div>

                <textarea
                  value={testInput}
                  onChange={(e) => setTestInput(e.target.value)}
                  rows={4}
                  className="w-full p-2.5 bg-[#08080A] border border-white/[0.12] rounded text-xs font-mono text-gray-200 focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              {testResult && (
                <div className="p-3 bg-[#101012] border border-white/[0.1] rounded-[8px] space-y-2 font-mono">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-bold text-white flex items-center gap-2">
                      {testResult.success ? (
                        <Check size={14} className="text-emerald-400" />
                      ) : (
                        <AlertCircle size={14} className="text-rose-400" />
                      )}
                      Test Output Result
                    </span>
                    <span className="text-gray-400 text-[10px]">
                      {testResult.execution_ms} ms • {testResult.tokens_used || 120} tokens
                    </span>
                  </div>

                  <pre className="p-3 bg-[#08080A] border border-white/[0.06] rounded text-[11px] text-emerald-400 whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {testResult.output || testResult.error}
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: SETTINGS & MANAGEMENT */}
          {activeTab === 'settings' && (
            <div className="space-y-4 font-sans">
              <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-3">
                <h4 className="text-xs font-bold font-mono text-white uppercase">Skill Details</h4>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-gray-500 block text-[10px] font-mono">SOURCE</span>
                    <span className="text-white font-mono">{skill.source_location || skill.source_type}</span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] font-mono">VERIFICATION</span>
                    <span className="text-emerald-400 font-mono flex items-center gap-1">
                      <ShieldCheck size={12} /> {skill.security_status.toUpperCase()}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] font-mono">CREATED AT</span>
                    <span className="text-gray-300 font-mono">{skill.created_at || 'Recently'}</span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] font-mono">VERSION</span>
                    <span className="text-gray-300 font-mono">v{skill.version}</span>
                  </div>
                </div>
              </div>

              {/* Danger Zone */}
              <div className="p-4 bg-rose-500/5 border border-rose-500/20 rounded-[8px] space-y-3">
                <h4 className="text-xs font-bold font-mono text-rose-400 uppercase flex items-center gap-2">
                  <Trash2 size={14} /> Uninstall Skill Package
                </h4>
                <p className="text-xs text-gray-400">
                  Permanently remove this skill from the company registry and unequip it from all assigned agents.
                </p>
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={handleDelete}
                  disabled={isDeleting}
                  icon={<Trash2 size={13} className="text-rose-400" />}
                >
                  {isDeleting ? 'Uninstalling...' : 'Uninstall Skill'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
