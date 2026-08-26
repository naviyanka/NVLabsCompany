import { useState, useEffect } from 'react';
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Lock,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { apiClient, unwrapItems } from '@/api/client';
import { getActiveCompanyId } from '@/config';

interface GovernanceApproval {
  id: string;
  title: string;
  agent_id: string;
  risk_level: 'critical' | 'high' | 'medium' | 'low';
  category: 'tool_execution' | 'budget_override' | 'prod_deploy' | string;
  status: 'pending' | 'approved' | 'rejected';
  payload_summary: string;
  created_at: string;
}

function mapApproval(raw: Record<string, unknown>): GovernanceApproval {
  const status = raw.status === 'approved' ? 'approved' : raw.status === 'rejected' ? 'rejected' : 'pending';
  const type = (raw.type || 'tool_execution') as string;
  const payload = (raw.payload || {}) as Record<string, unknown>;
  const envVar = payload.env_var as string | undefined;
  return {
    id: String(raw.id ?? ''),
    title: envVar ? `API Key Required: ${envVar}` : type,
    agent_id: (payload.agent_name as string) || (payload.agent_id as string) || 'unknown',
    risk_level: ((raw.risk_level as string) || payload.risk_level || 'medium') as GovernanceApproval['risk_level'],
    category: type,
    status,
    payload_summary:
      (payload.agent_name
        ? `Agent ${payload.agent_name} (${payload.agent_role ?? 'agent'}) needs ${envVar ?? type} to function.`
        : Object.keys(payload).length > 0
        ? JSON.stringify(payload).slice(0, 200)
        : ''),
    created_at: (raw.created_at as string) || new Date().toISOString(),
  };
}

export function Approvals() {
  const [approvals, setApprovals] = useState<GovernanceApproval[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadApprovals() {
      try {
        const res = await apiClient.get<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(
          `/api/v1/companies/${getActiveCompanyId()}/approvals/pending`
        );
        if (isMounted) {
          setApprovals(unwrapItems(res).map(mapApproval));
          setLoadError(null);
        }
      } catch (err) {
        if (isMounted) setLoadError('Failed to load approvals from the backend.');
      }
    }
    loadApprovals();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleDecision = async (id: string, decision: 'approved' | 'rejected') => {
    const action = decision === 'approved' ? 'approve' : 'reject';
    try {
      await apiClient.post(`/api/v1/approvals/${id}/${action}`, { decided_by: 'operator' });
      setApprovals((prev) => prev.map((a) => (a.id === id ? { ...a, status: decision } : a)));
    } catch (err) {
      console.error('Failed to record approval decision', err);
      setLoadError('Failed to record the decision. Please retry.');
    }
  };

  const pendingCount = approvals.filter((a) => a.status === 'pending').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Governance & Action Approval Gate
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Human-in-the-loop authorization for elevated permissions, high-cost operations, and shell execution
          </p>
        </div>
      </div>

      {loadError && (
        <div className="flex items-center gap-2 p-3 rounded-[8px] bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-mono">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {loadError}
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Pending Gate Requests"
          value={`${pendingCount} Requests`}
          subValue="Requires Operator Action"
          change={pendingCount > 0 ? 'Action required' : 'All clear'}
          changeType={pendingCount > 0 ? 'negative' : 'positive'}
          icon={<AlertTriangle className="w-4 h-4" />}
        />
        <StatCard
          label="Auto-Approved Operations"
          value="1,482"
          subValue="Low-risk executions"
          change="99.4% policy compliance"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <StatCard
          label="Security Guardrails"
          value="Enforced"
          subValue="Zero-Trust IAM"
          change="Hard isolation"
          changeType="positive"
          icon={<Lock className="w-4 h-4" />}
        />
      </div>

      {/* Approvals List */}
      <div className="space-y-3">
        {approvals.length === 0 ? (
          <EmptyState
            title="No approvals pending"
            description="All autonomous agent operations are currently within authorized risk thresholds."
            icon={<CheckCircle2 size={24} />}
          />
        ) : (
          approvals.map((req) => (
            <Card key={req.id}>
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <h3 className="text-xs font-medium text-[#F2F1EE]">{req.title}</h3>
                    <Badge variant={req.risk_level === 'critical' ? 'failed' : 'in_progress'}>
                      {req.risk_level} risk
                    </Badge>
                    <Badge variant={req.status === 'approved' ? 'completed' : req.status === 'rejected' ? 'failed' : 'idle'}>
                      {req.status}
                    </Badge>
                  </div>

                  <div className="text-[11px] font-mono text-[#6B6B6E]">
                    Requesting Agent: <span className="text-[#FFB020]">{req.agent_id}</span> · Category:{' '}
                    <span className="uppercase text-[#A8A8AB]">{req.category}</span>
                  </div>

                  <div className="p-2.5 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs font-mono text-[#F2F1EE] leading-relaxed">
                    {req.payload_summary}
                  </div>
                </div>

                {req.status === 'pending' ? (
                  <div className="flex items-center gap-2 shrink-0 self-end md:self-auto">
                    <Button
                      variant="secondary"
                      size="xs"
                      icon={<XCircle size={13} className="text-[#EF4444]" />}
                      onClick={() => handleDecision(req.id, 'rejected')}
                    >
                      Deny
                    </Button>
                    <Button
                      variant="primary"
                      size="xs"
                      icon={<CheckCircle2 size={13} />}
                      onClick={() => handleDecision(req.id, 'approved')}
                    >
                      Authorize
                    </Button>
                  </div>
                ) : (
                  <div className="text-xs font-mono text-[#6B6B6E] shrink-0">
                    Decision recorded
                  </div>
                )}
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
