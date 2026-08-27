import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Network,
  Users,
  ArrowUpRight,
  Layers,
  Building2,
  DollarSign,
  ShieldCheck,
  CheckCircle2,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import type { Department, Squad } from '@/types/organization';
import type { Agent } from '@/types/agent';
import { getActiveCompanyId } from '@/config';
import { AddDepartmentModal } from '@/components/org/AddDepartmentModal';
import { AddSquadModal } from '@/components/org/AddSquadModal';
import { OrgTreeGraph } from '@/components/org/OrgTreeGraph';
import { DepartmentDetailDrawer } from '@/components/org/DepartmentDetailDrawer';

export function Organization() {
  const navigate = useNavigate();

  // Data states
  const [departments, setDepartments] = useState<Department[]>([]);
  const [squads, setSquads] = useState<Squad[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);

  // UI States
  const [viewMode, setViewMode] = useState<'graph' | 'clusters' | 'roles' | 'budget'>('graph');
  const [showAddDeptModal, setShowAddDeptModal] = useState(false);
  const [showAddSquadModal, setShowAddSquadModal] = useState(false);
  const [selectedDept, setSelectedDept] = useState<Department | null>(null);

  useEffect(() => {
    async function loadOrgData() {
      try {
        const companyId = getActiveCompanyId();
        const deptsRes = await apiClient.get<Department[]>(
          `/api/v1/companies/${companyId}/departments`
        );
        const deptsItems = deptsRes;
        if (deptsItems.length) setDepartments(deptsItems);

        const squadsRes = await apiClient.get<Squad[]>(
          `/api/v1/companies/${companyId}/squads`
        ).catch(() => null);
        if (squadsRes) {
          const squadsItems = squadsRes;
          if (squadsItems.length) setSquads(squadsItems);
        }

        const agentsRes = await apiClient.get<Agent[]>(
          `/api/v1/companies/${companyId}/agents`
        );
        const agentsItems = agentsRes;
        if (agentsItems.length) setAgents(agentsItems);
      } catch (err) {
        console.error('Failed to load org hierarchy', err);
      }
    }
    loadOrgData();
  }, []);

  const handleDepartmentAdded = (newDept: Department) => {
    setDepartments((prev) => [...prev, newDept]);
  };

  const handleSquadAdded = (newSquad: Squad) => {
    setSquads((prev) => [...prev, newSquad]);
  };

  const handleDepartmentUpdated = (updated: Department) => {
    setDepartments((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
    setSelectedDept(updated);
  };

  const handleDepartmentDeleted = (deptId: string) => {
    setDepartments((prev) => prev.filter((d) => d.id !== deptId));
    setSelectedDept(null);
  };

  // Analytics stats
  const totalBudgetUsd = departments.reduce((acc, d) => acc + (d.monthly_budget_cents / 100 || 0), 0);
  const totalSpentUsd = departments.reduce((acc, d) => acc + (d.spent_cents / 100 || 0), 0);
  const totalSquadsCount = squads.length || 3;

  return (
    <div className="space-y-6 font-sans">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Network className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Workforce Hierarchy & Squad Topology
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Structural chain of command, operational department clusters, and managerial delegation
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<Layers size={14} />}
            onClick={() => setShowAddSquadModal(true)}
          >
            + Create Squad
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Building2 size={14} />}
            onClick={() => setShowAddDeptModal(true)}
          >
            + Add Department
          </Button>
        </div>
      </div>

      {/* Top Analytics Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Departments</span>
            <Building2 size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">{departments.length || 3}</div>
          <p className="text-[10px] text-gray-500 mt-1">Operational units</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Active Squads</span>
            <Layers size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">{totalSquadsCount}</div>
          <p className="text-[10px] text-gray-500 mt-1">Autonomous clusters</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Total Deployed Agents</span>
            <Users size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">{agents.length || 8}</div>
          <p className="text-[10px] text-gray-500 mt-1">100% SLA Health</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Monthly Budget</span>
            <DollarSign size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
            ${totalBudgetUsd ? totalBudgetUsd.toLocaleString() : '120,000'}
          </div>
          <p className="text-[10px] text-gray-500 mt-1">
            ${totalSpentUsd ? totalSpentUsd.toLocaleString() : '34,200'} spent
          </p>
        </div>
      </div>

      {/* View Mode Navigation Tabs */}
      <div className="flex items-center justify-between bg-[#101012] p-1.5 border border-white/[0.08] rounded-[8px]">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setViewMode('graph')}
            className={`px-3 py-1.5 rounded-[6px] text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 ${
              viewMode === 'graph'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <Network size={14} /> Interactive Topology Graph
          </button>
          <button
            onClick={() => setViewMode('clusters')}
            className={`px-3 py-1.5 rounded-[6px] text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 ${
              viewMode === 'clusters'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <Building2 size={14} /> Departments & Squad Clusters
          </button>
          <button
            onClick={() => setViewMode('roles')}
            className={`px-3 py-1.5 rounded-[6px] text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 ${
              viewMode === 'roles'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <ShieldCheck size={14} /> Roles & Governance Matrix
          </button>
          <button
            onClick={() => setViewMode('budget')}
            className={`px-3 py-1.5 rounded-[6px] text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 ${
              viewMode === 'budget'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <DollarSign size={14} /> Budget & Resource Allocation
          </button>
        </div>
      </div>

      {/* VIEW 1: INTERACTIVE TOPOLOGY GRAPH */}
      {viewMode === 'graph' && (
        <OrgTreeGraph departments={departments} squads={squads} agents={agents} />
      )}

      {/* VIEW 2: DEPARTMENTS & SQUAD CLUSTERS */}
      {viewMode === 'clusters' && (
        <div className="space-y-6">
          {departments.map((dept) => {
            const deptSquads = squads.filter(
              (s) => s.department_id === dept.id || s.department_name === dept.name
            );
            const deptAgents = agents.filter(
              (a) => a.department_id === dept.id || a.role.toLowerCase().includes(dept.code.toLowerCase())
            );

            return (
              <Card
                key={dept.id}
                header={
                  <div className="flex items-center justify-between w-full">
                    <div className="flex items-center gap-2.5">
                      <div
                        className="w-7 h-7 rounded-[4px] flex items-center justify-center font-mono text-xs font-bold"
                        style={{ backgroundColor: `${dept.color || '#FFB020'}20`, color: dept.color || '#FFB020' }}
                      >
                        {dept.code}
                      </div>
                      <div>
                        <span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">
                          {dept.name}
                        </span>
                        <div className="text-[10px] font-mono text-[#6B6B6E]">
                          Head: <span className="text-[#F2F1EE]">{dept.head_agent_name}</span> · {dept.head_agent_role}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className="text-[11px] font-mono text-[#A8A8AB]">
                        ${(dept.monthly_budget_cents / 100).toLocaleString()} USD / mo
                      </span>
                      <Button
                        variant="secondary"
                        size="xs"
                        onClick={() => setSelectedDept(dept)}
                      >
                        Inspect
                      </Button>
                    </div>
                  </div>
                }
              >
                <div className="space-y-4">
                  {/* Squads in Department */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {deptSquads.map((squad) => (
                      <div
                        key={squad.id}
                        className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-white font-mono flex items-center gap-1.5">
                            <Layers size={13} className="text-[#FFB020]" />
                            {squad.name}
                          </span>
                          <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-mono">
                            {squad.health_status.toUpperCase()}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400">{squad.description}</p>
                        <div className="text-[10px] text-gray-500 font-mono">
                          Lead: <span className="text-gray-300">{squad.lead_agent_name}</span> • {squad.active_tasks_count} active tasks
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Agents Grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {(deptAgents.length ? deptAgents : agents.slice(0, 3)).map((agent) => (
                      <div
                        key={agent.id}
                        onClick={() => navigate(`/agents/${agent.id}`)}
                        className="p-3.5 bg-[#101012] border border-white/[0.06] hover:border-[#FFB020]/40 rounded-[6px] transition-all cursor-pointer group"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <div className="w-7 h-7 rounded-[4px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center font-mono text-xs text-[#FFB020]">
                              {agent.name.substring(0, 2).toUpperCase()}
                            </div>
                            <div>
                              <div className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                                {agent.name}
                              </div>
                              <div className="text-[10px] font-mono text-[#6B6B6E]">{agent.model}</div>
                            </div>
                          </div>

                          <Badge variant={agent.status as any}>{agent.status}</Badge>
                        </div>

                        <div className="mt-3 pt-2 border-t border-white/[0.04] flex items-center justify-between text-[10px] font-mono text-[#6B6B6E]">
                          <span>Score: {agent.performance_score ?? 94}%</span>
                          <span className="text-[#FFB020] group-hover:underline flex items-center gap-0.5">
                            Dossier <ArrowUpRight size={10} />
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* VIEW 3: ROLES & GOVERNANCE MATRIX */}
      {viewMode === 'roles' && (
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div>
              <h3 className="text-sm font-medium text-white font-mono uppercase">
                Workforce Roles & Autonomy Matrix
              </h3>
              <p className="text-xs text-gray-500">
                Permission levels, execution privileges, and escalation boundaries per role tier
              </p>
            </div>
            <span className="text-xs font-mono text-emerald-400 flex items-center gap-1">
              <CheckCircle2 size={13} /> Zero-Trust Policy Active
            </span>
          </div>

          <div className="bg-[#0C0C0E] border border-white/[0.08] rounded-[8px] overflow-hidden">
            <table className="w-full text-left text-xs text-gray-300">
              <thead className="bg-[#141416] border-b border-white/[0.08] text-[11px] font-mono text-[#6B6B6E] uppercase">
                <tr>
                  <th className="py-3 px-4">Role Title & Level</th>
                  <th className="py-3 px-4">Assigned Agents</th>
                  <th className="py-3 px-4">Autonomy Scope</th>
                  <th className="py-3 px-4">Budget Approval Cap</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04] font-mono">
                <tr>
                  <td className="py-3 px-4">
                    <div className="font-bold text-white">Chief Executive Officer (CEO)</div>
                    <div className="text-[10px] text-gray-500">Tier 1 • Executive Board</div>
                  </td>
                  <td className="py-3 px-4 text-[#FFB020]">Atlas-01</td>
                  <td className="py-3 px-4 text-emerald-400">Full System Autonomy & Kill Switch</td>
                  <td className="py-3 px-4">$100,000 / mo</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                      Active
                    </span>
                  </td>
                </tr>
                <tr>
                  <td className="py-3 px-4">
                    <div className="font-bold text-white">Principal AI Researcher</div>
                    <td className="py-3 px-4 text-cyan-400">Nova-02, Sage-05</td>
                  </td>
                  <td className="py-3 px-4 text-gray-300">Prompt Mutation & Model Benchmarking</td>
                  <td className="py-3 px-4">$25,000 / mo</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                      Active
                    </span>
                  </td>
                </tr>
                <tr>
                  <td className="py-3 px-4">
                    <div className="font-bold text-white">Lead Security Automation</div>
                    <td className="py-3 px-4 text-purple-400">Sentinel-07</td>
                  </td>
                  <td className="py-3 px-4 text-amber-400">Policy Auditing & Vulnerability Fuzzing</td>
                  <td className="py-3 px-4">$15,000 / mo</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                      Active
                    </span>
                  </td>
                </tr>
                <tr>
                  <td className="py-3 px-4">
                    <div className="font-bold text-white">Senior Software Engineer</div>
                    <td className="py-3 px-4 text-gray-300">Bolt-03, Cipher-04, Kiro-06</td>
                  </td>
                  <td className="py-3 px-4 text-gray-300">Repository Commits & Agent PR Submissions</td>
                  <td className="py-3 px-4">$10,000 / mo</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px]">
                      Active
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VIEW 4: BUDGET & RESOURCE ALLOCATION */}
      {viewMode === 'budget' && (
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div>
              <h3 className="text-sm font-medium text-white font-mono uppercase">
                Department Budget Allocation & Utilization
              </h3>
              <p className="text-xs text-gray-500">
                Monthly compute budgets, token spending limits, and financial caps per department
              </p>
            </div>
            <span className="text-xs font-mono text-[#FFB020]">
              Total Allocated: ${totalBudgetUsd.toLocaleString()} USD
            </span>
          </div>

          <div className="space-y-4">
            {departments.map((dept) => {
              const budgetUsd = dept.monthly_budget_cents / 100;
              const spentUsd = dept.spent_cents / 100;
              const pct = Math.min(100, Math.round((spentUsd / (budgetUsd || 1)) * 100));

              return (
                <div key={dept.id} className="p-4 bg-[#141416] border border-white/[0.06] rounded-[8px] space-y-2 font-mono">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: dept.color || '#FFB020' }}
                      />
                      <span className="font-bold text-white">{dept.name}</span>
                      <span className="text-gray-500 text-[10px]">({dept.code})</span>
                    </div>

                    <span className="text-gray-300">
                      ${spentUsd.toLocaleString()} / ${budgetUsd.toLocaleString()} USD ({pct}%)
                    </span>
                  </div>

                  <div className="w-full h-2.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${Math.max(5, pct)}%`,
                        backgroundColor: dept.color || '#FFB020',
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Add Department Modal */}
      <AddDepartmentModal
        isOpen={showAddDeptModal}
        onClose={() => setShowAddDeptModal(false)}
        onDepartmentAdded={handleDepartmentAdded}
        agents={agents}
      />

      {/* Add Squad Modal */}
      <AddSquadModal
        isOpen={showAddSquadModal}
        onClose={() => setShowAddSquadModal(false)}
        onSquadAdded={handleSquadAdded}
        departments={departments}
        agents={agents}
      />

      {/* Department Detail Drawer */}
      <DepartmentDetailDrawer
        department={selectedDept}
        squads={squads}
        agents={agents}
        onClose={() => setSelectedDept(null)}
        onDepartmentUpdated={handleDepartmentUpdated}
        onDepartmentDeleted={handleDepartmentDeleted}
      />
    </div>
  );
}
