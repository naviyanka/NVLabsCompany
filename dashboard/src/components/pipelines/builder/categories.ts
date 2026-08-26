/**
 * Category → visual mapping shared by the reactflow builder.
 * Colors and glyphs for the 29 node categories exposed by GET /api/v1/nodes,
 * plus resolution of a category to a visual "kind" (which node component renders it).
 */

export const CATEGORY_COLORS: Record<string, string> = {
  ai: '#A855F7', communication: '#3B82F6', data: '#10B981', devops: '#F97316',
  file: '#64748B', http: '#06B6D4', schedule: '#F59E0B', trigger: '#EF4444',
  cloud: '#0EA5E9', browser: '#6366F1', email: '#EC4899', messaging: '#8B5CF6',
  database: '#14B8A6', search: '#EAB308', analytics: '#84CC16', storage: '#78716C',
  monitoring: '#F43F5E', testing: '#D946EF', media: '#EC4899', social: '#3B82F6',
  crm: '#22C55E', ecommerce: '#F59E0B', voice: '#6366F1', iot: '#06B6D4',
  security: '#EF4444', utility: '#6B7280', productivity: '#10B981', finance: '#22C55E',
  documentation: '#38BDF8', custom: '#71717A',
};

export const CATEGORY_ICONS: Record<string, string> = {
  ai: '🧠', communication: '💬', data: '📊', devops: '🔧', file: '📄', http: '🌐',
  schedule: '⏰', trigger: '⚡', cloud: '☁️', browser: '🖥️', email: '📧', messaging: '💬',
  database: '🗄️', search: '🔍', analytics: '📈', storage: '💾', monitoring: '📡',
  testing: '🧪', media: '🎬', social: '👥', crm: '👤', ecommerce: '🛒', voice: '🎙️',
  iot: '📡', security: '🛡️', utility: '🔨', productivity: '⚡', finance: '💰',
  documentation: '📚', custom: '⬡',
};

export function categoryColor(category?: string): string {
  return (category && CATEGORY_COLORS[category]) || '#FFB020';
}

export function categoryIcon(category?: string): string {
  return (category && CATEGORY_ICONS[category]) || '⬡';
}

/** Visual node kind → which custom reactflow component renders the node. */
export type NodeKind = 'trigger' | 'agent' | 'action';

/**
 * Resolve a node category to a visual kind, mirroring OpenCompany's
 * COMPONENT_BY_KIND fallback (trigger-ish → trigger, ai → agent, else action).
 */
export function kindForCategory(category?: string): NodeKind {
  if (!category) return 'action';
  if (category === 'trigger' || category === 'schedule') return 'trigger';
  if (category === 'ai') return 'agent';
  return 'action';
}
