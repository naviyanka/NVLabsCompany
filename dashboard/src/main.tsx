import React, { Component, type ReactNode } from 'react';
import ReactDOMClient from 'react-dom/client';
import App from './App';
import { applyTheme, getActiveTheme } from './styles/themes';
import './index.css';

// Restore the persisted theme before first paint so there is no flash.
applyTheme(getActiveTheme());

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Uncaught React Error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#0A0A0B] text-[#F2F1EE] flex items-center justify-center p-6 font-mono">
          <div className="max-w-xl w-full bg-[#141416] border border-red-500/30 rounded-xl p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-red-400">
              <span className="w-3 h-3 rounded-full bg-red-500 animate-ping" />
              <h2 className="text-base font-bold uppercase tracking-wider">Application Runtime Exception</h2>
            </div>
            
            <p className="text-xs text-gray-300">
              React encountered an error rendering the component tree:
            </p>

            <pre className="p-3 bg-[#0A0A0C] border border-white/[0.08] rounded text-[11px] text-rose-300 overflow-x-auto max-h-48 whitespace-pre-wrap">
              {this.state.error?.toString() || 'Unknown Runtime Error'}
            </pre>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => {
                  localStorage.clear();
                  window.location.href = '/';
                }}
                className="px-4 py-2 bg-[#FFB020] hover:bg-[#e09b1c] text-black font-bold text-xs rounded transition-colors cursor-pointer"
              >
                Reset App & Reload
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

ReactDOMClient.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
