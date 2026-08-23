import { useState, type ReactNode } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';

export interface Column<T> {
  key: string;
  header: string;
  render?: (item: T, index: number) => ReactNode;
  sortable?: boolean;
  className?: string;
  align?: 'left' | 'center' | 'right';
}

export interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (item: T, index: number) => string | number;
  onRowClick?: (item: T) => void;
  emptyText?: string;
  className?: string;
}

export function Table<T>({
  columns,
  data,
  keyExtractor,
  onRowClick,
  emptyText = 'No records found',
  className = '',
}: TableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDirection('asc');
    }
  };

  const sortedData = [...data].sort((a, b) => {
    if (!sortKey) return 0;
    const aVal = (a as Record<string, unknown>)[sortKey];
    const bVal = (b as Record<string, unknown>)[sortKey];

    if (aVal === bVal) return 0;
    if (aVal === null || aVal === undefined) return 1;
    if (bVal === null || bVal === undefined) return -1;

    const comparison = aVal < bVal ? -1 : 1;
    return sortDirection === 'asc' ? comparison : -comparison;
  });

  return (
    <div className={`w-full overflow-hidden ${className}`}>
      {/* Desktop Table View (≥768px) */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-left text-sm border-collapse" role="grid">
          <thead>
            <tr className="border-b border-white/[0.08] text-xs font-mono text-[#6B6B6E] tracking-wider uppercase bg-[#101012]">
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={`px-4 py-3 font-medium select-none ${
                    column.sortable ? 'cursor-pointer hover:text-[#F2F1EE]' : ''
                  } ${column.className || ''}`}
                  onClick={() => column.sortable && handleSort(column.key)}
                >
                  <div
                    className={`inline-flex items-center gap-1.5 ${
                      column.align === 'right' ? 'justify-end w-full' : column.align === 'center' ? 'justify-center w-full' : ''
                    }`}
                  >
                    <span>{column.header}</span>
                    {column.sortable && sortKey === column.key && (
                      <span className="text-[#FFB020]">
                        {sortDirection === 'asc' ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      </span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {sortedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-6 py-12 text-center text-[#6B6B6E] font-mono text-xs">
                  {emptyText}
                </td>
              </tr>
            ) : (
              sortedData.map((item, index) => {
                const isFocused = focusedIndex === index;
                return (
                  <tr
                    key={keyExtractor(item, index)}
                    tabIndex={onRowClick ? 0 : undefined}
                    onFocus={() => setFocusedIndex(index)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && onRowClick) onRowClick(item);
                    }}
                    onClick={() => onRowClick && onRowClick(item)}
                    className={`transition-colors border-b border-white/[0.04] ${
                      onRowClick ? 'cursor-pointer hover:bg-white/[0.02]' : 'hover:bg-white/[0.01]'
                    } ${isFocused ? 'bg-white/[0.03] outline-none ring-1 ring-[#FFB020]/40' : ''}`}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={`px-4 py-3 text-sm text-[#F2F1EE] ${
                          column.align === 'right' ? 'text-right' : column.align === 'center' ? 'text-center' : ''
                        } ${column.className || ''}`}
                      >
                        {column.render
                          ? column.render(item, index)
                          : String((item as Record<string, unknown>)[column.key] ?? '—')}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile Stacked Card View (<768px) */}
      <div className="md:hidden space-y-2.5">
        {sortedData.length === 0 ? (
          <div className="p-6 text-center text-[#6B6B6E] font-mono text-xs bg-[#141416] border border-white/[0.08] rounded-[6px]">
            {emptyText}
          </div>
        ) : (
          sortedData.map((item, index) => (
            <div
              key={keyExtractor(item, index)}
              onClick={() => onRowClick && onRowClick(item)}
              className={`p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2.5 ${
                onRowClick ? 'cursor-pointer active:bg-white/[0.04]' : ''
              }`}
            >
              {columns.map((column) => (
                <div key={column.key} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-[#6B6B6E] font-mono uppercase text-[11px]">{column.header}</span>
                  <div className="text-right text-[#F2F1EE] font-sans">
                    {column.render
                      ? column.render(item, index)
                      : String((item as Record<string, unknown>)[column.key] ?? '—')}
                  </div>
                </div>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
