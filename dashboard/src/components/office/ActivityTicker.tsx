import type { OfficeEvent } from '@/types/office';

interface ActivityTickerProps {
  events: OfficeEvent[];
}

const eventTypeColors: Record<string, string> = {
  task_completed: 'text-emerald-600',
  delegation: 'text-blue-600',
  issue: 'text-rose-600',
  meeting: 'text-purple-600',
  status_change: 'text-gray-600',
};

const eventTypeBadge: Record<string, string> = {
  task_completed: 'bg-emerald-100 text-emerald-700',
  delegation: 'bg-blue-100 text-blue-700',
  issue: 'bg-rose-100 text-rose-700',
  meeting: 'bg-purple-100 text-purple-700',
  status_change: 'bg-gray-100 text-gray-700',
};

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function ActivityTicker({ events }: ActivityTickerProps) {
  if (events.length === 0) {
    return (
      <div className="absolute bottom-0 left-0 right-0 z-20 bg-white/95 backdrop-blur-sm border-t border-gray-200 px-4 py-2">
        <span className="text-xs text-gray-400">No recent activity</span>
      </div>
    );
  }

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 bg-white/95 backdrop-blur-sm border-t border-gray-200 overflow-hidden">
      <div className="flex items-center h-8">
        {/* Label */}
        <div className="flex-shrink-0 px-3 py-1 bg-gray-800 text-white text-[10px] font-semibold h-full flex items-center">
          ACTIVITY
        </div>

        {/* Scrolling ticker */}
        <div className="flex-1 overflow-hidden relative">
          <div className="animate-office-ticker flex items-center gap-6 whitespace-nowrap px-4">
            {events.map((event) => (
              <div key={event.id} className="flex items-center gap-2 flex-shrink-0">
                <span className="text-[9px] text-gray-400 font-mono">
                  {formatTime(event.timestamp)}
                </span>
                <span
                  className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${eventTypeBadge[event.type] || eventTypeBadge.status_change}`}
                >
                  {event.type.replace('_', ' ')}
                </span>
                <span
                  className={`text-[11px] ${eventTypeColors[event.type] || 'text-gray-600'}`}
                >
                  {event.message}
                </span>
              </div>
            ))}
            {/* Duplicate for seamless loop */}
            {events.map((event) => (
              <div key={`dup-${event.id}`} className="flex items-center gap-2 flex-shrink-0">
                <span className="text-[9px] text-gray-400 font-mono">
                  {formatTime(event.timestamp)}
                </span>
                <span
                  className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${eventTypeBadge[event.type] || eventTypeBadge.status_change}`}
                >
                  {event.type.replace('_', ' ')}
                </span>
                <span
                  className={`text-[11px] ${eventTypeColors[event.type] || 'text-gray-600'}`}
                >
                  {event.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
