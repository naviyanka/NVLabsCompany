/**
 * CompanyPortabilitySection — export the current company to a portable archive
 * and import an archive into a fresh company.
 *
 * Wraps GET /api/v1/companies/{id}/export and POST /api/v1/companies/import
 * (CompanyPortabilityService). Export downloads a secret-scrubbed JSON archive;
 * import clones it into a new company with remapped IDs.
 */

import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { getActiveCompanyId } from '@/config';
import { Download, PackageOpen, Upload } from 'lucide-react';
import { useRef, useState } from 'react';

interface ExportManifest {
  archive_version?: number;
  company_name?: string;
  row_counts?: Record<string, number>;
  scrubbed?: Record<string, number>;
}

export function CompanyPortabilitySection({ onSaveToast }: { onSaveToast: (msg?: string) => void }) {
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importName, setImportName] = useState('');
  const [lastScrub, setLastScrub] = useState<{ tables: number; scrubbed: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleExport = async () => {
    setExporting(true);
    try {
      const archive = await apiClient.get<{ manifest: ExportManifest; tables: Record<string, unknown[]> }>(
        `/api/v1/companies/${getActiveCompanyId()}/export`,
      );
      const manifest = archive.manifest || {};
      const scrubCount = Object.values(manifest.scrubbed || {}).reduce((a, b) => a + b, 0);
      setLastScrub({ tables: Object.keys(archive.tables || {}).length, scrubbed: scrubCount });

      // Download as a JSON file.
      const blob = new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const safeName = (manifest.company_name || 'company').replace(/[^a-z0-9]+/gi, '_').toLowerCase();
      a.download = `${safeName}_export_${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      onSaveToast(`Exported ${Object.keys(archive.tables || {}).length} tables; ${scrubCount} secret values scrubbed.`);
    } catch (err) {
      console.error('Company export failed', err);
      onSaveToast('Company export failed.');
    } finally {
      setExporting(false);
    }
  };

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow re-selecting the same file
    if (!file) return;

    setImporting(true);
    try {
      const text = await file.text();
      const archive = JSON.parse(text);
      const res = await apiClient.post<{ company_id: string; new_name?: string }>(
        `/api/v1/companies/import`,
        { archive, new_name: importName.trim() || undefined },
      );
      onSaveToast(`Imported into new company "${res.new_name}" (${res.company_id.slice(0, 8)}…).`);
    } catch (err: any) {
      console.error('Company import failed', err);
      const detail = err?.detail || err?.message || '';
      onSaveToast(detail ? `Import failed: ${detail}` : 'Company import failed — check the archive is a valid export JSON.');
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
      <div className="flex items-center gap-2">
        <PackageOpen size={16} className="text-[#FFB020]" />
        <h3 className="font-bold text-white text-xs uppercase tracking-wider">Company Portability</h3>
      </div>
      <p className="text-[11px] text-[#A8A8AB] leading-relaxed">
        Export this company's full graph as a portable JSON archive. Secret material is
        scrubbed on the way out. Import clones an archive into a brand-new company with fresh
        IDs — it never overwrites the current one.
      </p>

      <div className="flex flex-col sm:flex-row gap-3">
        {/* Export */}
        <Button variant="secondary" size="sm" loading={exporting} icon={<Download size={14} />} onClick={handleExport}>
          Export This Company
        </Button>

        {/* Import */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={importName}
            onChange={(e) => setImportName(e.target.value)}
            placeholder="New company name (optional)"
            className="px-3 py-1.5 bg-[#0C0C0E] border border-white/[0.1] rounded text-white text-xs focus:outline-none focus:border-[#FFB020] w-56"
          />
          <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={handleImportFile} />
          <Button
            variant="secondary"
            size="sm"
            loading={importing}
            icon={<Upload size={14} />}
            onClick={() => fileRef.current?.click()}
          >
            Import Archive
          </Button>
        </div>
      </div>

      {lastScrub && (
        <div className="text-[10px] font-mono text-emerald-400">
          Last export: {lastScrub.tables} tables · {lastScrub.scrubbed} secret values scrubbed.
        </div>
      )}
    </div>
  );
}
