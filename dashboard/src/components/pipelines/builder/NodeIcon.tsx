/**
 * NodeIcon — resolves a node's lucide icon by name, matching the reference repo.
 *
 * Our backend serves a kebab-case lucide icon name per node (e.g. "brain",
 * "file-text", "git-pull-request"). lucide-react exports each icon in PascalCase
 * (Brain, FileText, GitPullRequest) and also a dynamic `icons` registry keyed by
 * PascalCase. We convert the name and look it up, falling back to a per-category
 * default and finally a generic Box.
 */

import { Box, icons, type LucideIcon } from 'lucide-react';

/** kebab-case (or snake) → PascalCase, e.g. "git-pull-request" → "GitPullRequest". */
function toPascal(name: string): string {
  return name
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

/** Per-category fallback icon name when a node has no explicit icon. */
const CATEGORY_FALLBACK: Record<string, string> = {
  ai: 'Brain', communication: 'MessageSquare', data: 'Database', devops: 'Terminal',
  file: 'File', http: 'Globe', schedule: 'Clock', trigger: 'Zap', cloud: 'Cloud',
  browser: 'Monitor', email: 'Mail', messaging: 'MessageCircle', database: 'Database',
  search: 'Search', analytics: 'BarChart2', storage: 'HardDrive', monitoring: 'Activity',
  testing: 'CheckSquare', media: 'Image', social: 'Users', crm: 'User',
  ecommerce: 'ShoppingCart', voice: 'Mic', iot: 'Radio', security: 'Shield',
  utility: 'Box', productivity: 'Briefcase', finance: 'DollarSign',
  documentation: 'BookOpen', custom: 'Box',
};

const cache = new Map<string, LucideIcon>();

/** Resolve the lucide component for a node icon name / category. */
export function resolveNodeIcon(iconName?: string, category?: string): LucideIcon {
  const key = `${iconName ?? ''}|${category ?? ''}`;
  const cached = cache.get(key);
  if (cached) return cached;

  const registry = icons as unknown as Record<string, LucideIcon>;
  let Comp: LucideIcon | undefined;

  if (iconName) Comp = registry[toPascal(iconName)];
  if (!Comp && category) Comp = registry[CATEGORY_FALLBACK[category] ?? 'Box'];
  if (!Comp) Comp = Box;

  cache.set(key, Comp);
  return Comp;
}

export function NodeIcon({
  icon,
  category,
  size = 16,
  color,
  className,
}: {
  icon?: string;
  category?: string;
  size?: number;
  color?: string;
  className?: string;
}) {
  const Comp = resolveNodeIcon(icon, category);
  return <Comp size={size} color={color} className={className} strokeWidth={2} />;
}
