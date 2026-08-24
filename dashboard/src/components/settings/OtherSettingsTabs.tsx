import type { SettingsTabId } from './types';
import { GeneralTab } from './tabs/GeneralTab';
import { SecurityTab } from './tabs/SecurityTab';
import { ApiKeysTab } from './tabs/ApiKeysTab';
import { SystemConfigTab } from './tabs/SystemConfigTab';
import { IntegrationsTab } from './tabs/IntegrationsTab';
import { NotificationsTab } from './tabs/NotificationsTab';
import { DataAuditTab } from './tabs/DataAuditTab';
import { DataStorageTab } from './tabs/DataStorageTab';
import { BackupRestoreTab } from './tabs/BackupRestoreTab';
import { AuditLogsTab } from './tabs/AuditLogsTab';
import { AdvancedCliToolsTab } from './tabs/AdvancedCliToolsTab';
import { AgentBudgetsBillingTab } from './tabs/AgentBudgetsBillingTab';
import { ProfileSettingsTab } from './ProfileSettingsTab';

interface OtherSettingsTabProps {
  activeTab: SettingsTabId;
  onSaveToast: (msg?: string) => void;
}

export function OtherSettingsTabs({ activeTab, onSaveToast }: OtherSettingsTabProps) {
  switch (activeTab) {
    case 'profile':
      return <ProfileSettingsTab onSaveToast={onSaveToast} />;
    case 'general':
      return <GeneralTab onSaveToast={onSaveToast} />;
    case 'security':
      return <SecurityTab onSaveToast={onSaveToast} />;
    case 'api_keys':
      return <ApiKeysTab onSaveToast={onSaveToast} />;
    case 'system_config':
      return <SystemConfigTab onSaveToast={onSaveToast} />;
    case 'integrations':
      return <IntegrationsTab onSaveToast={onSaveToast} />;
    case 'notifications':
      return <NotificationsTab onSaveToast={onSaveToast} />;
    case 'data_storage':
      return <DataStorageTab onSaveToast={onSaveToast} />;
    case 'backup':
      return <BackupRestoreTab onSaveToast={onSaveToast} />;
    case 'audit_logs':
      return <AuditLogsTab onSaveToast={onSaveToast} />;
    case 'advanced':
      return <AdvancedCliToolsTab onSaveToast={onSaveToast} />;
    case 'billing':
      return <AgentBudgetsBillingTab onSaveToast={onSaveToast} />;
    case 'appearance':
    case 'teams':
    case 'roles':
      return <DataAuditTab activeTab={activeTab} onSaveToast={onSaveToast} />;
    default:
      return <GeneralTab onSaveToast={onSaveToast} />;
  }
}
