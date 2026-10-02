{{/*
Expand the name of the chart.
*/}}
{{- define "nexus.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "nexus.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "nexus.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "nexus.labels" -}}
helm.sh/chart: {{ include "nexus.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ include "nexus.name" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Selector labels for a component
Usage: {{ include "nexus.selectorLabels" (dict "context" . "component" "api") }}
*/}}
{{- define "nexus.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nexus.name" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "nexus.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nexus.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Database identities. The application, migration and system roles are three different
principals, and each is used for one thing: the application role runs the pods, the
migrator role owns the schema and runs migrations, and the system role is for explicit
maintenance and is never given to a pod. Rendering fails rather than collapse them.
*/}}
{{- define "nexus.validateDatabaseRoles" -}}
{{- $app := required "database.user is required" .Values.database.user -}}
{{- $system := required "database.systemUser is required" .Values.database.systemUser -}}
{{- $migrator := required "migration.user is required" .Values.migration.user -}}
{{- if or (eq $app $migrator) (eq $app $system) (eq $migrator $system) -}}
{{- fail "database.user, database.systemUser and migration.user must be three different roles" -}}
{{- end -}}
{{- if eq $app "nexus_system" -}}
{{- fail "database.user must not be the system role nexus_system" -}}
{{- end -}}
{{- if eq $app "nexus_migrator" -}}
{{- fail "database.user must not be the migrator role nexus_migrator" -}}
{{- end -}}
{{- if eq $migrator "nexus_app" -}}
{{- fail "migration.user must not be the application role nexus_app" -}}
{{- end -}}
{{- if eq $migrator "nexus_system" -}}
{{- fail "migration.user must not be the system role nexus_system" -}}
{{- end -}}
{{- if .Values.migration.enabled -}}
{{- $_ := required "migration.existingSecret is required: the migration job needs its own credential and never falls back to the application's" .Values.migration.existingSecret -}}
{{- $_ := required "migration.secretKey is required" .Values.migration.secretKey -}}
{{- end -}}
{{- end }}
