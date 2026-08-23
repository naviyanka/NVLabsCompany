import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

/**
 * Keeps signed-out visitors out of the application shell.
 *
 * This is convenience, not enforcement. Every route it protects is also
 * protected server-side; deleting this component would make the app ugly, not
 * insecure. Its real job is to send people somewhere useful — setup on a fresh
 * install, login otherwise — instead of a dashboard whose every panel errors.
 */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'loading') {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0A0A0B]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-[#FFB020] border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-mono text-[#6B6B6E]">Verifying session...</span>
        </div>
      </div>
    );
  }

  if (status === 'setup-required') {
    return <Navigate to="/setup" replace />;
  }

  if (status === 'anonymous') {
    // Remember where they were headed so login can put them back there.
    return (
      <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
    );
  }

  return <Outlet />;
}
