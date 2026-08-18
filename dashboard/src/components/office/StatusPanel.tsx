import { useState, useEffect } from 'react';
import { Activity, Users, CheckCircle2, VideoIcon, AlertCircle } from 'lucide-react';

interface StatusPanelProps {
  agentsOnline: number;
  tasksRunning: number;
  meetingsActive: number;
  loading: boolean;
}

function useOfficeClock() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return time;
}

export function StatusPanel({
  agentsOnline,
  tasksRunning,
  meetingsActive,
  loading,
}: StatusPanelProps) {
  const clock = useOfficeClock();
  const timeStr = clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const healthScore = agentsOnline > 0 ? Math.min(100, Math.round((agentsOnline / (agentsOnline + 1)) * 100)) : 0;
  const healthColor = healthScore >= 80 ? 'text-emerald-500' : healthScore >= 50 ? 'text-amber-500' : 'text-rose-500';

  return (
    <div className="absolute top-3 right-3 z-20 bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200 p-3 w-52">
      {/* Company name and clock */}
      <div className="flex items-center justify-between mb-2 pb-2 border-b border-gray-100">
        <div>
          <h3 className="text-xs font-bold text-gray-800">NEXUS Corp</h3>
          <span className="text-[10px] text-gray-500">Virtual Office</span>
        </div>
        <div className="text-right">
          <div className="text-sm font-mono font-semibold text-gray-700">{timeStr}</div>
        </div>
      </div>

      {/* Health indicator */}
      <div className="flex items-center gap-2 mb-2">
        <Activity size={12} className={healthColor} />
        <span className="text-[10px] text-gray-600">System Health:</span>
        <span className={`text-xs font-bold ${healthColor}`}>
          {loading ? '...' : `${healthScore}%`}
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-1.5">
        <div className="flex flex-col items-center p-1.5 rounded-lg bg-emerald-50">
          <Users size={12} className="text-emerald-600 mb-0.5" />
          <span className="text-sm font-bold text-emerald-700">{agentsOnline}</span>
          <span className="text-[8px] text-emerald-600">Online</span>
        </div>
        <div className="flex flex-col items-center p-1.5 rounded-lg bg-blue-50">
          <CheckCircle2 size={12} className="text-blue-600 mb-0.5" />
          <span className="text-sm font-bold text-blue-700">{tasksRunning}</span>
          <span className="text-[8px] text-blue-600">Running</span>
        </div>
        <div className="flex flex-col items-center p-1.5 rounded-lg bg-purple-50">
          <VideoIcon size={12} className="text-purple-600 mb-0.5" />
          <span className="text-sm font-bold text-purple-700">{meetingsActive}</span>
          <span className="text-[8px] text-purple-600">Meetings</span>
        </div>
      </div>

      {/* Alert indicator */}
      {tasksRunning === 0 && agentsOnline > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-100 flex items-center gap-1.5">
          <AlertCircle size={11} className="text-amber-500" />
          <span className="text-[9px] text-amber-600">No active tasks running</span>
        </div>
      )}
    </div>
  );
}
