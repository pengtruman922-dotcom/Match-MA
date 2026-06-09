import { useCallback, useEffect, useState } from 'react';
import { getStoredUser } from './auth';

const ENABLE_DEBUG = import.meta.env.VITE_ENABLE_DEBUG_MODE === 'true';
const DEBUG_STORAGE_KEY = 'match_ma_debug_enabled';
const DEBUG_EVENT = 'match_ma_debug_changed';

export function useDebugMode() {
  const [debugEnabled, setDebugEnabled] = useState(() => window.localStorage.getItem(DEBUG_STORAGE_KEY) === 'true');
  const user = getStoredUser();
  const isAdmin = user?.role === 'admin';

  const toggleDebug = useCallback(() => {
    if (isAdmin && ENABLE_DEBUG) {
      setDebugEnabled((value) => {
        const next = !value;
        window.localStorage.setItem(DEBUG_STORAGE_KEY, String(next));
        window.dispatchEvent(new CustomEvent(DEBUG_EVENT, { detail: next }));
        return next;
      });
    }
  }, [isAdmin]);

  useEffect(() => {
    function syncDebugState(event: Event) {
      const detail = event instanceof CustomEvent ? event.detail : undefined;
      setDebugEnabled(typeof detail === 'boolean' ? detail : window.localStorage.getItem(DEBUG_STORAGE_KEY) === 'true');
    }
    window.addEventListener(DEBUG_EVENT, syncDebugState);
    window.addEventListener('storage', syncDebugState);
    return () => {
      window.removeEventListener(DEBUG_EVENT, syncDebugState);
      window.removeEventListener('storage', syncDebugState);
    };
  }, []);

  return {
    isAdmin,
    debugEnabled: isAdmin && ENABLE_DEBUG && debugEnabled,
    toggleDebug,
  };
}
