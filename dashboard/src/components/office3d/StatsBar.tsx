import { Users, Activity, Coffee, AlertCircle, WifiOff } from 'lucide-react';
import { mockAgents3D, managerAgent } from '@/config/office3dLayout';

export function StatsBar() {
  const allAgents = [...mockAgents3D, managerAgent];
  const total = allAgents.length;
  const active = allAgents.filter((a) => a.status === 'working').length;
  const idle = allAgents.filter((a) => a.status === 'idle').length;
  const review = allAgents.filter((a) => a.status === 'review').length;
  const offline = allAgents.filter((a) => a.status === 'offline').length;

  const stats = [
    { label: 'Total', value: total, icon: Users, color: '#F2F1EE' },
    { label: 'Active', value: active, icon: Activity, color: '#22C55E' },
    { label: 'Idle', value: idle, icon: Coffee, color: '#9C9C9F' },
    { label: 'Review', value: review, icon: AlertCircle, color: '#FFB020' },
    { label: 'Offline', value: offline, icon: WifiOff, color: '#6B6B6E' },
  ];

  return (
    <div className="absolute top-0 left-0 right-0 z-10 pointer-events-none">
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#0A0A0B]/95 border-b border-white/[0.08]">
        {/* Stats list */}
        <div className="flex items-center gap-5 pointer-events-auto">
          {stats.map((stat) => (
            <div key={stat.label} className="flex items-center gap-2">
              <stat.icon size={13} style={{ color: stat.color }} />
              <span className="text-xs font-mono text-[#6B6B6E]">{stat.label}:</span>
              <span
                className="text-xs font-mono font-medium"
                style={{ color: stat.color }}
              >
                {stat.value}
              </span>
            </div>
          ))}
        </div>

        {/* View mode & hint */}
        <div className="flex items-center gap-4 pointer-events-auto">
          <span className="text-[10px] font-mono text-[#6B6B6E] hidden lg:block">
            Drag to pan · Scroll to zoom · Click agent to inspect
          </span>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] bg-[#141416] border border-white/[0.08]">
            <div className="w-1.5 h-1.5 rounded-full bg-[#FFB020] animate-pulse" />
            <span className="text-xs font-mono text-[#F2F1EE]">3D Floor Plan</span>
          </div>
        </div>
      </div>
    </div>
  );
}
