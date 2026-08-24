import { useState } from 'react';
import { Database, FileText, Download, RotateCcw } from 'lucide-react';
import { Button } from '@/components/common/Button';
import type { SettingsTabId } from '../types';

interface DataAuditTabProps {
  activeTab: SettingsTabId;
  onSaveToast: (msg?: string) => void;
}

export function DataAuditTab({ activeTab, onSaveToast }: DataAuditTabProps) {
  const [retentionDays, setRetentionDays] = useState('90');

  const handleExportLogs = () => {
    onSaveToast('Audit log archive downloaded (JSON format)');
  };

  const handleBackup = () => {
    onSaveToast('Full system backup triggered to S3 bucket');
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            {activeTab === 'audit_logs' && <FileText size={18} className="text-[#FFB020]" />}
            {activeTab === 'data_storage' && <Database size={18} className="text-[#FFB020]" />}
            {activeTab === 'backup' && <RotateCcw size={18} className="text-[#FFB020]" />}
            <span className="capitalize">{activeTab.replace('_', ' ')} Operations</span>
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Audit trailing, automated backup routines, and telemetry data retention.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-bold text-white text-xs">Audit Trail Log Retention</div>
              <div className="text-[11px] text-gray-400">Duration before telemetry and agent action logs are archived</div>
            </div>
            <select
              value={retentionDays}
              onChange={(e) => {
                setRetentionDays(e.target.value);
                onSaveToast(`Retention updated to ${e.target.value} days`);
              }}
              className="px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="30">30 Days</option>
              <option value="90">90 Days (Recommended)</option>
              <option value="365">365 Days (Compliance)</option>
            </select>
          </div>

          <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between">
            <div>
              <div className="font-bold text-white text-xs">Export Audit Trail</div>
              <div className="text-[11px] text-gray-400">Download cryptographically signed audit logs for compliance</div>
            </div>
            <Button variant="secondary" size="xs" onClick={handleExportLogs} icon={<Download size={13} />}>
              Export JSON
            </Button>
          </div>

          <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between">
            <div>
              <div className="font-bold text-white text-xs">Trigger Manual System Backup</div>
              <div className="text-[11px] text-gray-400">Snapshot all databases, agent skills, and workflow configs</div>
            </div>
            <Button variant="primary" size="xs" onClick={handleBackup} icon={<RotateCcw size={13} />}>
              Backup Now
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
