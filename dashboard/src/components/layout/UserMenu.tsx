import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Check, ChevronDown, LogOut, Settings as SettingsIcon, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

const ROLE_COLORS: Record<string, string> = {
  admin: 'text-[#FFB020] bg-[#FFB020]/12 border-[#FFB020]/25',
  manager: 'text-[#38BDF8] bg-[#38BDF8]/12 border-[#38BDF8]/25',
  agent: 'text-[#22C55E] bg-[#22C55E]/12 border-[#22C55E]/25',
  viewer: 'text-[#A8A8AB] bg-white/[0.06] border-white/[0.12]',
};

function initials(displayName?: string): string {
  if (!displayName) return '?';
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return (parts[0] ?? '?').slice(0, 2).toUpperCase();
  const first = parts[0]?.[0] ?? '';
  const last = parts[parts.length - 1]?.[0] ?? '';
  return (first + last).toUpperCase() || '?';
}

/**
 * Identity control: who you are, which company you are acting in, and the way
 * out. Renders nothing until identity is known so the header does not flash a
 * placeholder name.
 */
export function UserMenu() {
  const { me, role, logout, switchCompany } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onEscape);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onEscape);
    };
  }, [open]);

  if (!me) return null;

  const handleSwitch = async (companyId: string) => {
    if (companyId === me.company_id) {
      setOpen(false);
      return;
    }
    setSwitching(companyId);
    try {
      await switchCompany(companyId);
      setOpen(false);
      // Every open panel is scoped to the old company; a reload is the honest
      // way to drop that state rather than refetching two dozen views by hand.
      window.location.reload();
    } finally {
      setSwitching('');
    }
  };

  const handleSignOut = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const roleClass = ROLE_COLORS[role] ?? ROLE_COLORS.viewer;

  return (
    <div className="relative pl-2 border-l border-white/[0.08]" ref={containerRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2.5 p-1 rounded-lg hover:bg-white/[0.04] transition-colors cursor-pointer group text-left"
        aria-label="Account menu"
        aria-expanded={open}
      >
        <div className="relative">
          <div className="w-8 h-8 rounded-full bg-[#FFB020]/15 ring-1 ring-[#FFB020]/30 group-hover:ring-[#FFB020] flex items-center justify-center">
            <span className="text-[11px] font-mono font-medium text-[#FFB020]">
              {initials(me.display_name)}
            </span>
          </div>
          <span className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-[#0A0A0B]" />
        </div>

        <div className="hidden md:block max-w-[10rem]">
          <div className="text-xs font-semibold text-[#F2F1EE] leading-tight truncate">
            {me.display_name}
          </div>
          <div className="text-[10px] text-[#A8A8AB] font-mono leading-tight truncate">
            {role || 'unknown'} · {me.company_name}
          </div>
        </div>

        <ChevronDown
          className={`w-3.5 h-3.5 text-[#6B6B6E] group-hover:text-[#F2F1EE] transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-72 bg-[#1C1C1F] border border-white/[0.14] rounded-[10px] shadow-2xl z-50 animate-in fade-in-0 zoom-in-95 duration-100">
          {/* Identity */}
          <div className="p-3.5 border-b border-white/[0.08]">
            <p className="text-sm font-medium text-[#F2F1EE] truncate">{me.display_name}</p>
            {me.user && (
              <p className="text-xs font-mono text-[#6B6B6E] truncate mt-0.5">{me.user.email}</p>
            )}
            <div className="flex items-center gap-2 mt-2">
              <span
                className={`px-1.5 py-0.5 text-[10px] font-mono uppercase rounded border ${roleClass}`}
              >
                {role || 'unknown'}
              </span>
              {me.kind === 'api_key' && (
                <span className="px-1.5 py-0.5 text-[10px] font-mono uppercase rounded border border-white/[0.12] text-[#A8A8AB]">
                  service token
                </span>
              )}
            </div>
          </div>

          {/* Company switcher — only worth showing when there is a choice */}
          {me.memberships.length > 1 && (
            <div className="py-1.5 border-b border-white/[0.08]">
              <p className="px-3.5 py-1 text-[10px] font-mono uppercase tracking-wider text-[#6B6B6E]">
                Switch Company
              </p>
              {me.memberships.map((membership) => (
                <button
                  key={membership.company_id}
                  onClick={() => handleSwitch(membership.company_id)}
                  disabled={switching !== ''}
                  className="w-full flex items-center gap-2.5 px-3.5 py-2 text-left hover:bg-white/[0.04] disabled:opacity-50 transition-colors cursor-pointer"
                >
                  <Building2 className="w-3.5 h-3.5 text-[#6B6B6E] shrink-0" />
                  <span className="flex-1 min-w-0 text-xs text-[#F2F1EE] truncate">
                    {membership.company_name}
                  </span>
                  <span className="text-[10px] font-mono text-[#6B6B6E] uppercase">
                    {membership.role}
                  </span>
                  {membership.company_id === me.company_id && (
                    <Check className="w-3.5 h-3.5 text-[#22C55E] shrink-0" />
                  )}
                </button>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="py-1.5">
            <button
              onClick={() => {
                setOpen(false);
                navigate('/settings');
              }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#F2F1EE] hover:bg-white/[0.04] transition-colors cursor-pointer"
            >
              <SettingsIcon className="w-3.5 h-3.5 text-[#6B6B6E]" />
              Settings
            </button>
            <button
              onClick={() => {
                setOpen(false);
                navigate('/settings?panel=security');
              }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#F2F1EE] hover:bg-white/[0.04] transition-colors cursor-pointer"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-[#6B6B6E]" />
              Password &amp; sessions
            </button>
            <button
              onClick={handleSignOut}
              className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#EF4444] hover:bg-[#EF4444]/10 transition-colors cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
