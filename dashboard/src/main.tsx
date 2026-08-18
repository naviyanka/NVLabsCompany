import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

const App = React.lazy(() => import('./App'));

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element not found');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <React.Suspense fallback={<div className="flex items-center justify-center h-screen">Loading...</div>}>
      <App />
    </React.Suspense>
  </React.StrictMode>
);
