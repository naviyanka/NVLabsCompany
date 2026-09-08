# Micro-Phase 5: Real-Time SSE/WS Event Pipeline

## 1. Problem Statement
The backend provides robust SSE streaming (`/api/v1/events`) and WebSocket channels, but the frontend currently queries data on static intervals or component mounts, leaving UI views out of sync with autonomous agent state changes.

## 2. Technical Invariants
1. Frontend must automatically re-establish lost SSE connections with exponential backoff and jitter.
2. Incoming events on a channel must invalidate corresponding React Query cache keys automatically.
3. Live agent actions, task status changes, approvals, and budget events must reflect on screen in real-time.

## 3. Implementation Blueprint
1. Implement `dashboard/src/hooks/useEventStream.ts`:
   - Handles connection lifecycle, auth credentials, heartbeat, and reconnection.
   - Triggers `queryClient.invalidateQueries({ queryKey: [channel] })`.
2. Connect hook into:
   - `dashboard/src/pages/Activity.tsx`
   - `dashboard/src/pages/Tasks.tsx`
   - `dashboard/src/pages/Approvals.tsx`
   - `dashboard/src/pages/Office.tsx`
