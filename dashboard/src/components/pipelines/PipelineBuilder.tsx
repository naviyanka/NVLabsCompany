/**
 * PipelineBuilder — Visual drag-and-drop pipeline stage editor.
 *
 * A canvas-based node editor that allows users to compose pipeline stages,
 * set agent assignments, configure prompts, and define sequential/parallel flow.
 * Uses native HTML drag-and-drop (no heavy library dependency).
 */

import { useState } from 'react';
import { Plus, Trash2, Play, ArrowRight, Zap, Save } from 'lucide-react';
import { Button } from '@/components/common/Button';

export interface PipelineStage {
  id: string;
  name: string;
  prompt: string;
  agent_id?: string;
  parallel?: boolean;
  sub_prompts?: string[];
  quality_gate?: boolean;
  quality_threshold?: number;
}

interface PipelineBuilderProps {
  initialStages?: PipelineStage[];
  agents?: Array<{ id: string; name: string }>;
  onSave?: (stages: PipelineStage[]) => void;
  onRun?: (stages: PipelineStage[]) => void;
}

export function PipelineBuilder({ initialStages, agents = [], onSave, onRun }: PipelineBuilderProps) {
  const [stages, setStages] = useState<PipelineStage[]>(
    initialStages || [{ id: `stage-${Date.now()}`, name: 'Stage 1', prompt: '', quality_gate: false }]
  );
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const addStage = () => {
    const newStage: PipelineStage = {
      id: `stage-${Date.now()}`,
      name: `Stage ${stages.length + 1}`,
      prompt: '',
      quality_gate: false,
    };
    setStages((prev) => [...prev, newStage]);
    setSelectedStage(newStage.id);
  };

  const removeStage = (id: string) => {
    setStages((prev) => prev.filter((s) => s.id !== id));
    if (selectedStage === id) setSelectedStage(null);
  };

  const updateStage = (id: string, updates: Partial<PipelineStage>) => {
    setStages((prev) => prev.map((s) => (s.id === id ? { ...s, ...updates } : s)));
  };

  const handleDragStart = (index: number) => {
    setDragIndex(index);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === index) return;
    const reordered = [...stages];
    const [moved] = reordered.splice(dragIndex, 1);
    if (moved) reordered.splice(index, 0, moved);
    setStages(reordered);
    setDragIndex(index);
  };

  const handleDragEnd = () => {
    setDragIndex(null);
  };

  const selected = stages.find((s) => s.id === selectedStage);

  return (
    <div className="flex flex-col lg:flex-row gap-4 h-full">
      {/* Stage Flow (Left Panel) */}
      <div className="flex-1 bg-[#101012] border border-white/[0.08] rounded-[10px] p-4 min-h-[400px]">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-mono font-medium text-[#F2F1EE] uppercase">Pipeline Flow</h3>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" icon={<Plus size={13} />} onClick={addStage}>
              Add Stage
            </Button>
            {onRun && (
              <Button variant="primary" size="sm" icon={<Play size={13} />} onClick={() => onRun(stages)}>
                Run
              </Button>
            )}
            {onSave && (
              <Button variant="secondary" size="sm" icon={<Save size={13} />} onClick={() => onSave(stages)}>
                Save
              </Button>
            )}
          </div>
        </div>

        {/* Stage nodes with flow arrows */}
        <div className="space-y-2">
          {stages.map((stage, index) => (
            <div key={stage.id}>
              <div
                draggable
                onDragStart={() => handleDragStart(index)}
                onDragOver={(e) => handleDragOver(e, index)}
                onDragEnd={handleDragEnd}
                onClick={() => setSelectedStage(stage.id)}
                className={`flex items-center gap-3 p-3 rounded-[8px] border cursor-pointer transition-all ${
                  selectedStage === stage.id
                    ? 'border-[#FFB020] bg-[#FFB020]/5'
                    : 'border-white/[0.08] bg-[#141416] hover:border-white/[0.15]'
                }`}
              >
                <div className="w-7 h-7 rounded-[4px] bg-white/[0.04] flex items-center justify-center text-[10px] font-mono text-[#FFB020] font-bold shrink-0">
                  {index + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-[#F2F1EE] truncate">{stage.name}</div>
                  <div className="text-[10px] text-[#6B6B6E] font-mono truncate">
                    {stage.parallel ? '⚡ Parallel' : '→ Sequential'}
                    {stage.quality_gate ? ' · 🛡️ Quality Gate' : ''}
                    {stage.agent_id ? ` · Agent: ${stage.agent_id.slice(0, 8)}` : ''}
                  </div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); removeStage(stage.id); }}
                  className="p-1 text-[#6B6B6E] hover:text-red-400 transition-colors shrink-0"
                >
                  <Trash2 size={12} />
                </button>
              </div>
              {index < stages.length - 1 && (
                <div className="flex justify-center py-1">
                  <ArrowRight size={14} className="text-[#6B6B6E] rotate-90" />
                </div>
              )}
            </div>
          ))}
        </div>

        {stages.length === 0 && (
          <div className="h-40 flex items-center justify-center text-xs font-mono text-[#6B6B6E]">
            No stages. Click "Add Stage" to start building your pipeline.
          </div>
        )}
      </div>

      {/* Stage Editor (Right Panel) */}
      <div className="w-full lg:w-80 bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
        {selected ? (
          <div className="space-y-4">
            <h3 className="text-xs font-mono font-medium text-[#F2F1EE] uppercase">Stage Config</h3>

            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Name</label>
              <input
                type="text"
                value={selected.name}
                onChange={(e) => updateStage(selected.id, { name: e.target.value })}
                className="w-full px-2.5 py-1.5 bg-[#141416] border border-white/[0.1] rounded-[4px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              />
            </div>

            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Prompt / Instruction</label>
              <textarea
                value={selected.prompt}
                onChange={(e) => updateStage(selected.id, { prompt: e.target.value })}
                rows={4}
                className="w-full px-2.5 py-1.5 bg-[#141416] border border-white/[0.1] rounded-[4px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] resize-y"
                placeholder="Enter the instruction for this stage..."
              />
            </div>

            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Assigned Agent</label>
              <select
                value={selected.agent_id || ''}
                onChange={(e) => updateStage(selected.id, { agent_id: e.target.value || undefined })}
                className="w-full px-2.5 py-1.5 bg-[#141416] border border-white/[0.1] rounded-[4px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="">Auto-assign (best available)</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="parallel"
                checked={selected.parallel || false}
                onChange={(e) => updateStage(selected.id, { parallel: e.target.checked })}
                className="rounded border-white/[0.2]"
              />
              <label htmlFor="parallel" className="text-[10px] font-mono text-[#A8A8AB]">
                <Zap size={10} className="inline mr-1" />
                Parallel execution (fan-out)
              </label>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="quality_gate"
                checked={selected.quality_gate || false}
                onChange={(e) => updateStage(selected.id, { quality_gate: e.target.checked })}
                className="rounded border-white/[0.2]"
              />
              <label htmlFor="quality_gate" className="text-[10px] font-mono text-[#A8A8AB]">
                Quality gate (CriticEvaluator)
              </label>
            </div>

            {selected.quality_gate && (
              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">Quality Threshold (0-1)</label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.1"
                  value={selected.quality_threshold ?? 0.7}
                  onChange={(e) => updateStage(selected.id, { quality_threshold: parseFloat(e.target.value) })}
                  className="w-full px-2.5 py-1.5 bg-[#141416] border border-white/[0.1] rounded-[4px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                />
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-xs font-mono text-[#6B6B6E]">
            Select a stage to edit its configuration.
          </div>
        )}
      </div>
    </div>
  );
}
