import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain } from 'lucide-react';
import type { Agent } from '@/types/agent';
import type { AgentPositionStatus } from '@/types/office';
import { statusColors } from '@/config/officeLayout';

interface AgentAvatarProps {
  agent: Agent;
  x: number;
  y: number;
  status: AgentPositionStatus;
  currentTask?: string;
  showLabel: boolean;
}

function getInitials(name: string): string {
  const parts = name.split(/\s+/);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function getStatusRingColor(agentStatus: string): string {
  return statusColors[agentStatus] || statusColors.idle;
}

function isAnimating(agentStatus: string): boolean {
  return agentStatus === 'active' || agentStatus === 'busy';
}

function hasError(agentStatus: string): boolean {
  return agentStatus === 'error';
}

export function AgentAvatar({ agent, x, y, status, currentTask, showLabel }: AgentAvatarProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const navigate = useNavigate();

  const initials = getInitials(agent.name);
  const ringColor = getStatusRingColor(agent.status);
  const shouldPulse = isAnimating(agent.status);
  const shouldShake = hasError(agent.status);

  const handleClick = () => {
    navigate(`/agents/${agent.id}`);
  };

  return (
    <div
      className="absolute flex flex-col items-center cursor-pointer transition-all duration-500 ease-in-out"
      style={{
        left: `${x}px`,
        top: `${y}px`,
        transform: 'translate(-50%, -50%)',
      }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      aria-label={`Agent ${agent.name} - ${status}`}
    >
      {/* Avatar circle with status ring */}
      <div
        className={`relative w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-gray-700 bg-white shadow-sm border-2 ${shouldPulse ? 'animate-office-pulse' : ''} ${shouldShake ? 'animate-office-shake' : ''}`}
        style={{ borderColor: ringColor }}
      >
        {initials}

        {/* AI adapter type icon overlay */}
        <div className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 bg-white rounded-full flex items-center justify-center shadow-sm">
          <Brain size={9} className="text-indigo-500" />
        </div>
      </div>

      {/* Name label */}
      {showLabel && (
        <span className="mt-0.5 text-[9px] text-gray-600 whitespace-nowrap max-w-[60px] truncate text-center">
          {agent.name.split(' ')[0]}
        </span>
      )}

      {/* Tooltip */}
      {showTooltip && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 shadow-lg whitespace-nowrap pointer-events-none">
          <div className="font-semibold">{agent.name}</div>
          <div className="text-gray-300">{agent.role}</div>
          {currentTask && (
            <div className="text-gray-400 mt-0.5 max-w-[180px] truncate">
              Working on: {currentTask}
            </div>
          )}
          <div className="flex items-center gap-1 mt-0.5">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: ringColor }}
            />
            <span className="text-gray-400 capitalize">{agent.status}</span>
          </div>
          {/* Tooltip arrow */}
          <div className="absolute top-full left-1/2 -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900" />
        </div>
      )}
    </div>
  );
}
