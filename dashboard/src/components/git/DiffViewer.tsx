/**
 * DiffViewer — Displays git diff output with syntax highlighting.
 *
 * Calls GET /api/v1/repos/{repoId}/diff to fetch diff between two refs
 * and renders it with colored additions/deletions.
 */

import { useState, useEffect } from 'react';
import { GitCompare, Copy, Check } from 'lucide-react';
import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';

interface DiffViewerProps {
  repoId: string;
  base?: string;
  target?: string;
}

interface DiffData {
  repo_id: string;
  base: string;
  target: string;
  stat: string;
  diff: string;
  truncated: boolean;
  error?: string;
}

export function DiffViewer({ repoId, base = 'HEAD~1', target = 'HEAD' }: DiffViewerProps) {
  const [data, setData] = useState<DiffData | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    async function loadDiff() {
      setLoading(true);
      try {
        const res = await apiClient.get<DiffData>(
          `/api/v1/repos/${repoId}/diff`,
          { base, target }
        );
        setData(res);
      } catch {
        setData({ repo_id: repoId, base, target, stat: '', diff: '', truncated: false, error: 'Failed to load diff' });
      } finally {
        setLoading(false);
      }
    }
    if (repoId) loadDiff();
  }, [repoId, base, target]);

  const handleCopy = () => {
    if (data?.diff) {
      navigator.clipboard.writeText(data.diff);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) {
    return <div className="p-4 text-xs font-mono text-[#6B6B6E] animate-pulse">Loading diff...</div>;
  }

  if (data?.error) {
    return <div className="p-4 text-xs font-mono text-red-400">{data.error}</div>;
  }

  const diffLines = (data?.diff || '').split('\n');

  return (
    <div className="bg-[#0A0A0B] border border-white/[0.08] rounded-[10px] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.08] bg-[#101012]">
        <div className="flex items-center gap-2">
          <GitCompare size={14} className="text-[#FFB020]" />
          <span className="text-xs font-mono font-medium text-[#F2F1EE]">
            {base} → {target}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {data?.truncated && (
            <span className="text-[10px] font-mono text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded">Truncated</span>
          )}
          <Button variant="secondary" size="sm" icon={copied ? <Check size={12} /> : <Copy size={12} />} onClick={handleCopy}>
            {copied ? 'Copied' : 'Copy'}
          </Button>
        </div>
      </div>

      {/* Stat summary */}
      {data?.stat && (
        <div className="px-3 py-2 border-b border-white/[0.06] bg-[#0D0D0F]">
          <pre className="text-[11px] font-mono text-[#A8A8AB] whitespace-pre-wrap">{data.stat}</pre>
        </div>
      )}

      {/* Diff content */}
      <div className="max-h-[600px] overflow-y-auto">
        <pre className="text-[11px] font-mono leading-relaxed">
          {diffLines.map((line, i) => {
            let bg = '';
            let textColor = 'text-[#A8A8AB]';
            if (line.startsWith('+') && !line.startsWith('+++')) {
              bg = 'bg-green-500/5';
              textColor = 'text-green-400';
            } else if (line.startsWith('-') && !line.startsWith('---')) {
              bg = 'bg-red-500/5';
              textColor = 'text-red-400';
            } else if (line.startsWith('@@')) {
              bg = 'bg-blue-500/5';
              textColor = 'text-blue-400';
            } else if (line.startsWith('diff ') || line.startsWith('index ')) {
              textColor = 'text-[#6B6B6E]';
            }
            return (
              <div key={i} className={`px-3 py-0 ${bg}`}>
                <span className={textColor}>{line}</span>
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
