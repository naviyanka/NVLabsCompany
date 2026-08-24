import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  Users,
  CheckSquare,
  DollarSign,
  TrendingUp,
  Settings,
  Plus,
  Layers,
} from 'lucide-react';
import { apiClient, unwrapItems } from '../../api/client';
import { getActiveCompanyId } from '../../config';

export interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenHireAgent?: () => void;
  onOpenCreateTask?: () => void;
}

interface CommandItem {
  id: string;
  category: 'Navigation' | 'Actions' | 'Agents' | 'Tasks';
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  action: () => void;
}

export function CommandPalette({
  isOpen,
  onClose,
  onOpenHireAgent,
  onOpenCreateTask,
}: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [agentsList, setAgentsList] = useState<Array<{ id: string; name: string; title: string }>>([]);
  const [tasksList, setTasksList] = useState<Array<{ id: string; title: string }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery('');
      setSelectedIndex(0);

      // Fetch dynamic entities
      const companyId = getActiveCompanyId();
      apiClient.get<Array<{ id: string; name: string; title: string }> | { items: Array<{ id: string; name: string; title: string }> }>(`/api/v1/companies/${companyId}/agents`)
        .then((res) => { const items = unwrapItems(res); if (items.length) setAgentsList(items); })
        .catch(() => {});

      apiClient.get<Array<{ id: string; title: string }> | { items: Array<{ id: string; title: string }> }>(`/api/v1/companies/${companyId}/tasks`)
        .then((res) => { const items = unwrapItems(res); if (items.length) setTasksList(items); })
        .catch(() => {});
    }
  }, [isOpen]);

  const baseCommands: CommandItem[] = [
    // Actions
    {
      id: 'act-hire',
      category: 'Actions',
      title: 'Hire Agent',
      subtitle: 'Deploy a new autonomous agent to the workforce',
      icon: <Plus className="w-4 h-4 text-[#FFB020]" />,
      action: () => {
        onClose();
        if (onOpenHireAgent) onOpenHireAgent();
        else navigate('/agents?new=true');
      },
    },
    {
      id: 'act-task',
      category: 'Actions',
      title: 'Create Task',
      subtitle: 'Assign a new objective to an agent',
      icon: <CheckSquare className="w-4 h-4 text-[#FFB020]" />,
      action: () => {
        onClose();
        if (onOpenCreateTask) onOpenCreateTask();
        else navigate('/tasks?new=true');
      },
    },
    // Navigation
    {
      id: 'nav-overview',
      category: 'Navigation',
      title: 'Go to Overview',
      subtitle: 'Main Mission Control operations telemetry',
      icon: <Layers className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/'); },
    },
    {
      id: 'nav-office',
      category: 'Navigation',
      title: 'Go to Office Floor',
      subtitle: '3D Simulation & 2D workspace map',
      icon: <Users className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/office'); },
    },
    {
      id: 'nav-agents',
      category: 'Navigation',
      title: 'Go to Agents',
      subtitle: 'Active workforce directory and status',
      icon: <Users className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/agents'); },
    },
    {
      id: 'nav-tasks',
      category: 'Navigation',
      title: 'Go to Tasks',
      subtitle: 'Kanban board & operational queue',
      icon: <CheckSquare className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/tasks'); },
    },
    {
      id: 'nav-budgets',
      category: 'Navigation',
      title: 'Go to Budgets & Governance',
      subtitle: 'Monthly spend, token consumption, and rate limits',
      icon: <DollarSign className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/budgets'); },
    },
    {
      id: 'nav-evolution',
      category: 'Navigation',
      title: 'Go to Evolution',
      subtitle: 'Prompt mutation proposals & statistical evals',
      icon: <TrendingUp className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/evolution'); },
    },
    {
      id: 'nav-settings',
      category: 'Navigation',
      title: 'Go to Settings',
      subtitle: 'Integrations, circuit breakers, and secrets',
      icon: <Settings className="w-4 h-4 text-[#A8A8AB]" />,
      action: () => { onClose(); navigate('/settings'); },
    },
  ];

  // Dynamic agent commands
  const dynamicAgentCommands: CommandItem[] = agentsList.map((ag) => ({
    id: `agent-${ag.id}`,
    category: 'Agents',
    title: ag.name,
    subtitle: `${ag.title} · Open Dossier & Chat`,
    icon: <Users className="w-4 h-4 text-[#38BDF8]" />,
    action: () => { onClose(); navigate(`/agents/${ag.id}`); },
  }));

  // Dynamic task commands
  const dynamicTaskCommands: CommandItem[] = tasksList.map((t) => ({
    id: `task-${t.id}`,
    category: 'Tasks',
    title: t.title,
    subtitle: `Task #${t.id}`,
    icon: <CheckSquare className="w-4 h-4 text-[#22C55E]" />,
    action: () => { onClose(); navigate('/tasks'); },
  }));

  const allItems = [...baseCommands, ...dynamicAgentCommands, ...dynamicTaskCommands];

  const filteredItems = allItems.filter((item) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      item.title.toLowerCase().includes(q) ||
      (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
      item.category.toLowerCase().includes(q)
    );
  });

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % (filteredItems.length || 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + (filteredItems.length || 1)) % (filteredItems.length || 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        filteredItems[selectedIndex].action();
      }
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 p-4" role="dialog" aria-modal="true">
      <div
        className="fixed inset-0 bg-[#0A0A0B]/80 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-xl bg-[#1C1C1F] border border-white/[0.14] rounded-[10px] shadow-2xl overflow-hidden flex flex-col z-10 animate-in fade-in-0 zoom-in-95 duration-150">
        {/* Search Bar Input */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-white/[0.08] bg-[#141416]">
          <Search className="w-4 h-4 text-[#6B6B6E] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Type a command or search workforce, tasks, telemetry..."
            className="w-full bg-transparent text-sm text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none font-sans"
          />
          <span className="text-[10px] font-mono text-[#6B6B6E] bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06]">
            ESC
          </span>
        </div>

        {/* Command List */}
        <div className="max-h-80 overflow-y-auto p-2 space-y-1">
          {filteredItems.length === 0 ? (
            <div className="p-8 text-center text-xs font-mono text-[#6B6B6E]">
              No matching commands or entities found.
            </div>
          ) : (
            filteredItems.map((item, index) => {
              const isSelected = index === selectedIndex;
              return (
                <div
                  key={item.id}
                  onClick={item.action}
                  onMouseEnter={() => setSelectedIndex(index)}
                  className={`flex items-center justify-between gap-3 px-3 py-2 rounded-[6px] cursor-pointer transition-colors ${
                    isSelected ? 'bg-white/[0.06] text-[#F2F1EE]' : 'text-[#A8A8AB] hover:bg-white/[0.02]'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="shrink-0">{item.icon}</span>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-[#F2F1EE] truncate">{item.title}</div>
                      {item.subtitle && (
                        <div className="text-[11px] font-mono text-[#6B6B6E] truncate">{item.subtitle}</div>
                      )}
                    </div>
                  </div>
                  <span className="text-[10px] font-mono text-[#6B6B6E] uppercase shrink-0">
                    {item.category}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Footer info */}
        <div className="px-4 py-2 border-t border-white/[0.06] bg-[#141416] flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
          <span>Use ↑↓ to navigate</span>
          <span>↵ to execute</span>
        </div>
      </div>
    </div>
  );
}
