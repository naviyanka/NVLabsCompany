import { useState, useEffect } from 'react';

/**
 * Returns whether the page is currently visible.
 * Used to pause GPU-intensive rendering (e.g. Three.js canvas)
 * when the tab is not active, saving power and reducing heat.
 */
export function usePageVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(!document.hidden);

  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsVisible(!document.hidden);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  return isVisible;
}
