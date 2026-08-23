import { useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  X,
  Zap,
  Activity,
  AlertTriangle,
  GitFork,
  CheckCircle2,
} from 'lucide-react';
import { MemoryEdgeType } from '@/types/memoryGraph';
import { EDGE_TYPE_COLORS } from '@/lib/memoryGraphAdapter';

interface RelationshipLegendProps {
  isOpen?: boolean;
  onToggle?: () => void;
  selectedEdgeTypeFilter?: MemoryEdgeType | null;
  onSelectEdgeType?: (type: MemoryEdgeType | null) => void;
  className?: string;
}

interface EdgeDefinition {
  type: MemoryEdgeType;
  name: string;
  category: 'structural' | 'temporal' | 'semantic' | 'conflict';
  style: 'solid' | 'dashed';
  color: string;
  description: string;
  directionExample: string;
}

const EDGE_DEFINITIONS: EdgeDefinition[] = [
  {
    type: 'supports',
    name: 'Supports / Evidences',
    category: 'semantic',
    style: 'solid',
    color: EDGE_TYPE_COLORS.supports.stroke,
    description: 'Corroborating evidence, empirical test result, or validation for a belief/task.',
    directionExample: 'Test Result → Feature Task',
  },
  {
    type: 'produced_by',
    name: 'Produced By',
    category: 'structural',
    style: 'solid',
    color: EDGE_TYPE_COLORS.produced_by.stroke,
    description: 'Direct authoring, agent execution outcome, or generative synthesis artifact.',
    directionExample: 'Decision → Author Agent',
  },
  {
    type: 'derived_from',
    name: 'Derived From',
    category: 'semantic',
    style: 'solid',
    color: EDGE_TYPE_COLORS.derived_from.stroke,
    description: 'Higher-order inference or distilled conclusion derived from source nodes.',
    directionExample: 'Knowledge Base ← Observation',
  },
  {
    type: 'informs',
    name: 'Informs / Guides',
    category: 'semantic',
    style: 'solid',
    color: EDGE_TYPE_COLORS.informs.stroke,
    description: 'Provides operational context, heuristic constraints, or policy guidance.',
    directionExample: 'Guideline → Architecture Plan',
  },
  {
    type: 'part_of',
    name: 'Part Of',
    category: 'structural',
    style: 'solid',
    color: EDGE_TYPE_COLORS.part_of.stroke,
    description: 'Hierarchical containment or sub-component membership in a cluster.',
    directionExample: 'Microservice → System Domain',
  },
  {
    type: 'depends_on',
    name: 'Depends On',
    category: 'structural',
    style: 'dashed',
    color: EDGE_TYPE_COLORS.depends_on.stroke,
    description: 'Upstream blocking prerequisite or functional reliance between goals/tasks.',
    directionExample: 'Deploy Task ⤏ Build Artifact',
  },
  {
    type: 'temporal_precedes',
    name: 'Temporal Precedes',
    category: 'temporal',
    style: 'dashed',
    color: EDGE_TYPE_COLORS.temporal_precedes.stroke,
    description: 'Time-series ordering where one event or thought preceded the subsequent action.',
    directionExample: 'Event T0 ⤏ Event T1',
  },
  {
    type: 'contradicts',
    name: 'Contradicts / Conflicts',
    category: 'conflict',
    style: 'dashed',
    color: EDGE_TYPE_COLORS.contradicts.stroke,
    description: 'Direct ontological contradiction, divergent agent belief, or obsolete state.',
    directionExample: 'Claim A ⤏ Claim B (Conflict)',
  },
];

