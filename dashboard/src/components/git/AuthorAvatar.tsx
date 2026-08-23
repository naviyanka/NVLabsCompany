import React, { useState } from 'react';
import { Bot, User, Shield, Sparkles, Terminal, Wrench, Code2, Layers } from 'lucide-react';

interface AuthorMeta {
  role: string;
  color: string;
  bgColor: string;
  borderColor: string;
  initials: string;
  icon: React.ElementType;
  isAgent: boolean;
  avatarUrl?: string;
}

const AGENT_METAS: Record<string, Partial<AuthorMeta>> = {
  'Atlas-01': {
    role: 'Lead Coordinator & Dispatcher',
    color: '#FFB020',
    bgColor: 'rgba(255, 176, 32, 0.15)',
    borderColor: 'rgba(255, 176, 32, 0.4)',
    initials: 'AT',
    icon: Sparkles,
    isAgent: true,
  },
  'Nova-02': {
    role: 'Chief Technology Officer / Architecture',
    color: '#818CF8',
    bgColor: 'rgba(129, 140, 248, 0.15)',
    borderColor: 'rgba(129, 140, 248, 0.4)',
    initials: 'NV',
    icon: Layers,
    isAgent: true,
  },
  'Bolt-03': {
    role: 'Senior Backend & Systems Engineer',
    color: '#34D399',
    bgColor: 'rgba(52, 211, 153, 0.15)',
    borderColor: 'rgba(52, 211, 153, 0.4)',
    initials: 'BL',
    icon: Terminal,
    isAgent: true,
  },
  'Pixel-04': {
    role: 'Frontend & 3D WebGL Graphics Lead',
    color: '#F43F5E',
    bgColor: 'rgba(244, 63, 94, 0.15)',
    borderColor: 'rgba(244, 63, 94, 0.4)',
    initials: 'PX',
    icon: Code2,
    isAgent: true,
  },
  'Sage-05': {
    role: 'AI Research & AST Parsing Lead',
    color: '#C084FC',
    bgColor: 'rgba(192, 132, 252, 0.15)',
    borderColor: 'rgba(192, 132, 252, 0.4)',
    initials: 'SG',
    icon: Bot,
    isAgent: true,
  },
  'Forge-08': {
    role: 'DevOps & Reliability Engineer',
    color: '#FB923C',
    bgColor: 'rgba(251, 146, 60, 0.15)',
    borderColor: 'rgba(251, 146, 60, 0.4)',
    initials: 'FG',
    icon: Wrench,
    isAgent: true,
  },
  'Shield-07': {
    role: 'Security & Quality Assurance Lead',
    color: '#38BDF8',
    bgColor: 'rgba(56, 189, 248, 0.15)',
    borderColor: 'rgba(56, 189, 248, 0.4)',
    initials: 'SH',
    icon: Shield,
    isAgent: true,
  },
};

const PALETTE = [
  { color: '#38BDF8', bgColor: 'rgba(56, 189, 248, 0.15)', borderColor: 'rgba(56, 189, 248, 0.35)' },
  { color: '#A855F7', bgColor: 'rgba(168, 85, 247, 0.15)', borderColor: 'rgba(168, 85, 247, 0.35)' },
  { color: '#22C55E', bgColor: 'rgba(34, 197, 94, 0.15)', borderColor: 'rgba(34, 197, 94, 0.35)' },
  { color: '#FFB020', bgColor: 'rgba(255, 176, 32, 0.15)', borderColor: 'rgba(255, 176, 32, 0.35)' },
  { color: '#F43F5E', bgColor: 'rgba(244, 63, 94, 0.15)', borderColor: 'rgba(244, 63, 94, 0.35)' },
  { color: '#EC4899', bgColor: 'rgba(236, 72, 153, 0.15)', borderColor: 'rgba(236, 72, 153, 0.35)' },
];

