/**
 * ArchetypeGrid — Displays a grid of selectable agent archetype cards.
 * Used in the "Hire from Template" flow.
 */

import { useState } from 'react';
import type { AgentArchetype } from '@/api/agents';
import {
  Code2,
  Server,
  Palette,
  Brain,
  ClipboardList,
  Database,
  Gauge,
  Lock,
  Microscope,
  Monitor,
  Smartphone,
  Users,
  Wrench,
  Zap,
  Accessibility,
  GitBranch,
  PenTool,
  Search,
} from 'lucide-react';

interface ArchetypeGridProps {
  archetypes: AgentArchetype[];
  onSelect: (archetype: AgentArchetype) => void;
}

const ROLE_ICON_MAP: Record<string, React.ReactNode> = {
  'software-architect': <GitBranch size={16} className="text-indigo-400" />,
  'backend-engineer': <Server size={16} className="text-blue-400" />,
  'frontend-engineer': <Monitor size={16} className="text-cyan-400" />,
  'qa-engineer': <ClipboardList size={16} className="text-amber-400" />,
  'devops-engineer': <Wrench size={16} className="text-orange-400" />,
  'security-engineer': <Lock size={16} className="text-red-400" />,
  'data-engineer': <Database size={16} className="text-emerald-400" />,
  'ml-engineer': <Brain size={16} className="text-purple-400" />,
  'product-manager': <Users size={16} className="text-pink-400" />,
  'tech-writer': <PenTool size={16} className="text-teal-400" />,
  'designer': <Palette size={16} className="text-fuchsia-400" />,
  'researcher': <Microscope size={16} className="text-sky-400" />,
  'project-manager': <ClipboardList size={16} className="text-lime-400" />,
  'scrum-master': <Zap size={16} className="text-yellow-400" />,
  'site-reliability-engineer': <Gauge size={16} className="text-rose-400" />,
  'database-admin': <Database size={16} className="text-green-400" />,
  'mobile-developer': <Smartphone size={16} className="text-violet-400" />,
  'performance-engineer': <Gauge size={16} className="text-orange-300" />,
  'accessibility-specialist': <Accessibility size={16} className="text-blue-300" />,
  'team-lead': <Users size={16} className="text-amber-300" />,
};

const STYLE_COLORS: Record<string, string> = {
  analytical: 'border-blue-500/20 bg-blue-500/5',
  methodical: 'border-emerald-500/20 bg-emerald-500/5',
  creative: 'border-fuchsia-500/20 bg-fuchsia-500/5',
  directive: 'border-orange-500/20 bg-orange-500/5',
  collaborative: 'border-purple-500/20 bg-purple-500/5',
  supportive: 'border-teal-500/20 bg-teal-500/5',
};

export function ArchetypeGrid({ archetypes, onSelect }: ArchetypeGridProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const filtered = archetypes.filter((a) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      a.name.toLowerCase().includes(q) ||
      a.role.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q) ||
      a.capabilities.some((c) => c.toLowerCase().includes(q))
    );
  });

  return (
    <div className="space-y-3">
      {/* Search */}
      <div className="relative">
        <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search archetypes by name, role, or capability..."
          className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
        />
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 max-h-[420px] overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="col-span-full p-6 text-center">
            <Code2 className="w-8 h-8 mx-auto text-gray-500 mb-2" />
            <p className="text-xs font-mono text-gray-400">No archetypes match your search</p>
          </div>
        ) : (
          filtered.map((archetype) => {
            const styleColor = STYLE_COLORS[archetype.interaction_style] || 'border-white/[0.08] bg-white/[0.02]';
            return (
              <button
                key={archetype.role}
                onClick={() => onSelect(archetype)}
                className={`p-3 border rounded-[8px] text-left transition-all hover:border-[#FFB020]/50 hover:shadow-lg hover:shadow-[#FFB020]/5 group cursor-pointer ${styleColor}`}
              >
                <div className="flex items-start gap-2.5">
                  <div className="w-8 h-8 rounded-[5px] bg-[#101012] border border-white/[0.08] flex items-center justify-center shrink-0">
                    {ROLE_ICON_MAP[archetype.role] || <Code2 size={16} className="text-gray-400" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors truncate">
                      {archetype.name}
                    </div>
                    <p className="text-[10px] text-[#6B6B6E] mt-0.5 line-clamp-2 leading-relaxed">
                      {archetype.description}
                    </p>
                  </div>
                </div>

                {/* Capabilities preview */}
                <div className="flex flex-wrap gap-1 mt-2">
                  {archetype.capabilities.slice(0, 3).map((cap) => (
                    <span
                      key={cap}
                      className="px-1.5 py-0.5 text-[9px] font-mono text-[#A8A8AB] bg-[#101012] border border-white/[0.06] rounded"
                    >
                      {cap}
                    </span>
                  ))}
                  {archetype.capabilities.length > 3 && (
                    <span className="px-1.5 py-0.5 text-[9px] font-mono text-[#6B6B6E]">
                      +{archetype.capabilities.length - 3}
                    </span>
                  )}
                </div>

                {/* Style badge */}
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-[9px] font-mono text-[#6B6B6E] uppercase">
                    {archetype.interaction_style}
                  </span>
                  <span className="text-[9px] font-mono text-[#FFB020] opacity-0 group-hover:opacity-100 transition-opacity">
                    Select →
                  </span>
                </div>
              </button>
            );
          })
        )}
      </div>

      <p className="text-[10px] text-[#6B6B6E] font-mono text-center">
        {filtered.length} archetype{filtered.length !== 1 ? 's' : ''} available
        {searchQuery && ` (filtered from ${archetypes.length})`}
      </p>
    </div>
  );
}