export function RelationshipLegend({
  isOpen: externalIsOpen,
  onToggle: externalOnToggle,
  selectedEdgeTypeFilter,
  onSelectEdgeType,
  className = '',
}: RelationshipLegendProps) {
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'types' | 'syntax'>('types');

  const isOpen = externalIsOpen !== undefined ? externalIsOpen : internalIsOpen;
  const handleToggle = () => {
    if (externalOnToggle) {
      externalOnToggle();
    } else {
      setInternalIsOpen((prev) => !prev);
    }
  };

  return (
    <div
      id="memory-relationship-legend"
      className={`transition-all duration-200 pointer-events-auto ${className}`}
    >
      {/* Collapsed Pill Button */}
      {!isOpen ? (
        <button
          onClick={handleToggle}
          className="flex items-center gap-2 px-3 py-1.5 bg-[#101012]/90 hover:bg-[#101012] backdrop-blur-md border border-white/[0.12] hover:border-[#FFB020]/40 rounded-[8px] text-xs font-mono text-[#F2F1EE] shadow-xl transition-all cursor-pointer group"
          title="Open Edge Visual Language & Relationship Legend"
        >
          <div className="flex items-center -space-x-1">
            <span className="w-2 h-2 rounded-full bg-[#34D399]" />
            <span className="w-2 h-2 rounded-full bg-[#38BDF8]" />
            <span className="w-2 h-2 rounded-full bg-[#EF4444]" />
          </div>
          <span className="font-medium text-[11px] text-[#A8A8AB] group-hover:text-[#F2F1EE]">
            Edge Legend
          </span>
          <ChevronUp className="w-3.5 h-3.5 text-[#6B6B6E] group-hover:text-[#FFB020]" />
        </button>
      ) : (
        /* Expanded Legend Panel */
        <div className="w-80 sm:w-96 max-h-[75vh] flex flex-col bg-[#101012]/95 backdrop-blur-xl border border-white/[0.14] rounded-[10px] shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2.5 bg-[#141416]/80 border-b border-white/[0.08]">
            <div className="flex items-center gap-2">
              <GitFork className="w-4 h-4 text-[#FFB020]" />
              <div>
                <h2 className="text-xs font-mono font-semibold text-[#F2F1EE]">
                  Relationship Visual Syntax
                </h2>
                <p className="text-[10px] font-mono text-[#6B6B6E]">
                  Edge topology & semantic encoding rules
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={handleToggle}
                className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded transition-colors cursor-pointer"
                title="Collapse Legend"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Sub-Tab Navigation */}
          <div className="flex items-center border-b border-white/[0.06] bg-[#0E0E10] px-2 py-1">
            <button
              onClick={() => setActiveTab('types')}
              className={`flex-1 py-1 text-center text-[11px] font-mono rounded transition-colors cursor-pointer ${
                activeTab === 'types'
                  ? 'bg-white/[0.08] text-[#FFB020] font-semibold'
                  : 'text-[#6B6B6E] hover:text-[#F2F1EE]'
              }`}
            >
              Edge Types (8)
            </button>
            <button
              onClick={() => setActiveTab('syntax')}
              className={`flex-1 py-1 text-center text-[11px] font-mono rounded transition-colors cursor-pointer ${
                activeTab === 'syntax'
                  ? 'bg-white/[0.08] text-[#FFB020] font-semibold'
                  : 'text-[#6B6B6E] hover:text-[#F2F1EE]'
              }`}
            >
              Visual Encoding Rules
            </button>
          </div>

          {/* Content Body */}
          <div className="p-3 overflow-y-auto max-h-[calc(75vh-5rem)] space-y-2.5 text-xs font-mono">
            {activeTab === 'types' ? (
              <>
                <div className="flex items-center justify-between text-[10px] text-[#6B6B6E] px-1 pb-1">
                  <span>SEMANTIC RELATION</span>
                  <span>STROKE PATTERN</span>
                </div>

                <div className="space-y-1.5">
                  {EDGE_DEFINITIONS.map((edge) => {
                    const isSelected = selectedEdgeTypeFilter === edge.type;
                    return (
                      <div
                        key={edge.type}
                        onClick={() => onSelectEdgeType && onSelectEdgeType(isSelected ? null : edge.type)}
                        className={`p-2 rounded-[6px] border transition-all ${
                          isSelected
                            ? 'bg-[#FFB020]/15 border-[#FFB020]/40 shadow-sm'
                            : 'bg-[#141416]/90 border-white/[0.06] hover:border-white/[0.15] hover:bg-[#18181B]'
                        } ${onSelectEdgeType ? 'cursor-pointer' : ''}`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <div className="flex items-center gap-1.5">
                            <span
                              className="w-2 h-2 rounded-full shrink-0"
                              style={{ backgroundColor: edge.color }}
                            />
                            <span className="font-semibold text-[#F2F1EE] text-[11px]">
                              {edge.name}
                            </span>
                          </div>

                          {/* Render actual vector line stroke */}
                          <div className="flex items-center gap-1.5 shrink-0">
                            <svg className="w-12 h-3" viewBox="0 0 48 12">
                              <line
                                x1="2"
                                y1="6"
                                x2="46"
                                y2="6"
                                stroke={edge.color}
                                strokeWidth="2.5"
                                strokeDasharray={edge.style === 'dashed' ? '5,4' : 'none'}
                              />
                            </svg>
                            <span
                              className={`text-[9px] px-1 py-0.2 rounded font-mono ${
                                edge.style === 'solid'
                                  ? 'bg-white/[0.06] text-[#A8A8AB]'
                                  : 'bg-[#FFB020]/10 text-[#FFB020]'
                              }`}
                            >
                              {edge.style}
                            </span>
                          </div>
                        </div>

                        <p className="text-[10px] text-[#A8A8AB] leading-relaxed">
                          {edge.description}
                        </p>

                        <div className="mt-1 pt-1 border-t border-white/[0.04] flex items-center justify-between text-[9px] text-[#6B6B6E]">
                          <span>Example:</span>
                          <span className="text-[#38BDF8] font-mono truncate max-w-[200px]">
                            {edge.directionExample}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              /* Visual Encoding Explanations */
              <div className="space-y-3">
                {/* 1. Line Styles */}
                <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-[6px] space-y-2">
                  <div className="flex items-center gap-1.5 text-[#FFB020] font-semibold text-[11px]">
                    <Activity className="w-3.5 h-3.5" />
                    <span>Line Pattern Meaning</span>
                  </div>
                  <div className="space-y-1.5 text-[11px] text-[#A8A8AB]">
                    <div className="flex items-start gap-2">
                      <svg className="w-8 h-4 shrink-0 mt-0.5" viewBox="0 0 32 16">
                        <line x1="2" y1="8" x2="30" y2="8" stroke="#34D399" strokeWidth="2.5" />
                      </svg>
                      <div>
                        <strong className="text-[#F2F1EE]">Solid Lines:</strong> Structural lineage, generative provenance (`produced_by`), and factual corroboration (`supports`, `derived_from`).
                      </div>
                    </div>

                    <div className="flex items-start gap-2">
                      <svg className="w-8 h-4 shrink-0 mt-0.5" viewBox="0 0 32 16">
                        <line
                          x1="2"
                          y1="8"
                          x2="30"
                          y2="8"
                          stroke="#38BDF8"
                          strokeWidth="2.5"
                          strokeDasharray="4,3"
                        />
                      </svg>
                      <div>
                        <strong className="text-[#F2F1EE]">Dashed Lines:</strong> Prerequisites (`depends_on`), chronological sequences (`temporal_precedes`), and ontological disputes (`contradicts`).
                      </div>
                    </div>
                  </div>
                </div>

                {/* 2. Particle Pulses */}
                <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-[6px] space-y-1.5">
                  <div className="flex items-center gap-1.5 text-[#FFB020] font-semibold text-[11px]">
                    <Zap className="w-3.5 h-3.5 text-[#FFB020]" />
                    <span>Animated Particle Pulses</span>
                  </div>
                  <p className="text-[10px] text-[#A8A8AB] leading-relaxed">
                    Glowing beads traveling along links indicate active vector recall and real-time reasoning flow. Amber pulses represent standard associative flow, while red pulses signal anomaly friction along contradiction links.
                  </p>
                </div>

                {/* 3. Focus & Hover Dynamics */}
                <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-[6px] space-y-1.5">
                  <div className="flex items-center gap-1.5 text-[#38BDF8] font-semibold text-[11px]">
                    <CheckCircle2 className="w-3.5 h-3.5 text-[#38BDF8]" />
                    <span>Interaction & Highlighting</span>
                  </div>
                  <p className="text-[10px] text-[#A8A8AB] leading-relaxed">
                    Hovering or clicking any node brightens all directly incident edges to 2.5× stroke thickness and renders the contextual relationship label at the edge midpoint.
                  </p>
                </div>

                {/* 4. Conflict Resolution */}
                <div className="p-2.5 bg-red-500/10 border border-red-500/25 rounded-[6px] space-y-1.5">
                  <div className="flex items-center gap-1.5 text-red-400 font-semibold text-[11px]">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    <span>Contradiction Links (Red Dashed)</span>
                  </div>
                  <p className="text-[10px] text-red-300/80 leading-relaxed">
                    Highlight opposing factual claims or outdated knowledge across agents. Clicking the contradiction node opens automated Bayesian resolution options.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Footer with Collapse Action */}
          <div className="p-2 bg-[#0E0E10] border-t border-white/[0.06] flex items-center justify-between text-[10px] text-[#6B6B6E]">
            <span>Active Layout: Multi-Cluster</span>
            <button
              onClick={handleToggle}
              className="text-[#FFB020] hover:underline cursor-pointer flex items-center gap-1 font-mono"
            >
              <span>Collapse</span>
              <ChevronDown className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
