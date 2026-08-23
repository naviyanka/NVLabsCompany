import {
  GitPullRequest,
  GitMerge,
  XCircle,
  FileCode,
  CheckCircle2,
  AlertOctagon,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  Clock,
  CheckCheck,
} from 'lucide-react';
import type { PRReviewer } from '@/types/gitRepo';

interface PRStatusBadgeProps {
  status: 'open' | 'merged' | 'closed' | 'draft';
  className?: string;
  size?: 'xs' | 'sm' | 'md';
}

export function PRStatusBadge({ status, className = '', size = 'sm' }: PRStatusBadgeProps) {
  const sizeClasses = {
    xs: 'px-1.5 py-0.5 text-[9px] gap-1',
    sm: 'px-2 py-0.5 text-[10px] gap-1.5',
    md: 'px-2.5 py-1 text-xs gap-1.5',
  }[size];

  const iconSizes = {
    xs: 'w-2.5 h-2.5',
    sm: 'w-3 h-3',
    md: 'w-3.5 h-3.5',
  }[size];

  switch (status) {
    case 'open':
      return (
        <span
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shadow-[0_0_8px_rgba(34,197,94,0.15)] ${sizeClasses} ${className}`}
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
          </span>
          <GitPullRequest className={iconSizes} />
          <span>Open</span>
        </span>
      );

    case 'merged':
      return (
        <span
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-purple-500/15 text-purple-300 border border-purple-500/30 shadow-[0_0_8px_rgba(168,85,247,0.15)] ${sizeClasses} ${className}`}
        >
          <GitMerge className={`${iconSizes} text-purple-300`} />
          <span>Merged</span>
        </span>
      );

    case 'closed':
      return (
        <span
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-rose-500/15 text-rose-400 border border-rose-500/30 ${sizeClasses} ${className}`}
        >
          <XCircle className={`${iconSizes} text-rose-400`} />
          <span>Closed</span>
        </span>
      );

    case 'draft':
    default:
      return (
        <span
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-zinc-500/15 text-zinc-400 border border-zinc-500/30 ${sizeClasses} ${className}`}
        >
          <FileCode className={iconSizes} />
          <span>Draft</span>
        </span>
      );
  }
}

interface PRChecksBadgeProps {
  checks: 'passed' | 'failed' | 'running' | 'pending';
  className?: string;
  size?: 'xs' | 'sm' | 'md';
  showLabel?: boolean;
}

export function PRChecksBadge({
  checks,
  className = '',
  size = 'sm',
  showLabel = true,
}: PRChecksBadgeProps) {
  const sizeClasses = {
    xs: 'px-1.5 py-0.5 text-[9px] gap-1',
    sm: 'px-2 py-0.5 text-[10px] gap-1.5',
    md: 'px-2.5 py-1 text-xs gap-1.5',
  }[size];

  const iconSizes = {
    xs: 'w-2.5 h-2.5',
    sm: 'w-3 h-3',
    md: 'w-3.5 h-3.5',
  }[size];

  switch (checks) {
    case 'failed':
      return (
        <span
          title="CI/CD Pipeline Checks Failed"
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-rose-500/15 text-rose-400 border border-rose-500/30 shadow-[0_0_8px_rgba(244,63,94,0.15)] ${sizeClasses} ${className}`}
        >
          <AlertOctagon className={`${iconSizes} text-rose-400`} />
          {showLabel && <span>CI Failed</span>}
        </span>
      );

    case 'running':
      return (
        <span
          title="CI/CD Matrix Tests & AST Checks Running"
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 ${sizeClasses} ${className}`}
        >
          <RefreshCw className={`${iconSizes} animate-spin text-cyan-300`} />
          {showLabel && <span>CI Running</span>}
        </span>
      );

    case 'pending':
      return (
        <span
          title="CI Checks Queued / Pending"
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-amber-500/15 text-amber-400 border border-amber-500/30 ${sizeClasses} ${className}`}
        >
          <Clock className={`${iconSizes} text-amber-400`} />
          {showLabel && <span>CI Pending</span>}
        </span>
      );

    case 'passed':
    default:
      return (
        <span
          title="All AST Security & Matrix Checks Passed"
          className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 ${sizeClasses} ${className}`}
        >
          <CheckCircle2 className={`${iconSizes} text-emerald-400`} />
          {showLabel && <span>CI Passed</span>}
        </span>
      );
  }
}

interface PRReviewBadgeProps {
  reviewers?: PRReviewer[];
  status: 'open' | 'merged' | 'closed' | 'draft';
  className?: string;
  size?: 'xs' | 'sm' | 'md';
}

export function PRReviewBadge({
  reviewers = [],
  status,
  className = '',
  size = 'sm',
}: PRReviewBadgeProps) {
  const sizeClasses = {
    xs: 'px-1.5 py-0.5 text-[9px] gap-1',
    sm: 'px-2 py-0.5 text-[10px] gap-1.5',
    md: 'px-2.5 py-1 text-xs gap-1.5',
  }[size];

  const iconSizes = {
    xs: 'w-2.5 h-2.5',
    sm: 'w-3 h-3',
    md: 'w-3.5 h-3.5',
  }[size];

  if (status === 'merged') {
    return (
      <span
        title="Pull Request Approved & Merged into Base Branch"
        className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-purple-500/10 text-purple-300 border border-purple-500/20 ${sizeClasses} ${className}`}
      >
        <CheckCheck className={`${iconSizes} text-purple-300`} />
        <span>Approved & Merged</span>
      </span>
    );
  }

  if (status === 'closed') {
    return null;
  }

  const hasChangesRequested = reviewers.some((r) => r.decision === 'changes_requested');
  const approvedCount = reviewers.filter((r) => r.decision === 'approved').length;

  if (hasChangesRequested) {
    return (
      <span
        title="Reviewer Requested Changes on AST / Security Gate"
        className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-amber-500/15 text-amber-400 border border-amber-500/30 shadow-[0_0_8px_rgba(245,158,11,0.15)] ${sizeClasses} ${className}`}
      >
        <AlertTriangle className={`${iconSizes} text-amber-400`} />
        <span>Changes Requested</span>
      </span>
    );
  }

  if (approvedCount > 0) {
    return (
      <span
        title={`Approved by ${approvedCount} Agent Reviewer${approvedCount !== 1 ? 's' : ''}`}
        className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 ${sizeClasses} ${className}`}
      >
        <CheckCircle2 className={`${iconSizes} text-emerald-400`} />
        <span>Approved ({approvedCount})</span>
      </span>
    );
  }

  // Needs review (no approvals, pending review, or empty reviewers)
  return (
    <span
      title="Awaiting autonomous agent review or human sign-off"
      className={`inline-flex items-center font-mono font-medium rounded-[5px] bg-amber-500/15 text-amber-400 border border-amber-500/30 shadow-[0_0_8px_rgba(245,158,11,0.15)] ${sizeClasses} ${className}`}
    >
      <AlertCircle className={`${iconSizes} text-amber-400`} />
      <span>Needs Review</span>
    </span>
  );
}
