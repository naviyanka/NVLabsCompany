/**
 * Custom reactflow node components for the pipeline builder.
 *
 * Mirrors the OpenCompany COMPONENT_BY_KIND pattern: a small set of memoized
 * components (Trigger / Agent / Action), each reading its visuals from node.data
 * and rendering handles. node.data carries { label, category, icon, color,
 * nodeId, params, disabled? }.
 */

import { Trash2 } from 'lucide-react';
import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps } from 'reactflow';
import { categoryColor } from './categories';
import { NodeIcon } from './NodeIcon';

export interface BuilderNodeData {
  label: string;
  category?: string;
  icon?: string;
  color?: string;
  /** Backend registry node id (from /api/v1/nodes). */
  nodeId?: string;
  /** Parameter values keyed by node input name. */
  params?: Record<string, unknown>;
  /** Agent shown as subtitle for agent-kind nodes. */
  agent?: string;
  disabled?: boolean;
}

const HANDLE_STYLE_BASE: React.CSSProperties = {
  width: 10,
  height: 10,
  border: '2px solid',
  background: '#0C0C0E',
};

function NodeShell({
  id,
  data,
  selected,
  showInput,
  showOutput,
}: {
  id: string;
  data: BuilderNodeData;
  selected?: boolean;
  showInput: boolean;
  showOutput: boolean;
}) {
  const { deleteElements } = useReactFlow();
  const color = data.color || categoryColor(data.category);
  const subtitle = data.agent || data.category || '';

  const onDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    void deleteElements({ nodes: [{ id }] });
  };

  return (
    <div
      className="group relative rounded-[10px] border shadow-lg"
      style={{
        width: 210,
        background: '#141416',
        borderColor: selected ? '#FFB020' : color + '80',
        borderWidth: selected ? 2 : 1.2,
        opacity: data.disabled ? 0.5 : 1,
      }}
    >
      {/* accent bar */}
      <div
        className="absolute left-0 top-0 bottom-0 rounded-l-[10px]"
        style={{ width: 4, background: color }}
      />

      {/* delete button — visible on hover or when selected */}
      <button
        type="button"
        onClick={onDelete}
        title="Delete node"
        className={`nodrag absolute -top-2.5 -right-2.5 z-10 flex h-5 w-5 items-center justify-center rounded-full border border-white/20 bg-[#1A1A1E] text-rose-400 hover:bg-rose-500 hover:text-white transition-opacity cursor-pointer ${selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
          }`}
      >
        <Trash2 size={11} />
      </button>

      {showInput && (
        <Handle
          type="target"
          position={Position.Left}
          style={{ ...HANDLE_STYLE_BASE, borderColor: color }}
        />
      )}

      <div className="flex items-center gap-2.5 px-3 py-2.5 pl-4">
        <span
          className="flex items-center justify-center rounded shrink-0"
          style={{
            width: 30,
            height: 30,
            background: color + '18',
            border: `1px solid ${color}60`,
          }}
        >
          <NodeIcon icon={data.icon} category={data.category} size={16} color={color} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-white truncate">
            {data.label}
          </div>
          {subtitle && (
            <div className="text-[10px] font-mono text-[#6B6B6E] truncate">
              {subtitle}
            </div>
          )}
        </div>
      </div>

      {showOutput && (
        <Handle
          type="source"
          position={Position.Right}
          style={{ ...HANDLE_STYLE_BASE, borderColor: color }}
        />
      )}
    </div>
  );
}

export const TriggerNode = memo(({ id, data, selected }: NodeProps<BuilderNodeData>) => (
  <NodeShell id={id} data={data} selected={selected} showInput={false} showOutput={true} />
));
TriggerNode.displayName = 'TriggerNode';

export const AgentNode = memo(({ id, data, selected }: NodeProps<BuilderNodeData>) => (
  <NodeShell id={id} data={data} selected={selected} showInput={true} showOutput={true} />
));
AgentNode.displayName = 'AgentNode';

export const ActionNode = memo(({ id, data, selected }: NodeProps<BuilderNodeData>) => (
  <NodeShell id={id} data={data} selected={selected} showInput={true} showOutput={true} />
));
ActionNode.displayName = 'ActionNode';

/** Passed to <ReactFlow nodeTypes={...} />. Keys must match node.type. */
export const nodeTypes = {
  trigger: TriggerNode,
  agent: AgentNode,
  action: ActionNode,
};
