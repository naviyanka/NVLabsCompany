import { useState, useEffect, useRef } from 'react';
import { ChevronDown, FolderOpen, Check } from 'lucide-react';
import { apiClient } from '../../api/client';
import { getActiveCompanyId } from '@/config';

interface Workspace {
  id: string;
  name: string;
  path: string;
  is_active: boolean;
  is_git_repo: boolean;
}

export function WorkspaceSwitcher() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const active = workspaces.find((w) => w.is_active);

  useEffect(() => {
    const companyId = getActiveCompanyId();
    apiClient
      .get<Workspace[]>(`/api/v1/companies/${companyId}/workspaces`)
      .then((res: Workspace[]) => {
        if (Array.isArray(res)) setWorkspaces(res);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const activate = async (id: string) => {
    await apiClient.post(`/api/v1/workspaces/${id}/activate`);
    setWorkspaces((prev) =>
      prev.map((w) => ({ ...w, is_active: w.id === id }))
    );
    setOpen(false);
  };

  if (workspaces.length === 0) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 text-xs font-mono text-[#A8A8AB] hover:text-[#F2F1EE] bg-white/[0.04] hover:bg-white/[0.08] rounded-[4px] transition-colors cursor-pointer border border-white/[0.06]"
        aria-label="Switch workspace"
      >
        <FolderOpen className="w-3.5 h-3.5" />
        <span className="truncate max-w-[120px]">{active?.name ?? 'Workspace'}</span>
        <ChevronDown className="w-3 h-3" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-56 bg-[#141416] border border-white/[0.08] rounded-[6px] shadow-xl z-50 py-1 overflow-hidden">
          <div className="px-3 py-1.5 text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider">
            Workspaces
          </div>
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              onClick={() => activate(ws.id)}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.04] transition-colors text-left"
            >
              <FolderOpen className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate flex-1">{ws.name}</span>
              {ws.is_active && <Check className="w-3.5 h-3.5 text-[#22C55E]" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
