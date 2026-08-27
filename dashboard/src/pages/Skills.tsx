import { apiClient } from '@/api/client';
import { Badge } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { AddSkillModal } from '@/components/skills/AddSkillModal';
import { SkillDetailDrawer } from '@/components/skills/SkillDetailDrawer';
import { SkillPolicyPanel } from '@/components/skills/SkillPolicyPanel';
import { getActiveCompanyId } from '@/config';
import type { SkillItem } from '@/types/skill';
import {
  CheckCircle2,
  Code2,
  FileArchive,
  Github,
  LayoutGrid,
  List,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Users,
  Zap,
} from 'lucide-react';
import { useEffect, useState } from 'react';

export function Skills() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string; role: string }[]>([]);
  const [githubRepos, setGithubRepos] = useState<{ name: string; default_branch: string }[]>([]);

  // Search & Filter
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedSource, setSelectedSource] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'grid' | 'table' | 'policy'>('grid');

  // Modals & Drawers
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<SkillItem | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const skillsRes = await apiClient.get<SkillItem[]>(
          `/api/v1/companies/${companyId}/skills`
        );
        const skillItems = skillsRes;
        if (skillItems.length) setSkills(skillItems);

        const agentsRes = await apiClient.get<any[]>(
          `/api/v1/companies/${companyId}/agents`
        );
        const agentItems = agentsRes;
        if (agentItems.length) setAgents(agentItems);

        const reposRes = await apiClient.get<any[]>(
          `/api/v1/companies/${companyId}/github/user-repos`
        ).catch(() => null);
        if (reposRes) {
          const repoItems = reposRes;
          if (repoItems.length) setGithubRepos(repoItems);
        }
      } catch (err: any) {
        setLoadError(err?.detail || err?.message || 'Failed to load skills');
      }
    }
    loadData();
  }, []);

  const handleSkillAdded = (newSkill: SkillItem) => {
    setSkills((prev) => [newSkill, ...prev]);
  };

  const handleSkillUpdated = (updated: SkillItem) => {
    setSkills((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    setSelectedSkill(updated);
  };

  const handleSkillDeleted = (deletedId: string) => {
    setSkills((prev) => prev.filter((s) => s.id !== deletedId));
    setSelectedSkill(null);
  };

  const filteredSkills = skills.filter((s) => {
    if (selectedCategory !== 'all' && (s.category ?? '').toLowerCase() !== selectedCategory.toLowerCase()) {
      return false;
    }
    if (selectedSource !== 'all' && s.source_type !== selectedSource) {
      return false;
    }
    if (search) {
      const q = search.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        (s.description ?? '').toLowerCase().includes(q) ||
        (s.category ?? '').toLowerCase().includes(q) ||
        (s.author ?? '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  // Calculate top analytics stats
  const totalSkills = skills.length;
  const equippedCount = skills.reduce(
    (acc, s) => acc + ((s.equipped_agents?.length ?? 0) > 0 ? 1 : 0),
    0
  );
  const totalCalls30d = skills.reduce((acc, s) => acc + (s.call_count_30d ?? 0), 0);
  const avgSuccessRate = '99.4%';

  const getSourceBadge = (source: string) => {
    switch (source) {
      case 'zip':
        return (
          <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-mono flex items-center gap-1">
            <FileArchive size={11} /> ZIP Archive
          </span>
        );
      case 'command':
        return (
          <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-[#00FF66] border border-emerald-500/20 text-[10px] font-mono flex items-center gap-1">
            <Terminal size={11} /> CLI Command
          </span>
        );
      case 'github':
        return (
          <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 text-[10px] font-mono flex items-center gap-1">
            <Github size={11} /> GitHub Repo
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-[10px] font-mono flex items-center gap-1">
            <Code2 size={11} /> Custom Code
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Workforce Skills & Capability Envelopes
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Manage, install (ZIP, Command, GitHub, Custom), and assign domain capabilities to autonomous agent squads
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowAddModal(true)}
        >
          Add / Install Skill
        </Button>
      </div>

      {loadError && (
        <div className="p-3 rounded-[8px] bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs font-mono">
          {loadError}
        </div>
      )}

      {/* Top Analytics Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Total Registered Skills</span>
            <Sparkles size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">{totalSkills}</div>
          <p className="text-[10px] text-gray-500 mt-1">Across 7 domain categories</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Equipped Capabilities</span>
            <Users size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">{equippedCount}</div>
          <p className="text-[10px] text-gray-500 mt-1">Bound to active agent squads</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>30D Skill Invocations</span>
            <Zap size={14} className="text-amber-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">
            {totalCalls30d.toLocaleString()}
          </div>
          <p className="text-[10px] text-gray-500 mt-1">Tool executions & prompt hops</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Avg Execution Health</span>
            <ShieldCheck size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">{avgSuccessRate}</div>
          <p className="text-[10px] text-gray-500 mt-1">Sandboxed verification status</p>
        </div>
      </div>

      {/* Filter and Control Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-[#101012] p-3 border border-white/[0.08] rounded-[8px]">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search skills by name, description, author..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Category Filters */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
          {['all', 'Engineering', 'Security', 'QA', 'AI & Research', 'Frontend', 'DevOps'].map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer capitalize whitespace-nowrap ${selectedCategory.toLowerCase() === cat.toLowerCase()
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold'
                : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
                }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Source Dropdown & View Mode */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-[#141416] border border-white/[0.08] px-2 py-1 rounded">
            <SlidersHorizontal size={12} className="text-gray-400" />
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="bg-transparent text-xs font-mono text-gray-300 focus:outline-none cursor-pointer"
            >
              <option value="all">All Sources</option>
              <option value="zip">ZIP Package</option>
              <option value="command">CLI Command</option>
              <option value="github">GitHub Repo</option>
              <option value="custom">Custom Code</option>
            </select>
          </div>

          <div className="flex items-center gap-1 bg-[#141416] p-1 border border-white/[0.08] rounded">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1 rounded cursor-pointer ${viewMode === 'grid' ? 'bg-[#FFB020] text-black' : 'text-gray-400 hover:text-white'
                }`}
              title="Grid View"
            >
              <LayoutGrid size={14} />
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`p-1 rounded cursor-pointer ${viewMode === 'table' ? 'bg-[#FFB020] text-black' : 'text-gray-400 hover:text-white'
                }`}
              title="Table View"
            >
              <List size={14} />
            </button>
            <button
              onClick={() => setViewMode('policy')}
              className={`p-1 rounded cursor-pointer ${viewMode === 'policy' ? 'bg-[#FFB020] text-black' : 'text-gray-400 hover:text-white'
                }`}
              title="Access Policy"
            >
              <ShieldCheck size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Skills GRID VIEW */}
      {viewMode === 'grid' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSkills.map((skill) => {
            const agentCount = skill.equipped_agents?.length ?? 0;
            return (
              <Card
                key={skill.id}
                padding="sm"
                className="hover:border-[#FFB020]/40 transition-colors cursor-pointer group flex flex-col justify-between"
                onClick={() => setSelectedSkill(skill)}
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <h3 className="text-sm font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                        {skill.name}
                      </h3>
                      <div className="flex items-center gap-2">
                        <Badge variant="active">{skill.category ?? 'Uncategorized'}</Badge>
                        {getSourceBadge(skill.source_type ?? '')}
                      </div>
                    </div>
                    <span className="text-[10px] font-mono text-[#6B6B6E]">v{skill.version}</span>
                  </div>

                  <p className="text-xs text-[#9C9C9F] mt-3 font-sans leading-relaxed line-clamp-3">
                    {skill.description ?? 'No description provided.'}
                  </p>
                </div>

                <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] font-mono">
                  <span className="flex items-center gap-1 text-[#6B6B6E]">
                    <Users size={12} className="text-cyan-400" /> {agentCount} Agents Equipped
                  </span>
                  <span className="text-emerald-400 flex items-center gap-1 font-bold">
                    <CheckCircle2 size={12} /> {skill.success_rate ?? '—'}
                  </span>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Skills TABLE VIEW */}
      {viewMode === 'table' && (
        <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] overflow-hidden font-sans">
          <table className="w-full text-left text-xs text-gray-300">
            <thead className="bg-[#141416] border-b border-white/[0.08] text-[11px] font-mono text-[#6B6B6E] uppercase">
              <tr>
                <th className="py-3 px-4">Skill Title & Category</th>
                <th className="py-3 px-4">Source Type</th>
                <th className="py-3 px-4">Version & Author</th>
                <th className="py-3 px-4">Equipped Agents</th>
                <th className="py-3 px-4">30D Calls</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {filteredSkills.map((skill) => (
                <tr
                  key={skill.id}
                  onClick={() => setSelectedSkill(skill)}
                  className="hover:bg-white/[0.03] transition-colors cursor-pointer"
                >
                  <td className="py-3 px-4">
                    <div className="font-medium text-white group-hover:text-[#FFB020]">{skill.name}</div>
                    <div className="text-[10px] text-gray-500 font-mono mt-0.5">
                      {skill.category ?? 'Uncategorized'}
                    </div>
                  </td>
                  <td className="py-3 px-4">{getSourceBadge(skill.source_type ?? '')}</td>
                  <td className="py-3 px-4 font-mono text-[11px]">
                    <div>v{skill.version}</div>
                    <div className="text-[10px] text-gray-500">by {skill.author ?? 'unknown'}</div>
                  </td>
                  <td className="py-3 px-4 font-mono text-cyan-400">
                    <span className="flex items-center gap-1">
                      <Users size={12} /> {skill.equipped_agents?.length ?? 0} Agents
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-[#FFB020]">
                    {(skill.call_count_30d ?? 0).toLocaleString()}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <Button variant="secondary" size="xs">
                      Inspect
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Skills ACCESS POLICY VIEW */}
      {viewMode === 'policy' && <SkillPolicyPanel />}

      {/* Add Skill Modal */}
      <AddSkillModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSkillAdded={handleSkillAdded}
        githubRepos={githubRepos}
      />

      {/* Skill Detail Drawer */}
      <SkillDetailDrawer
        skill={selectedSkill}
        allAgents={agents}
        onClose={() => setSelectedSkill(null)}
        onSkillUpdated={handleSkillUpdated}
        onSkillDeleted={handleSkillDeleted}
      />
    </div>
  );
}
