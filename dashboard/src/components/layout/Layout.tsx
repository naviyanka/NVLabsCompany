import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { PulseLine } from './PulseLine';
import { CommandPalette } from '../common/CommandPalette';

export function Layout() {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const location = useLocation();

  const isFullCanvasPage = location.pathname === '/memory-graph' || location.pathname === '/office';

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-[#F2F1EE] flex flex-row overflow-hidden font-sans">
      {/* Sidebar Navigation */}
      <Sidebar
        isMobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
        {/* Header with Breadcrumb & Search */}
        <Header
          onToggleSidebar={() => setMobileSidebarOpen((prev) => !prev)}
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
        />

        {/* Signature Element: Pulse Line Ticker */}
        <PulseLine />

        {/* Dynamic Page Outlet */}
        <main
          className={`flex-1 overflow-hidden bg-[#0A0A0B] ${
            isFullCanvasPage
              ? 'p-2 sm:p-3 overflow-hidden flex flex-col min-h-0'
              : 'overflow-y-auto p-4 sm:p-6 lg:p-8'
          }`}
        >
          <div
            className={`w-full ${
              isFullCanvasPage
                ? 'h-full flex-1 flex flex-col min-h-0'
                : 'max-w-7xl mx-auto space-y-6'
            }`}
          >
            <Outlet />
          </div>
        </main>
      </div>

      {/* Cmd+K Global Command Palette */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </div>
  );
}
