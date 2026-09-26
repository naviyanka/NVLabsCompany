import { ApiClientError } from '@/api/client';

/** What the operator is told when the server refuses or cannot find something. */
export function describeError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.status === 404) return 'Not found, or not in your company.';
    if (error.status === 403) return 'You do not have permission to view this.';
    if (error.status === 401) return 'Your sign-in has expired.';
    return error.detail || `Request failed (${error.status}).`;
  }
  return error instanceof Error ? error.message : 'Request failed.';
}
