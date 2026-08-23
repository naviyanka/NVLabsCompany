export const LANGUAGE_COLORS: Record<string, string> = {
  TypeScript: '#3178C6',
  JavaScript: '#F7DF1E',
  Rust: '#DEA584',
  Go: '#00ADD8',
  Python: '#3572A5',
  HCL: '#844FBA',
  Solidity: '#AA6746',
  C: '#555555',
  'C++': '#F34B7D',
  Java: '#B07219',
};

export function getLanguageColor(lang: string): string {
  return LANGUAGE_COLORS[lang] || '#A8A8AB';
}

export function formatTimeAgo(isoString: string): string {
  try {
    const diff = Date.now() - new Date(isoString).getTime();
    if (isNaN(diff) || diff < 0) return 'Just now';
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return 'Recently';
  }
}
