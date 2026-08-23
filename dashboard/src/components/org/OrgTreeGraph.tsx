import { useState } from 'react';
import { Network, Crown, Building2, Layers, Cpu, ChevronRight, ChevronDown, CheckCircle2, ArrowUpRight } from 'lucide-react';
import type { Department, Squad } from '@/types/organization';
import type { Agent } from '@/types/agent';
import { useNavigate } from 'react-router-dom';

interface OrgTreeGraphProps {
  departments: Department[];
  squads: Squad[];
  agents: Agent[];
}

export function OrgTreeGraph({ departments, squads, agents }: OrgTreeGraphProps) {
  const navigate = useNavigate();
  const [expandedDepts, setExpandedDepts] = useState<Record<string, boolean>>({
    'dept-exec': true,
    'dept-eng': true,
    'dept-ai': true,
  });

  const toggleDept = (deptId: string) => {
    setExpandedDepts((prev) => ({ ...prev, [deptId]: !prev[deptId] }));
  };

  return (
    <div className="p-5 bg-[#0C0C0E] border border-white/[0.08] rounded-[12px] space-y-6 font-sans">
      <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
        <div className="flex items-center gap-2">
          <Network className="w-5 h-5 text-[#FFB020]" />
          <div>
            <h3 className="text-sm font-medium text-white">Interactive Workforce Topology Graph</h3>
            <p className="text-[11px] text-[#6B6B6E] font-mono">
              Live organizational hierarchy from Executive Board to Squad Workers
            </p>
          </div>
        </div>
        <span className="px-2.5 py-1 rounded bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/30 font-mono text-[10px] font-bold">
          LIVE TOPOLOGY
        </span>
      </div>

      {/* EXECUTIVE LEVEL NODE */}
      <div className="space-y-4">
        <div className="p-4 bg-[#141417] border border-[#FFB020]/40 rounded-[10px] flex items-center justify-between shadow-lg">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-[#FFB020]/15 border border-[#FFB020]/40 rounded-[8px]">
              <Crown className="w-5 h-5 text-[#FFB020]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-white">Atlas-01</span>
                <span className="px-2 py-0.2 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[9px] font-mono">
                  CHIEF EXECUTIVE OFFICER
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5 font-mono">
                Executive Command & High-Level Policy Orchestration
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono">
            <div className="text-right">
              <span className="text-gray-500 block text-[10px]">DIRECT REPORT DEPTS</span>
              <span className="text-white font-bold">{departments.length} Departments</span>
            </div>
            <div className="text-right">
              <span className="text-gray-500 block text-[10px]">TOTAL WORKFORCE</span>
              <span className="text-[#FFB020] font-bold">{agents.length || 8} Active Agents</span>
            </div>
          </div>
        </div>

        {/* CONNECTOR LINE */}
        <div className="w-0.5 h-6 bg-[#FFB020]/30 mx-auto" />

        {/* DEPARTMENTS TREE BRANCHES */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {departments.map((dept) => {
            const isExpanded = expandedDepts[dept.id] ?? true;
            const deptSquads = squads.filter(
              (s) => s.department_id === dept.id || s.department_name === dept.name
            );
            const deptAgents = agents.filter(
              (a) => a.department_id === dept.id || a.role.toLowerCase().includes(dept.code.toLowerCase())
            );

            return (
              <div
                key={dept.id}
                className="bg-[#101013] border border-white/[0.08] rounded-[10px] overflow-hidden flex flex-col justify-between"
              >
                {/* Department Header Node */}
                <div
                  onClick={() => toggleDept(dept.id)}
                  className="p-3 bg-[#141416] border-b border-white/[0.06] flex items-center justify-between cursor-pointer hover:bg-white/[0.02] transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <div
                      className="w-7 h-7 rounded-[6px] flex items-center justify-center font-mono text-xs font-bold"
                      style={{ backgroundColor: `${dept.color || '#FFB020'}20`, color: dept.color || '#FFB020' }}
                    >
                      <Building2 size={15} />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-white flex items-center gap-1.5">
                        {dept.name}
                        <span className="text-[10px] font-mono text-gray-500">({dept.code})</span>
                      </div>
                      <div className="text-[10px] text-gray-400 font-mono">
                        Head: <span className="text-white">{dept.head_agent_name}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-gray-400">
                      ${(dept.monthly_budget_cents / 100).toLocaleString()}
                    </span>
                    {isExpanded ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />}
                  </div>
                </div>

                {/* Expanded Squad & Agent Nodes */}
                {isExpanded && (
                  <div className="p-3 space-y-3">
                    {/* Squad Clusters inside Dept */}
                    {deptSquads.length > 0 ? (
                      deptSquads.map((squad) => (
                        <div
                          key={squad.id}
                          className="p-2.5 bg-[#141417] border border-white/[0.06] rounded-[6px] space-y-2"
                        >
                          <div className="flex items-center justify-between text-[11px] font-mono">
                            <span className="text-white font-bold flex items-center gap-1.5">
                              <Layers size={12} className="text-[#FFB020]" />
                              {squad.name}
                            </span>
                            <span className="text-emerald-400 text-[10px] flex items-center gap-1">
                              <CheckCircle2 size={10} /> {squad.health_status}
                            </span>
                          </div>

                          <div className="text-[10px] text-gray-500 font-mono">
                            Lead: <span className="text-gray-300">{squad.lead_agent_name}</span> • {squad.active_tasks_count} active tasks
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-[11px] font-mono text-gray-500 italic p-2 text-center bg-[#141416] rounded">
                        General Department Unit
                      </div>
                    )}

                    {/* Member Agents Badges */}
                    <div className="pt-2 border-t border-white/[0.04] space-y-1.5">
                      <span className="text-[10px] font-mono uppercase text-[#6B6B6E] block">
                        Assigned Squad Agents ({deptAgents.length || 2})
                      </span>
                      <div className="grid grid-cols-2 gap-1.5">
                        {(deptAgents.length ? deptAgents : agents.slice(0, 2)).map((agent) => (
                          <div
                            key={agent.id}
                            onClick={() => navigate(`/agents/${agent.id}`)}
                            className="p-1.5 bg-[#0C0C0E] border border-white/[0.06] hover:border-[#FFB020]/40 rounded text-[11px] flex items-center justify-between cursor-pointer group transition-colors"
                          >
                            <div className="flex items-center gap-1.5 truncate">
                              <Cpu size={11} className="text-[#FFB020] shrink-0" />
                              <span className="text-gray-200 group-hover:text-[#FFB020] truncate">
                                {agent.name}
                              </span>
                            </div>
                            <ArrowUpRight size={10} className="text-gray-500 group-hover:text-[#FFB020] shrink-0" />
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
