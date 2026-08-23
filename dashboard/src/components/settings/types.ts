export type SettingsTabId =
  | 'general'
  | 'profile'
  | 'security'
  | 'api_keys'
  | 'integrations'
  | 'teams'
  | 'roles'
  | 'billing'
  | 'system_config'
  | 'notifications'
  | 'data_storage'
  | 'backup'
  | 'audit_logs'
  | 'appearance'
  | 'advanced';

export interface UserProfileData {
  fullName: string;
  username: string;
  email: string;
  jobTitle: string;
  phone: string;
  phoneCountry: string;
  department: string;
  bio: string;
  avatarUrl: string;
  language: string;
  timeZone: string;
  dateFormat: string;
  theme: 'system' | 'light' | 'dark';
  weekStartsOn: 'Monday' | 'Sunday';
}

export interface SessionActivityItem {
  id: string;
  device: string;
  browser: string;
  ip: string;
  timestamp: string;
  isActive: boolean;
  type: 'desktop' | 'mobile' | 'tablet';
}

export interface LinkedAccountItem {
  id: string;
  provider: 'google' | 'github' | 'slack' | 'discord' | 'microsoft';
  name: string;
  identifier: string;
  connected: boolean;
  connectedAt?: string;
}

export interface ApiKeyItem {
  id: string;
  name: string;
  prefix: string;
  createdAt: string;
  lastUsedAt: string;
  expiresAt: string;
  scopes: string[];
}
