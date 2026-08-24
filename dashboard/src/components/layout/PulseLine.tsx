import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { apiClient } from '../../api/client';
import { getActiveCompanyId } from '../../config';

export interface PulseEvent {
  id: string;
  type: string;
  actor: string;
  target: string;
  target_id: string;
  target_type: string;
  timestamp: string;
  details?: string;
}

export function PulseLine() {
  const [events, setEvents] = useState<PulseEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [hoveredEvent, setHoveredEvent] = useState<PulseEvent | null>(null);
  const [isConnected, setIsConnected] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    // Initial fetch of recent telemetry events
    const fetchPulse = async () => {
      try {
        const res = await apiClient.get<PulseEvent[]>(`/api/v1/companies/${getActiveCompanyId()}/pulse`);
        if (Array.isArray(res)) {
          setEvents(res);
        }
      } catch {
        setIsConnected(false);
      }
    };
    fetchPulse();

    // SSE connection for live updates
    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource(`/api/v1/companies/${getActiveCompanyId()}/activity/stream`);
      eventSource.onopen = () => setIsConnected(true);
      eventSource.onmessage = (e) => {
        try {
          const newEvent = JSON.parse(e.data) as PulseEvent;
          setEvents((prev) => [newEvent, ...prev.slice(0, 19)]);
        } catch {
          // ignore parse errors
        }
      };
      eventSource.onerror = () => {
        setIsConnected(false);
      };
    } catch {
      setIsConnected(false);
    }

    return () => {
      if (eventSource) eventSource.close();
    };
  }, []);

  const handleJump = (event: PulseEvent) => {
    if (event.target_type === 'agent') {
      navigate(`/agents/${event.target_id}`);
    } else if (event.target_type === 'task') {
      navigate('/tasks');
    } else if (event.target_type === 'pipeline') {
      navigate('/pipelines');
    } else if (event.target_type === 'budget') {
      navigate('/budgets');
    } else if (event.target_type === 'evolution') {
      navigate('/evolution');
    } else if (event.target_type === 'repo') {
      navigate('/git-repos');
    } else {
      navigate('/activity');
    }
  };

  const displayList = events.length > 0 ? events : [
    { id: '1', type: 'agent.wake', actor: 'Atlas-01', target: 'Content Pipeline', target_id: 'pipe-release', target_type: 'pipeline', timestamp: new Date().toISOString() },
    { id: '2', type: 'task.completed', actor: 'Bolt-03', target: 'Router #4471', target_id: 'task-4471', target_type: 'task', timestamp: new Date().toISOString() },
    { id: '3', type: 'budget.threshold', actor: 'System', target: 'Engineering Dept (82%)', target_id: 'dept-eng', target_type: 'budget', timestamp: new Date().toISOString() },
  ];

  return (
    <div
      className="h-8 bg-[#0A0A0B] border-b border-white/[0.08] flex items-center px-4 overflow-hidden relative select-none z-20 shrink-0"
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => {
        setIsPaused(false);
        setHoveredEvent(null);
      }}
    >
      {/* Ticker label & connection badge */}
      <div className="flex items-center gap-2 pr-3 bg-[#0A0A0B] z-10 shrink-0 border-r border-white/[0.06]">
        <span className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-widest text-[#6B6B6E]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#FFB020] animate-pulse" />
          Pulse
        </span>
        {!isConnected && (
          <span className="text-[10px] font-mono text-[#F97316] bg-[#F97316]/10 px-1 rounded-[2px]">
            Reconnecting…
          </span>
        )}
      </div>

      {/* Streaming Event Items */}
      <div className="flex-1 overflow-hidden relative ml-3">
        <div
          className={`flex items-center gap-8 whitespace-nowrap font-mono text-xs text-[#A8A8AB] ${
            isPaused ? '' : 'animate-pulse-line'
          }`}
          style={{ animationPlayState: isPaused ? 'paused' : 'running' }}
        >
          {/* Loop twice for seamless scrolling */}
          {[...displayList, ...displayList].map((evt, idx) => {
            const timeStr = new Date(evt.timestamp).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: false,
            });

            return (
              <div
                key={`${evt.id}-${idx}`}
                onMouseEnter={() => setHoveredEvent(evt)}
                onClick={() => handleJump(evt)}
                className="inline-flex items-center gap-2 hover:text-[#F2F1EE] cursor-pointer transition-colors group py-1"
              >
                <span className="text-[#6B6B6E] text-[11px]">{timeStr}</span>
                <span className="text-[#6B6B6E]">·</span>
                <span className="text-[#FFB020] font-medium">{evt.type}</span>
                <span className="text-[#6B6B6E]">·</span>
                <span className="text-[#F2F1EE]">{evt.actor}</span>
                <span className="text-[#6B6B6E]">·</span>
                <span className="text-[#A8A8AB] group-hover:text-[#FFB020] transition-colors">{evt.target}</span>

                <ArrowUpRight className="w-3 h-3 text-[#6B6B6E] group-hover:text-[#FFB020] opacity-0 group-hover:opacity-100 transition-all inline-block" />
              </div>
            );
          })}
        </div>
      </div>

      {/* Hover Inspection Quick Action */}
      {hoveredEvent && (
        <div className="hidden lg:flex items-center gap-2 pl-3 bg-[#0A0A0B] z-10 shrink-0 border-l border-white/[0.06] text-[11px] font-mono">
          <span className="text-[#6B6B6E]">Focus:</span>
          <button
            onClick={() => handleJump(hoveredEvent)}
            className="text-[#FFB020] hover:underline flex items-center gap-1"
          >
            Jump to {hoveredEvent.target_type} <ArrowUpRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}
