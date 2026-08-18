import type { DelegationArrow, AgentPosition } from '@/types/office';
import { CANVAS_WIDTH, CANVAS_HEIGHT } from '@/config/officeLayout';

interface DelegationFlowProps {
  delegations: DelegationArrow[];
  agentPositions: AgentPosition[];
  visible: boolean;
}

const arrowStatusColors: Record<string, string> = {
  active: '#3b82f6',
  completed: '#10b981',
  failed: '#f43f5e',
};

export function DelegationFlow({ delegations, agentPositions, visible }: DelegationFlowProps) {
  if (!visible || delegations.length === 0) return null;

  const positionMap = new Map(agentPositions.map((p) => [p.agentId, p]));

  return (
    <svg
      className="absolute inset-0 pointer-events-none z-10"
      width={CANVAS_WIDTH}
      height={CANVAS_HEIGHT}
      style={{ overflow: 'visible' }}
    >
      <defs>
        {delegations.map((del) => (
          <marker
            key={`marker-${del.id}`}
            id={`arrowhead-${del.id}`}
            markerWidth="8"
            markerHeight="6"
            refX="7"
            refY="3"
            orient="auto"
          >
            <polygon
              points="0 0, 8 3, 0 6"
              fill={arrowStatusColors[del.status] || arrowStatusColors.active}
              opacity="0.7"
            />
          </marker>
        ))}
      </defs>

      {delegations.map((del) => {
        const fromPos = positionMap.get(del.fromAgentId);
        const toPos = positionMap.get(del.toAgentId);

        if (!fromPos || !toPos) return null;

        const color = arrowStatusColors[del.status] || arrowStatusColors.active;

        // Calculate a slight curve for the line
        const midX = (fromPos.x + toPos.x) / 2;
        const midY = (fromPos.y + toPos.y) / 2 - 20;

        return (
          <g key={del.id}>
            <path
              d={`M ${fromPos.x} ${fromPos.y} Q ${midX} ${midY} ${toPos.x} ${toPos.y}`}
              fill="none"
              stroke={color}
              strokeWidth="2"
              strokeDasharray="6 4"
              strokeLinecap="round"
              markerEnd={`url(#arrowhead-${del.id})`}
              opacity="0.6"
              className="animate-office-dash"
            />
            {/* Task label at midpoint */}
            <text
              x={midX}
              y={midY - 6}
              textAnchor="middle"
              className="text-[8px] fill-gray-500"
            >
              {del.taskTitle.length > 20
                ? `${del.taskTitle.slice(0, 20)}...`
                : del.taskTitle}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
