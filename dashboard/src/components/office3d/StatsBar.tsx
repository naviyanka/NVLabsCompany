import { Users, Activity, Coffee, AlertCircle, WifiOff } from 'lucide-react';
import { mockAgents3D, managerAgent, status3DColors } from '@/config/office3dLayout';

/**
 * Top stats bar overlay showing agent status counts.
 * Includes view mode hint and interaction tips.
 */
export function StatsBar() {
  const allAgents = [...mockAgents3D, managerAgent];
  const total = allAgents.length;
  const active = allAgents.filter((a) => a.status === 'working').length;
  const idle = allAgents.filter((a) => a.status === 'idle').length;
  const review = allAgents.filter((a) => a.status === 'review').length;
  const offline = allAgents.filter((a) => a.status === 'offline').length;

  const stats = [
    { label: 'Total Agents', value: total, icon: Users, color: '#ffffff' },
    { label: 'Active', value: active, icon: Activity, color: status3DColors.working },
    { label: 'Idle', value: idle, icon: Coffee, color: status3DColors.idle },
    { label: 'Review', value: review, icon: AlertCircle, color: status3DColors.review },
    { label: 'Offline', value: offline, icon: WifiOff, color: status3DColors.offline },
  ];

  return (
    <div className="absolute top-0 left-0 right-0 z-10 pointer-events-none">
      <div className="flex items-center justify-between px-4 py-3 bg-dark-bg/90 backdrop-blur-sm border-b border-white/[0.08]">
        {/* Stats */}
        <div className="flex items-center gap-5 pointer-events-auto">
          {stats.map((stat) => (
            <div key={stat.label} className="flex items-center gap-2">
              <stat.icon size={14} style={{ color: stat.color }} />
              <span className="text-xs text-gray-400">{stat.label}:</span>
              <span
                className="text-sm font-semibold"
                style={{ color: stat.color }}
              >
                {stat.value}
              </span>
            </div>
          ))}
        </div>

        {/* View mode & hint */}
        <div className="flex items-center gap-4 pointer-events-auto">
          <span className="text-[10px] text-gray-500 hidden lg:block">
            Drag to pan &bull; Scroll to zoom &bull; Click agent to inspect
          </span>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-dark-surface border border-white/[0.08]">
            <div className="w-2 h-2 rounded-full bg-indigo-500" />
            <span className="text-xs text-gray-300">3D Floor Plan</span>
          </div>
        </div>
      </div>
    </div>
  );
}
