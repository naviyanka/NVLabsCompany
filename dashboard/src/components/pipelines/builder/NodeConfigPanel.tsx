/**
 * NodeConfigPanel — right-hand parameter editor for the selected builder node.
 *
 * Our simpler analogue of OpenCompany's ParameterRenderer: a switch over the
 * node input `type` (string | number | boolean | json | file | credential),
 * with a text fallback for unknown types. Edits the node label and writes
 * parameter values back into node.data.params.
 */

import type { ApiNodeInput } from '@/types/pipeline';
import { X } from 'lucide-react';
import type { BuilderNodeData } from './nodeTypes';

export interface SelectedNode {
  id: string;
  data: BuilderNodeData;
  /** Full input schema resolved from the backend registry, if known. */
  inputs?: ApiNodeInput[];
}

interface Props {
  node: SelectedNode | null;
  onClose: () => void;
  onLabelChange: (id: string, label: string) => void;
  onParamChange: (id: string, name: string, value: unknown) => void;
}

const LABEL_CLS = 'block text-[11px] font-mono text-gray-400 uppercase mb-1';
const INPUT_CLS =
  'w-full px-3 py-2 bg-[#0C0C0E] border border-white/[0.1] rounded text-white text-xs focus:outline-none focus:border-[#FFB020]';

function ParamField({
  input,
  value,
  onChange,
}: {
  input: ApiNodeInput;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = (
    <label className={LABEL_CLS}>
      {input.name}
      {input.required && <span className="text-rose-400"> *</span>}
    </label>
  );

  const help = input.description ? (
    <p className="text-[10px] text-[#6B6B6E] mt-1">{input.description}</p>
  ) : null;

  switch (input.type) {
    case 'boolean':
      return (
        <div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => onChange(e.target.checked)}
              className="accent-[#FFB020]"
            />
            <span className="text-xs text-white">{input.name}</span>
            {input.required && <span className="text-rose-400 text-xs">*</span>}
          </label>
          {help}
        </div>
      );

    case 'number':
      return (
        <div>
          {label}
          <input
            type="number"
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
            className={INPUT_CLS}
          />
          {help}
        </div>
      );

    case 'json':
      return (
        <div>
          {label}
          <textarea
            rows={4}
            value={typeof value === 'string' ? value : value ? JSON.stringify(value, null, 2) : ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="{ }"
            className={`${INPUT_CLS} font-mono resize-y`}
          />
          {help}
        </div>
      );

    case 'file':
      return (
        <div>
          {label}
          <input
            type="text"
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value)}
            placeholder="/path/to/file"
            className={INPUT_CLS}
          />
          {help}
        </div>
      );

    case 'credential':
      return (
        <div>
          {label}
          <input
            type="text"
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value)}
            placeholder="credential name / id"
            className={INPUT_CLS}
          />
          {help}
        </div>
      );

    case 'string':
    default:
      return (
        <div>
          {label}
          <input
            type="text"
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value)}
            className={INPUT_CLS}
          />
          {help}
        </div>
      );
  }
}

export function NodeConfigPanel({ node, onClose, onLabelChange, onParamChange }: Props) {
  if (!node) return null;

  const inputs = node.inputs ?? [];
  const params = node.data.params ?? {};

  return (
    <div className="w-80 shrink-0 bg-[#0C0C0E] border-l border-white/[0.08] overflow-y-auto">
      <div className="flex items-center justify-between px-4 h-12 border-b border-white/[0.08] sticky top-0 bg-[#0C0C0E] z-10">
        <span className="text-sm font-medium text-white">Node Settings</span>
        <button
          onClick={onClose}
          className="p-1 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] cursor-pointer"
        >
          <X size={16} />
        </button>
      </div>

      <div className="p-4 space-y-4">
        <div>
          <label className={LABEL_CLS}>Label</label>
          <input
            type="text"
            value={node.data.label}
            onChange={(e) => onLabelChange(node.id, e.target.value)}
            className={INPUT_CLS}
          />
        </div>

        {node.data.nodeId && (
          <div className="text-[10px] font-mono text-[#6B6B6E]">
            Node: <span className="text-[#FFB020]">{node.data.nodeId}</span>
            {node.data.category ? ` · ${node.data.category}` : ''}
          </div>
        )}

        {inputs.length > 0 ? (
          <div className="space-y-3 pt-1 border-t border-white/[0.06]">
            <div className="text-[10px] font-mono text-[#6B6B6E] uppercase pt-2">Parameters</div>
            {inputs.map((input) => (
              <ParamField
                key={input.name}
                input={input}
                value={params[input.name] ?? input.default}
                onChange={(v) => onParamChange(node.id, input.name, v)}
              />
            ))}
          </div>
        ) : (
          <div className="text-[10px] text-[#6B6B6E] pt-2 border-t border-white/[0.06]">
            This node has no configurable parameters.
          </div>
        )}
      </div>
    </div>
  );
}
