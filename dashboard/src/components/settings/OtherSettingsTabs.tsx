import { ProfileSettingsTab } from './ProfileSettingsTab';
import { AdvancedCliToolsTab } from './tabs/AdvancedCliToolsTab';
import { AgentBudgetsBillingTab } from './tabs/AgentBudgetsBillingTab';
import { ApiKeysTab } from './tabs/ApiKeysTab';
import { AuditLogsTab } from './tabs/AuditLogsTab';
import { BackupRestoreTab } from './tabs/BackupRestoreTab';
import { DataAuditTab } from './tabs/DataAuditTab';
import { DataStorageTab } from './tabs/DataStorageTab';
import { GeneralTab } from './tabs/GeneralTab';
import { IntegrationsTab } from './tabs/IntegrationsTab';
import { NotificationsTab } from './tabs/NotificationsTab';
import { SecretsVaultTab } from './tabs/SecretsVaultTab';
import { SecurityTab } from './tabs/SecurityTab';
import { SystemConfigTab } from './tabs/SystemConfigTab';
import { ThemeTab } from './tabs/ThemeTab';
import type { SettingsTabId } from './types';

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
    case 'secrets':
      return <SecretsVaultTab onSaveToast={onSaveToast} />;
    case 'advanced':
      return <AdvancedCliToolsTab onSaveToast={onSaveToast} />;
    case 'billing':
      return <AgentBudgetsBillingTab onSaveToast={onSaveToast} />;
    case 'appearance':
      return <ThemeTab onSaveToast={onSaveToast} />;
    case 'teams':
    case 'roles':
      return <DataAuditTab activeTab={activeTab} onSaveToast={onSaveToast} />;
    default:
      return <GeneralTab onSaveToast={onSaveToast} />;
  }
}
