import { useState, useCallback } from 'react';

const ENABLE_DEBUG = import.meta.env.VITE_ENABLE_DEBUG_MODE === 'true';
const MOCK_ROLE = import.meta.env.VITE_MOCK_USER_ROLE || 'consultant';

export function useDebugMode() {
  const [debugEnabled, setDebugEnabled] = useState(false);
  const isAdmin = MOCK_ROLE === 'admin';

  const toggleDebug = useCallback(() => {
    if (isAdmin && ENABLE_DEBUG) {
      setDebugEnabled((v) => !v);
    }
  }, [isAdmin]);

  return {
    isAdmin,
    debugEnabled: isAdmin && ENABLE_DEBUG && debugEnabled,
    toggleDebug,
  };
}
