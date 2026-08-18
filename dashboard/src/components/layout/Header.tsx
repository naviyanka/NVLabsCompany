import { Bell, Search } from 'lucide-react';
import { Breadcrumb } from './Breadcrumb';

export interface HeaderProps {
  title?: string;
}

export function Header({ title }: HeaderProps) {
  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6">
      <div className="flex items-center gap-4">
        {title ? (
          <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
        ) : (
          <Breadcrumb />
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
          aria-label="Search"
        >
          <Search size={20} />
        </button>
        <button
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 relative"
          aria-label="Notifications"
        >
          <Bell size={20} />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 bg-danger-500 rounded-full" />
        </button>
      </div>
    </header>
  );
}
