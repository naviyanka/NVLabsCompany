import { useLocation, Link } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';

function formatSegment(segment: string): string {
  return segment
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function Breadcrumb() {
  const location = useLocation();
  const pathSegments = location.pathname.split('/').filter(Boolean);

  if (pathSegments.length === 0) {
    return (
      <nav className="flex items-center text-sm text-gray-500">
        <Home size={16} className="text-gray-400" />
        <span className="ml-2 font-medium text-gray-900">Dashboard</span>
      </nav>
    );
  }

  return (
    <nav className="flex items-center text-sm text-gray-500" aria-label="Breadcrumb">
      <Link to="/" className="hover:text-gray-700">
        <Home size={16} />
      </Link>
      {pathSegments.map((segment, index) => {
        const path = '/' + pathSegments.slice(0, index + 1).join('/');
        const isLast = index === pathSegments.length - 1;

        return (
          <span key={path} className="flex items-center">
            <ChevronRight size={14} className="mx-2 text-gray-400" />
            {isLast ? (
              <span className="font-medium text-gray-900">{formatSegment(segment)}</span>
            ) : (
              <Link to={path} className="hover:text-gray-700">
                {formatSegment(segment)}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
