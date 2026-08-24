/**
 * FileExplorer — Browse project files from the dashboard.
 *
 * Calls GET /api/v1/repos/{repoId}/tree to fetch the file tree
 * and renders it as a collapsible tree view.
 */

import { useState, useEffect } from 'react';
import { Folder, File, ChevronRight, ChevronDown, Code } from 'lucide-react';
import { apiClient } from '@/api/client';

interface FileEntry {
  name: string;
  type: 'file' | 'directory';
  path: string;
  size?: number;
  extension?: string;
  children?: FileEntry[];
}

interface FileExplorerProps {
  repoId: string;
  onFileSelect?: (path: string) => void;
}

function FileTreeNode({ entry, depth, onFileSelect }: { entry: FileEntry; depth: number; onFileSelect?: (path: string) => void }) {
  const [expanded, setExpanded] = useState(depth < 2);

  const isDir = entry.type === 'directory';
  const indent = depth * 16;

  return (
    <div>
      <button
        onClick={() => {
          if (isDir) setExpanded(!expanded);
          else onFileSelect?.(entry.path);
        }}
        className="w-full flex items-center gap-1.5 py-1 px-2 text-left hover:bg-white/[0.04] rounded transition-colors group"
        style={{ paddingLeft: `${indent + 8}px` }}
      >
        {isDir ? (
          expanded ? <ChevronDown size={12} className="text-[#6B6B6E] shrink-0" /> : <ChevronRight size={12} className="text-[#6B6B6E] shrink-0" />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        {isDir ? (
          <Folder size={14} className="text-[#FFB020] shrink-0" />
        ) : (
          <File size={14} className="text-[#6B6B6E] shrink-0" />
        )}
        <span className={`text-xs font-mono truncate ${isDir ? 'text-[#F2F1EE]' : 'text-[#A8A8AB]'}`}>
          {entry.name}
        </span>
        {!isDir && entry.size !== undefined && (
          <span className="ml-auto text-[10px] text-[#6B6B6E] font-mono opacity-0 group-hover:opacity-100">
            {entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)}KB` : `${entry.size}B`}
          </span>
        )}
      </button>
      {isDir && expanded && entry.children && (
        <div>
          {entry.children.map((child) => (
            <FileTreeNode key={child.path} entry={child} depth={depth + 1} onFileSelect={onFileSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

export function FileExplorer({ repoId, onFileSelect }: FileExplorerProps) {
  const [tree, setTree] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTree() {
      setLoading(true);
      try {
        const res = await apiClient.get<{ entries: FileEntry[]; error?: string }>(
          `/api/v1/repos/${repoId}/tree`
        );
        if (res?.error) {
          setError(res.error);
        } else if (res?.entries) {
          setTree(res.entries);
        }
      } catch (err: any) {
        setError(err?.message || 'Failed to load file tree');
      } finally {
        setLoading(false);
      }
    }
    if (repoId) loadTree();
  }, [repoId]);

  if (loading) {
    return (
      <div className="p-4 text-xs font-mono text-[#6B6B6E] animate-pulse">
        Loading file tree...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-xs font-mono text-red-400">
        {error}
      </div>
    );
  }

  return (
    <div className="bg-[#0A0A0B] border border-white/[0.08] rounded-[10px] overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.08] bg-[#101012]">
        <Code size={14} className="text-[#FFB020]" />
        <span className="text-xs font-mono font-medium text-[#F2F1EE]">File Explorer</span>
        <span className="text-[10px] font-mono text-[#6B6B6E] ml-auto">{tree.length} items</span>
      </div>
      <div className="max-h-[500px] overflow-y-auto py-1">
        {tree.length === 0 ? (
          <div className="p-4 text-center text-xs font-mono text-[#6B6B6E]">
            No files found in this repository.
          </div>
        ) : (
          tree.map((entry) => (
            <FileTreeNode key={entry.path} entry={entry} depth={0} onFileSelect={onFileSelect} />
          ))
        )}
      </div>
    </div>
  );
}
