/**
 * ManifestImport — Import an agent from a portable HireManifest JSON file.
 * Supports file drop, paste, and validation preview before deployment.
 */

import { useState, useCallback } from 'react';
import { Button } from '@/components/common/Button';
import { hireFromManifest } from '@/api/agents';
import {
  Upload,
  FileJson,
  CheckCircle2,
  AlertTriangle,
  Rocket,
  ClipboardPaste,
  X,
} from 'lucide-react';

interface ManifestImportProps {
  onSuccess: () => void;
  onCancel: () => void;
}

interface ParsedManifest {
  spec?: string;
  name?: string;
  description?: string;
  goal?: string;
  provider?: string;
  model?: string;
  command_flags?: string[];
  capabilities?: string[];
  isolate?: boolean;
  token_cap?: number;
  author?: string;
  homepage?: string;
  [key: string]: unknown;
}

export function ManifestImport({ onSuccess, onCancel }: ManifestImportProps) {
  const [rawJson, setRawJson] = useState('');
  const [parsed, setParsed] = useState<ParsedManifest | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const parseManifest = useCallback((text: string) => {
    setRawJson(text);
    setParseError(null);
    setParsed(null);

    if (!text.trim()) return;

    try {
      const data = JSON.parse(text);
      if (typeof data !== 'object' || data === null || Array.isArray(data)) {
        setParseError('Manifest must be a JSON object');
        return;
      }
      if (!data.name) {
        setParseError('Manifest must have a "name" field');
        return;
      }
      if (data.spec && !data.spec.startsWith('nexus/hire@')) {
        setParseError(`Unknown spec format: "${data.spec}". Expected "nexus/hire@1"`);
        return;
      }
      setParsed(data as ParsedManifest);
    } catch (e: any) {
      setParseError(`Invalid JSON: ${e.message}`);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);

      const file = e.dataTransfer.files[0];
      if (!file) return;

      if (!file.name.endsWith('.json')) {
        setParseError('Please drop a .json file');
        return;
      }

      const reader = new FileReader();
      reader.onload = (ev) => {
        const text = ev.target?.result as string;
        parseManifest(text);
      };
      reader.readAsText(file);
    },
    [parseManifest]
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (ev) => {
        const text = ev.target?.result as string;
        parseManifest(text);
      };
      reader.readAsText(file);
    },
    [parseManifest]
  );

  const handlePaste = useCallback(() => {
    navigator.clipboard.readText().then((text) => {
      parseManifest(text);
    }).catch(() => {
      setParseError('Could not read clipboard. Try pasting into the text area instead.');
    });
  }, [parseManifest]);

  const handleDeploy = async () => {
    if (!parsed) return;
    setDeploying(true);
    setDeployError(null);

    try {
      const response = await hireFromManifest({
        manifest: parsed as Record<string, unknown>,
      });
      setResult(response);
    } catch (err: any) {
      const detail = err?.detail;
      if (detail && typeof detail === 'object' && detail.errors) {
        setDeployError(`Validation failed: ${(detail.errors as string[]).join(', ')}`);
      } else {
        setDeployError(err?.message || 'Deployment failed');
      }
    } finally {
      setDeploying(false);
    }
  };

  // Success state
  if (result) {
    return (
      <div className="space-y-4 text-center py-4">
        <div className="w-12 h-12 mx-auto rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
          <CheckCircle2 size={24} className="text-emerald-400" />
        </div>
        <div>
          <h3 className="text-sm font-medium text-[#F2F1EE]">Agent Deployed from Manifest</h3>
          <p className="text-xs text-[#6B6B6E] font-mono mt-1">
            {(result as any).name} ({(result as any).role}) — {(result as any).provider || 'default'} provider
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={onSuccess}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-[#9C9C9F] font-mono">
        Import a portable agent configuration from a <code className="text-[#FFB020]">nexus/hire@1</code> manifest file.
        Drop a JSON file, paste from clipboard, or type directly.
      </p>

      {/* Drop Zone */}
      {!parsed && (
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          className={`relative p-6 border-2 border-dashed rounded-[10px] text-center transition-all ${
            isDragOver
              ? 'border-[#FFB020] bg-[#FFB020]/5'
              : 'border-white/[0.12] hover:border-white/[0.2]'
          }`}
        >
          <Upload className={`w-8 h-8 mx-auto mb-2 ${isDragOver ? 'text-[#FFB020]' : 'text-gray-500'}`} />
          <p className="text-xs font-mono text-[#A8A8AB]">
            {isDragOver ? 'Drop manifest here...' : 'Drop a .json manifest file here'}
          </p>
          <div className="flex items-center justify-center gap-3 mt-3">
            <label className="px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[10px] font-mono text-[#A8A8AB] hover:text-[#FFB020] hover:border-[#FFB020]/30 transition-colors cursor-pointer">
              <input type="file" accept=".json" onChange={handleFileSelect} className="hidden" />
              Browse files
            </label>
            <button
              type="button"
              onClick={handlePaste}
              className="px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-[6px] text-[10px] font-mono text-[#A8A8AB] hover:text-[#FFB020] hover:border-[#FFB020]/30 transition-colors cursor-pointer flex items-center gap-1.5"
            >
              <ClipboardPaste size={11} />
              Paste from clipboard
            </button>
          </div>
        </div>
      )}

      {/* JSON Editor (always available for manual editing) */}
      {!parsed && (
        <div>
          <label className="block text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">
            Or paste/edit JSON directly:
          </label>
          <textarea
            value={rawJson}
            onChange={(e) => parseManifest(e.target.value)}
            placeholder={'{\n  "spec": "nexus/hire@1",\n  "name": "My Agent",\n  "provider": "claude",\n  "model": "claude-sonnet-4-20250514",\n  "capabilities": ["api-design", "testing"],\n  "goal": "Build reliable backend services"\n}'}
            rows={8}
            className="w-full px-3 py-2 bg-[#0A0A0C] border border-white/[0.12] rounded-[8px] text-[11px] font-mono text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] leading-relaxed"
          />
        </div>
      )}

      {/* Parse Error */}
      {parseError && (
        <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-[6px] text-xs text-red-400 font-mono flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0" />
          {parseError}
        </div>
      )}

      {/* Parsed Preview */}
      {parsed && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileJson size={14} className="text-[#FFB020]" />
              <span className="text-xs font-medium text-[#F2F1EE]">Manifest Validated</span>
            </div>
            <button
              type="button"
              onClick={() => { setParsed(null); setRawJson(''); }}
              className="text-[10px] font-mono text-[#6B6B6E] hover:text-red-400 cursor-pointer flex items-center gap-1"
            >
              <X size={10} />
              Clear
            </button>
          </div>

          <div className="p-3 bg-[#101012] border border-white/[0.08] rounded-[8px] space-y-2">
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div>
                <span className="text-[#6B6B6E]">Name:</span>{' '}
                <span className="text-[#F2F1EE]">{parsed.name}</span>
              </div>
              {parsed.provider && (
                <div>
                  <span className="text-[#6B6B6E]">Provider:</span>{' '}
                  <span className="text-[#FFB020]">{parsed.provider}</span>
                </div>
              )}
              {parsed.model && (
                <div>
                  <span className="text-[#6B6B6E]">Model:</span>{' '}
                  <span className="text-cyan-400">{parsed.model}</span>
                </div>
              )}
              {parsed.spec && (
                <div>
                  <span className="text-[#6B6B6E]">Spec:</span>{' '}
                  <span className="text-emerald-400">{parsed.spec}</span>
                </div>
              )}
            </div>

            {parsed.description && (
              <p className="text-[11px] text-[#9C9C9F] border-t border-white/[0.06] pt-2">
                {parsed.description}
              </p>
            )}

            {parsed.capabilities && parsed.capabilities.length > 0 && (
              <div className="flex flex-wrap gap-1 border-t border-white/[0.06] pt-2">
                {parsed.capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="px-1.5 py-0.5 text-[9px] font-mono text-[#A8A8AB] bg-[#141416] border border-white/[0.06] rounded"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            )}

            {parsed.goal && (
              <div className="border-t border-white/[0.06] pt-2">
                <span className="text-[9px] font-mono text-[#6B6B6E] uppercase">Goal: </span>
                <span className="text-[11px] text-[#A8A8AB]">{parsed.goal}</span>
              </div>
            )}

            {parsed.token_cap && (
              <div className="text-[10px] font-mono text-[#6B6B6E]">
                Token cap: {parsed.token_cap.toLocaleString()}
              </div>
            )}
          </div>

          {/* Deploy Error */}
          {deployError && (
            <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-[6px] text-xs text-red-400 font-mono flex items-center gap-2">
              <AlertTriangle size={14} className="shrink-0" />
              {deployError}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex justify-end gap-2 pt-3 border-t border-white/[0.08]">
        <Button variant="secondary" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        {parsed && (
          <Button
            variant="primary"
            size="sm"
            onClick={handleDeploy}
            loading={deploying}
            icon={<Rocket size={13} />}
          >
            Deploy from Manifest
          </Button>
        )}
      </div>
    </div>
  );
}
