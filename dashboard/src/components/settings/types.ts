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
  | 'secrets'
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
  lastUsedAt?: string;
  expiresAt?: string;
  scopes: string;
}

export interface IntegrationItem {
  id: string;
  name: string;
  category: 'version_control' | 'issue_tracking' | 'communication' | 'apm_telemetry' | 'cloud_infrastructure' | 'knowledge_base' | 'ai_provider';
  desc: string;
  active: boolean;
  icon: string;
  status: 'connected' | 'disconnected' | 'error';
  version?: string;
  credentials?: Record<string, string>;
  syncFeatures?: { id: string; label: string; enabled: boolean }[];
  lastSyncedAt?: string;
  latencyMs?: number;
}

export interface IntegrationTestResult {
  id: string;
  name: string;
  success: boolean;
  httpStatus: number;
  latencyMs: number;
  endpoint: string;
  authScheme: string;
  verifiedScopes: string[];
  requestHeaders: Record<string, string>;
  responseBody: Record<string, any>;
  timestamp: string;
}

export interface SystemConfigData {
  workspaceName: string;
  defaultEnv: string;
  defaultModel: string;
  fallbackModel: string;
  fastUtilityModel: string;
  temperature: number;
  topP: number;
  frequencyPenalty: number;
  presencePenalty: number;
  maxOutputTokens: number;
  maxStepHops: number;
  maxSubagentParallelism: number;
  contextWindowStrategy: 'sliding_window' | 'summarized_truncation' | 'full-[#FFB020]';
  vectorMemoryTopK: number;
  similarityThreshold: number;
  circuitBreakerFailures: number;
  retryStrategy: 'exponential_backoff' | 'fixed_retries';
  maxTaskBudget: string;
  dailyCompanyCap: string;
  killSwitchEngaged: boolean;
}

export interface NotificationEventRule {
  id: string;
  eventName: string;
  category: 'agent' | 'budget' | 'security' | 'pipeline' | 'system';
  email: boolean;
  slack: boolean;
  teams: boolean;
  telegram: boolean;
  discord: boolean;
  pagerduty: boolean;
  webhook: boolean;
  inApp: boolean;
  priority: 'critical' | 'warning' | 'info';
}

export interface NotificationConfigData {
  emailEnabled: boolean;
  emailRecipients: string;
  smtpServer?: string;
  slackEnabled: boolean;
  slackWebhookUrl: string;
  slackChannel: string;
  teamsEnabled: boolean;
  teamsWebhookUrl: string;
  telegramEnabled: boolean;
  telegramBotToken: string;
  telegramChatId: string;
  discordEnabled: boolean;
  discordWebhookUrl: string;
  pagerdutyEnabled: boolean;
  pagerdutyIntegrationKey: string;
  webhookEnabled: boolean;
  webhookUrl: string;
  webhookHmacSecret: string;
  inAppEnabled: boolean;
  audioChimeEnabled: boolean;
  browserPingsEnabled: boolean;
  quietHoursEnabled: boolean;
  quietHoursStart?: string;
  quietHoursEnd?: string;
  eventRules: NotificationEventRule[];
}

export interface BackupLocationConfig {
  targetType: 'local' | 's3' | 'gcp';
  localPath: string;
  s3Bucket: string;
  s3Region: string;
  s3Endpoint: string;
  s3AccessKey: string;
  s3SecretKey: string;
  autoReplicate: boolean;
  backupFreq: string;
  backupScope: string;
  maxRetentionCount: string;
}

export interface SnapshotArchiveItem {
  id: string;
  name: string;
  timestamp: string;
  sizeBytes: number;
  sizeFormatted: string;
  scope: 'Full System' | 'Core DB & Settings' | 'Telemetry Logs';
  sha256: string;
  location: string;
  status: 'Verified' | 'Creating' | 'Failed';
  isAuto: boolean;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  correlationId?: string;
  traceId?: string;
  spanId?: string;
  parentSpanId?: string;
  actor: string;
  actorType: 'Operator' | 'Agent Workload' | 'System Daemon' | 'Security Engine';
  actorRole?: string;
  authScheme?: string;
  tenantId?: string;
  organizationSquad?: string;
  environment?: string;
  hostname?: string;
  executionEngine?: string;
  action: string;
  target: string;
  targetType: string;
  ip: string;
  location?: string;
  severity: 'info' | 'warning' | 'critical';
  details: string;
  httpMethod?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  requestPath?: string;
  protocol?: string;
  statusCode?: number;
  latencyMs?: number;
  bytesTransferred?: string;
  userAgent?: string;
  sessionId?: string;
  requestHeaders?: Record<string, string>;
  riskScore?: number;
  complianceTags?: ('SOC2' | 'ISO27001' | 'GDPR' | 'HIPAA' | 'PCI_DSS')[];
  beforeState?: Record<string, any>;
  afterState?: Record<string, any>;
  previousHash?: string;
  sha256: string;
  signature?: string;
  payload?: Record<string, any>;
}

export interface CliToolConfig {
  id: string;
  name: string;
  category: 'code_intelligence' | 'sandbox' | 'language_runtime' | 'search_utility' | 'mcp_connector';
  command: string;
  enabled: boolean;
  installed: boolean;
  version?: string;
  path?: string;
  timeoutSeconds: number;
  agentScope: 'all' | 'architect_lead_only' | 'operator_approval_required';
  envVars?: Record<string, string>;
  description: string;
  iconName: string;
}

export interface AgentProviderBudget {
  id: string;
  name: string;
  category: 'cli_tool' | 'llm_provider' | 'code_intelligence' | 'compute_cluster' | 'custom';
  icon: string;
  creditMetric: 'Credits' | 'USD ($)' | 'Tokens' | 'Compute Hours' | 'API Requests';
  totalCredits: number;
  usedCredits: number;
  remainingCredits: number;
  unitPrefix?: string;
  unitSuffix?: string;
  warningThresholdPercent: number;
  hardStopAction: 'halt_execution' | 'switch_fallback' | 'notify_operator_only';
  renewalCycle: 'monthly' | 'pay_as_you_go' | 'annual';
  isCustom?: boolean;
  lastRefreshedAt?: string;
}

export interface GeneralWorkspaceConfig {
  workspaceName: string;
  workspaceSlug: string;
  workspaceIcon: string;
  primaryContactEmail: string;
  defaultEnv: 'production' | 'staging' | 'development';
  executionIsolationMode: 'gvisor_microvm' | 'docker_container' | 'host_sandbox';
  maxAgentConcurrency: number;
  idleAutoSleepMinutes: number;
  maxTaskRetryCap: number;
  autoArchiveDays: number;
  timeZone: string;
  dateFormat: string;
  defaultRepoBranch: string;
  maintenanceModeEngaged: boolean;
  lastCacheFlushedAt?: string;
}
