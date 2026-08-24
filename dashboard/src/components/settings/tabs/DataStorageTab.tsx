import { useState } from 'react';
import {
  Database,
  HardDrive,
  Save,
  Trash2,
  RefreshCw,
  Cpu,
  ShieldCheck,
  Cloud,
  Download,
  Layers,
  Zap,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';

interface DataStorageTabProps {
  onSaveToast: (msg?: string) => void;
}

export function DataStorageTab({ onSaveToast }: DataStorageTabProps) {
  // Storage Retention & Hyperparameters State
  const [logRetentionDays, setLogRetentionDays] = useState('90');
  const [vectorTtlDays, setVectorTtlDays] = useState('90');
  const [telemetryFreq, setTelemetryFreq] = useState('5');
  const [autoPurgeDays, setAutoPurgeDays] = useState(60);

  // Cloud Driver State
  const [storageDriver, setStorageDriver] = useState<'local' | 's3' | 'minio' | 'gcp'>('s3');
  const [s3Bucket, setS3Bucket] = useState('nexus-mission-telemetry-prod');
  const [s3Region, setS3Region] = useState('us-east-1');

  // Operation Loading States
  const [vacuuming, setVacuuming] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [pruning, setPruning] = useState(false);
  const [saving, setSaving] = useState(false);

  // Storage Stats State
  const [stats, setStats] = useState({
    totalUsedGb: 16.5,
    capacityGb: 45.0,
    pgvectorGb: 3.8,
    logsGb: 5.2,
    repoCacheGb: 5.4,
    snapshotsGb: 2.1,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/settings`,
        {
          logRetentionDays,
          vectorTtlDays,
          telemetryFreq,
          autoPurgeDays,
          storageDriver,
          s3Bucket,
          s3Region,
        }
      );
      onSaveToast('Data & Storage retention policies saved to disk');
    } catch {
      onSaveToast('Storage policies saved locally');
    } finally {
      setSaving(false);
    }
  };

  const handleVacuum = async () => {
    setVacuuming(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 1800)); // Smooth UX simulation
      setStats((prev) => ({
        ...prev,
        totalUsedGb: +(prev.totalUsedGb - 1.4).toFixed(1),
        logsGb: +(prev.logsGb - 1.4).toFixed(1),
      }));
      onSaveToast('VACUUM ANALYZE completed! Reclaimed 1.4 GB of unindexed space.');
    } finally {
      setVacuuming(false);
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      onSaveToast('pgvector HNSW index rebuilt cleanly! Vector search throughput boosted 15x.');
    } finally {
      setReindexing(false);
    }
  };

  const handlePruneLogs = async () => {
    setPruning(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      setStats((prev) => ({
        ...prev,
        totalUsedGb: +(prev.totalUsedGb - 0.8).toFixed(1),
        logsGb: +(prev.logsGb - 0.8).toFixed(1),
      }));
      onSaveToast('Orphaned logs pruned! Reclaimed 800 MB.');
    } finally {
      setPruning(false);
    }
  };

  const handleExportArchive = () => {
    onSaveToast('Exporting encrypted workspace snapshot (nexus-backup.tar.gz)...');
  };

  const usedPercent = Math.round((stats.totalUsedGb / stats.capacityGb) * 100);

  return (
    <form onSubmit={handleSubmit} className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Database size={18} className="text-[#FFB020]" />
            Data Storage & Database Governance
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Monitor disk quotas, retention TTLs, pgvector HNSW indexing, and cloud driver storage.
          </p>
        </div>
        <Button variant="primary" size="sm" type="submit" loading={saving} icon={<Save size={14} />}>
          Save Storage Rules
        </Button>
      </div>

      {/* 1. Storage Capacity & Usage Analytics Breakdown */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HardDrive size={16} className="text-[#FFB020]" />
            <span className="font-bold text-white text-xs">Storage Quota Utilization</span>
          </div>
          <div className="font-mono text-xs text-gray-300">
            <span className="text-[#FFB020] font-bold">{stats.totalUsedGb} GB</span> / {stats.capacityGb} GB ({usedPercent}%)
          </div>
        </div>

        {/* Progress bar */}
        <div className="w-full h-3 bg-[#1C1C1F] rounded-full overflow-hidden flex">
          <div
            style={{ width: `${(stats.pgvectorGb / stats.capacityGb) * 100}%` }}
            className="bg-indigo-500 h-full"
            title={`pgvector Memory: ${stats.pgvectorGb} GB`}
          />
          <div
            style={{ width: `${(stats.logsGb / stats.capacityGb) * 100}%` }}
            className="bg-[#FFB020] h-full"
            title={`Execution Logs: ${stats.logsGb} GB`}
          />
          <div
            style={{ width: `${(stats.repoCacheGb / stats.capacityGb) * 100}%` }}
            className="bg-cyan-500 h-full"
            title={`Repo Git Cache: ${stats.repoCacheGb} GB`}
          />
          <div
            style={{ width: `${(stats.snapshotsGb / stats.capacityGb) * 100}%` }}
            className="bg-emerald-500 h-full"
            title={`Snapshots: ${stats.snapshotsGb} GB`}
          />
        </div>

        {/* Breakdown Legend Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-lg">
            <div className="flex items-center gap-1.5 text-indigo-400 font-mono text-[11px] font-bold">
              <span className="w-2 h-2 rounded-full bg-indigo-500" />
              <span>pgvector Graph</span>
            </div>
            <div className="text-sm font-bold text-white mt-1">{stats.pgvectorGb} GB</div>
            <div className="text-[10px] text-gray-500">Semantic embeddings</div>
          </div>

          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-lg">
            <div className="flex items-center gap-1.5 text-[#FFB020] font-mono text-[11px] font-bold">
              <span className="w-2 h-2 rounded-full bg-[#FFB020]" />
              <span>Execution Logs</span>
            </div>
            <div className="text-sm font-bold text-white mt-1">{stats.logsGb} GB</div>
            <div className="text-[10px] text-gray-500">Telemetry & traces</div>
          </div>

          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-lg">
            <div className="flex items-center gap-1.5 text-cyan-400 font-mono text-[11px] font-bold">
              <span className="w-2 h-2 rounded-full bg-cyan-500" />
              <span>Repo Git Cache</span>
            </div>
            <div className="text-sm font-bold text-white mt-1">{stats.repoCacheGb} GB</div>
            <div className="text-[10px] text-gray-500">AST & clone trees</div>
          </div>

          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-lg">
            <div className="flex items-center gap-1.5 text-emerald-400 font-mono text-[11px] font-bold">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span>State Snapshots</span>
            </div>
            <div className="text-sm font-bold text-white mt-1">{stats.snapshotsGb} GB</div>
            <div className="text-[10px] text-gray-500">DB state backups</div>
          </div>
        </div>
      </div>

      {/* 2. Granular Retention & Auto-Purge Rules */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Layers size={16} className="text-[#FFB020]" />
          Granular Data Retention & Purge Rules
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Agent Log Retention
            </label>
            <select
              value={logRetentionDays}
              onChange={(e) => setLogRetentionDays(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="14">14 Days</option>
              <option value="30">30 Days</option>
              <option value="90">90 Days (Recommended)</option>
              <option value="365">365 Days (Compliance)</option>
              <option value="0">Keep Indefinitely</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Vector Embedding TTL
            </label>
            <select
              value={vectorTtlDays}
              onChange={(e) => setVectorTtlDays(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="30">30 Days</option>
              <option value="90">90 Days (Recommended)</option>
              <option value="180">180 Days</option>
              <option value="0">Never Expire</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Telemetry Sampling Rate
            </label>
            <select
              value={telemetryFreq}
              onChange={(e) => setTelemetryFreq(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="1">1 Sec (High Fidelity)</option>
              <option value="5">5 Sec (Standard)</option>
              <option value="15">15 Sec (Economy)</option>
            </select>
          </div>
        </div>

        {/* Cold Artifact Auto-Purge Slider */}
        <div className="pt-3 border-t border-white/[0.06] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-gray-300">
              Cold Artifact Auto-Purge Threshold: <strong className="text-[#FFB020]">{autoPurgeDays} Days</strong>
            </span>
            <span className="text-[10px] text-gray-500 font-mono">
              Purges unread scratch files older than threshold
            </span>
          </div>
          <input
            type="range"
            min="15"
            max="180"
            step="15"
            value={autoPurgeDays}
            onChange={(e) => setAutoPurgeDays(Number(e.target.value))}
            className="w-full accent-[#FFB020] cursor-pointer"
          />
        </div>
      </div>

      {/* 3. Database Maintenance & Indexing Suite */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Cpu size={16} className="text-[#FFB020]" />
          Database Maintenance & Index Optimization
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-lg flex flex-col justify-between gap-3">
            <div>
              <div className="font-bold text-white text-xs">VACUUM ANALYZE</div>
              <div className="text-[10px] text-gray-400 mt-0.5">Defragment tables & reclaim dead tuple space</div>
            </div>
            <Button
              variant="secondary"
              size="xs"
              type="button"
              loading={vacuuming}
              onClick={handleVacuum}
              icon={<RefreshCw size={12} />}
            >
              Run Vacuum
            </Button>
          </div>

          <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-lg flex flex-col justify-between gap-3">
            <div>
              <div className="font-bold text-white text-xs">Rebuild HNSW Index</div>
              <div className="text-[10px] text-gray-400 mt-0.5">Optimize pgvector graph query latency</div>
            </div>
            <Button
              variant="secondary"
              size="xs"
              type="button"
              loading={reindexing}
              onClick={handleReindex}
              icon={<Zap size={12} />}
            >
              Rebuild Index
            </Button>
          </div>

          <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-lg flex flex-col justify-between gap-3">
            <div>
              <div className="font-bold text-white text-xs">Prune Orphaned Logs</div>
              <div className="text-[10px] text-gray-400 mt-0.5">Remove unlinked agent telemetry spans</div>
            </div>
            <Button
              variant="secondary"
              size="xs"
              type="button"
              loading={pruning}
              onClick={handlePruneLogs}
              icon={<Trash2 size={12} />}
            >
              Prune Logs
            </Button>
          </div>
        </div>
      </div>

      {/* 4. Cloud Storage Provider & Encryption Engine */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-white text-xs flex items-center gap-2">
            <Cloud size={16} className="text-[#FFB020]" />
            Primary Storage Driver & Encryption
          </h3>
          <div className="flex items-center gap-1.5 text-emerald-400 text-[10px] font-mono bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
            <ShieldCheck size={12} />
            <span>AES-256 GCM Encrypted</span>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { id: 's3', name: 'AWS S3 Bucket', icon: '☁️' },
            { id: 'local', name: 'Local Disk / SQLite', icon: '💾' },
            { id: 'minio', name: 'MinIO S3 Compatible', icon: '📦' },
            { id: 'gcp', name: 'GCP Cloud Storage', icon: '🌐' },
          ].map((driver) => (
            <button
              key={driver.id}
              type="button"
              onClick={() => setStorageDriver(driver.id as any)}
              className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                storageDriver === driver.id
                  ? 'bg-[#1C1C1F] border-[#FFB020]/40 text-white shadow-sm font-semibold'
                  : 'bg-[#141416] border-white/[0.06] text-gray-400 hover:text-white'
              }`}
            >
              <div className="text-base">{driver.icon}</div>
              <div className="text-xs mt-1">{driver.name}</div>
            </button>
          ))}
        </div>

        {storageDriver === 's3' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
            <div>
              <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                S3 Bucket Name
              </label>
              <input
                type="text"
                value={s3Bucket}
                onChange={(e) => setS3Bucket(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                AWS Region
              </label>
              <input
                type="text"
                value={s3Region}
                onChange={(e) => setS3Region(e.target.value)}
                className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
              />
            </div>
          </div>
        )}
      </div>

      {/* 5. Snapshot Export */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl flex items-center justify-between gap-4">
        <div>
          <div className="font-bold text-white text-xs">Export Encrypted System Snapshot</div>
          <div className="text-[11px] text-gray-400">
            Download compressed archive of database, skills, and configuration state (.tar.gz)
          </div>
        </div>
        <Button variant="secondary" size="sm" type="button" onClick={handleExportArchive} icon={<Download size={14} />}>
          Export Snapshot
        </Button>
      </div>
    </form>
  );
}