export function getAuthorMeta(name?: string, customAvatarUrl?: string): AuthorMeta {
  const cleanName = (name || 'Agent').trim();
  const known = AGENT_METAS[cleanName];

  if (known) {
    return {
      role: known.role || 'Autonomous Agent',
      color: known.color || '#FFB020',
      bgColor: known.bgColor || 'rgba(255, 176, 32, 0.15)',
      borderColor: known.borderColor || 'rgba(255, 176, 32, 0.35)',
      initials: known.initials || cleanName.slice(0, 2).toUpperCase(),
      icon: known.icon || Bot,
      isAgent: true,
      avatarUrl: customAvatarUrl || known.avatarUrl,
    };
  }

  // Generate deterministic hash for arbitrary names
  let hash = 0;
  for (let i = 0; i < cleanName.length; i++) {
    hash = (hash << 5) - hash + cleanName.charCodeAt(i);
    hash |= 0;
  }
  const colorIndex = Math.abs(hash) % PALETTE.length;
  const pickedPalette = PALETTE[colorIndex] ?? PALETTE[0] ?? { color: '#60a5fa', bgColor: 'rgba(96, 165, 250, 0.1)', borderColor: 'rgba(96, 165, 250, 0.2)' };

  const words = (cleanName || 'Agent').split(/[\s-_]+/);
  const firstChar = words[0]?.[0] || '';
  const secondChar = words[1]?.[0] || '';
  const initials =
    words.length >= 2 && firstChar && secondChar
      ? (firstChar + secondChar).toUpperCase()
      : cleanName.slice(0, 2).toUpperCase();

  const isAgent = /agent|bot|\d{2}/i.test(cleanName);

  return {
    role: isAgent ? 'Autonomous Agent' : 'Developer / Contributor',
    color: pickedPalette.color,
    bgColor: pickedPalette.bgColor,
    borderColor: pickedPalette.borderColor,
    initials,
    icon: isAgent ? Bot : User,
    isAgent,
    avatarUrl: customAvatarUrl,
  };
}

interface AuthorAvatarProps {
  name: string;
  avatarUrl?: string;
  role?: string;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  showTooltip?: boolean;
  showName?: boolean;
  showRole?: boolean;
  className?: string;
}

export function AuthorAvatar({
  name,
  avatarUrl,
  role,
  size = 'sm',
  showTooltip = true,
  showName = false,
  showRole = false,
  className = '',
}: AuthorAvatarProps) {
  const [imageError, setImageError] = useState(false);
  const meta = getAuthorMeta(name, avatarUrl);
  const finalRole = role || meta.role;

  const sizeClasses = {
    xs: 'w-4 h-4 text-[8px]',
    sm: 'w-6 h-6 text-[10px]',
    md: 'w-7 h-7 text-xs',
    lg: 'w-9 h-9 text-sm',
  }[size];

  const displayAvatar = (
    <div
      title={showTooltip ? `${name} • ${finalRole}` : undefined}
      className={`relative shrink-0 rounded-full flex items-center justify-center font-mono font-bold select-none transition-transform duration-150 overflow-hidden ${sizeClasses} ${className}`}
      style={{
        backgroundColor: meta.bgColor,
        border: `1px solid ${meta.borderColor}`,
        color: meta.color,
        boxShadow: `0 0 6px ${meta.borderColor}`,
      }}
    >
      {meta.avatarUrl && !imageError ? (
        <img
          src={meta.avatarUrl}
          alt={name}
          onError={() => setImageError(true)}
          className="w-full h-full object-cover rounded-full"
        />
      ) : (
        <span className="leading-none flex items-center justify-center">
          {meta.initials}
        </span>
      )}

      {/* Online indicator dot for agents */}
      {meta.isAgent && size !== 'xs' && (
        <span
          className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-[#101012]"
          style={{ backgroundColor: meta.color }}
        />
      )}
    </div>
  );

  if (!showName && !showRole) {
    return displayAvatar;
  }

  return (
    <div className="flex items-center gap-2 min-w-0 font-mono">
      {displayAvatar}
      <div className="min-w-0 flex flex-col">
        {showName && (
          <span className="text-xs font-medium text-[#F2F1EE] truncate hover:text-[#FFB020] transition-colors">
            {name}
          </span>
        )}
        {showRole && (
          <span className="text-[10px] text-[#6B6B6E] truncate leading-tight">
            {finalRole}
          </span>
        )}
      </div>
    </div>
  );
}
