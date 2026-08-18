import { useState } from 'react';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { Spinner } from '@/components/common/Spinner';
import { Brain, Search } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { agentsApi } from '@/api/agents';
import type { MemoryEntry } from '@/types/agent';
import type { MemoryScope } from '@/types/common';
import { formatRelativeTime } from '@/utils/time';
import { COMPANY_ID } from '@/config';

function tierColor(tier: string): string {
  switch (tier) {
    case 'hot': return 'bg-rose-100 text-rose-700';
    case 'warm': return 'bg-amber-100 text-amber-700';
    case 'cold': return 'bg-sky-100 text-sky-700';
    default: return 'bg-gray-100 text-gray-700';
  }
}

export function Memory() {
  const [search, setSearch] = useState('');
  const [scopeFilter, setScopeFilter] = useState<MemoryScope | 'all'>('all');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<MemoryEntry[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async () => {
    if (!search.trim()) return;
    setSearching(true);
    try {
      const data = await agentsApi.searchMemory(COMPANY_ID, search);
      setResults(data);
      setHasSearched(true);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const filteredResults = results.filter((entry) => {
    if (scopeFilter !== 'all' && entry.scope !== scopeFilter) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Memory</h1>
        <p className="text-sm text-gray-500 mt-1">Browse organizational knowledge and agent memories</p>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search memories..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void handleSearch(); }}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          />
        </div>
        <select
          value={scopeFilter}
          onChange={(e) => setScopeFilter(e.target.value as MemoryScope | 'all')}
          className="text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        >
          <option value="all">All Scopes</option>
          <option value="agent">Agent</option>
          <option value="team">Team</option>
          <option value="department">Department</option>
          <option value="company">Company</option>
        </select>
        <button
          onClick={() => void handleSearch()}
          disabled={!search.trim() || searching}
          className="px-4 py-2 bg-primary-500 text-white rounded-lg text-sm font-medium hover:bg-primary-600 disabled:opacity-50"
        >
          Search
        </button>
      </div>

      {searching && <Spinner size="md" className="py-8" />}

      {!searching && !hasSearched && (
        <EmptyState
          icon={<Brain size={48} />}
          title="Search organizational memory"
          description="Enter a search query to find relevant knowledge entries."
        />
      )}

      {!searching && hasSearched && filteredResults.length === 0 && (
        <EmptyState
          icon={<Brain size={48} />}
          title="No results found"
          description="Try a different search term or adjust filters."
        />
      )}

      {!searching && filteredResults.length > 0 && (
        <div className="space-y-3">
          {filteredResults.map((entry) => (
            <Card key={entry.id}>
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-900">{entry.content}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <Badge variant="default" size="sm">{entry.scope}</Badge>
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium ${tierColor(entry.tier)}`}>
                      {entry.tier}
                    </span>
                    <span className="text-xs text-gray-500">
                      Importance: {entry.importance}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatRelativeTime(entry.updated_at)}
                    </span>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
