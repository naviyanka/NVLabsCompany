import { Search } from 'lucide-react';
import { NavLink } from 'react-router-dom';

export function Header() {
  return (
    <header className="h-14 bg-[#1a1b2e] border-b border-white/[0.08] flex items-center justify-between px-6">
      {/* Search */}
      <div className="flex items-center gap-4">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search agents, tasks, pipelines..."
            className="w-72 pl-9 pr-16 py-1.5 bg-[#0f1117] border border-white/[0.08] rounded-lg text-sm text-gray-300 placeholder-gray-500 focus:outline-none focus:border-indigo-500/50"
          />
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-gray-500 bg-[#1a1b2e] border border-white/[0.08] rounded px-1.5 py-0.5">
            Ctrl+K
          </span>
        </div>
      </div>

      {/* Toggle Buttons */}
      <div className="flex items-center gap-1 bg-[#0f1117] rounded-lg p-1">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `px-3 py-1 text-sm rounded-md font-medium transition-colors ${
              isActive ? 'bg-[#1a1b2e] text-white' : 'text-gray-400 hover:text-gray-200'
            }`
          }
        >
          Dashboard
        </NavLink>
        <NavLink
          to="/office"
          className={({ isActive }) =>
            `px-3 py-1 text-sm rounded-md font-medium transition-colors ${
              isActive ? 'bg-[#14b8a6] text-white' : 'text-gray-400 hover:text-gray-200'
            }`
          }
        >
          Office
        </NavLink>
      </div>

      {/* User Info */}
      <div className="flex items-center gap-3">
        <div className="text-right">
          <p className="text-sm text-white font-medium">Navi Yanka</p>
          <p className="text-[10px] text-gray-500">Operator</p>
        </div>
        <div className="h-8 w-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center">
          <span className="text-white text-xs font-bold">NY</span>
        </div>
      </div>
    </header>
  );
}
