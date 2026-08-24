/**
 * ErrorBoundary — Catches React render errors without crashing the whole app.
 *
 * Wraps page sections so a crash in one panel shows a friendly error
 * message instead of white-screening the entire dashboard.
 */

import { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-8 bg-[#141416] border border-red-500/20 rounded-[10px] text-center">
          <div className="w-10 h-10 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-3">
            <AlertTriangle size={18} className="text-red-400" />
          </div>
          <h3 className="text-sm font-medium text-[#F2F1EE] mb-1">
            {this.props.fallbackTitle || 'Something went wrong'}
          </h3>
          <p className="text-xs font-mono text-[#6B6B6E] mb-3 max-w-md">
            {this.state.error?.message || 'An unexpected error occurred in this section.'}
          </p>
          <button
            onClick={this.handleReset}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-white/[0.04] border border-white/[0.1] rounded-[6px] text-xs text-[#A8A8AB] hover:text-[#F2F1EE] hover:border-white/[0.2] transition-colors"
          >
            <RefreshCw size={12} />
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
