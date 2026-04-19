import { useState, useEffect, useCallback } from 'react';
import { KEYS, getCompatItem, setCompatItem } from '../lib/storage-compat';

type Theme = 'light' | 'dark' | 'system';

function getSystemPreference(): 'light' | 'dark' {
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveTheme(theme: Theme): 'light' | 'dark' {
  return theme === 'system' ? getSystemPreference() : theme;
}

function applyTheme(resolved: 'light' | 'dark') {
  const root = document.documentElement;
  if (resolved === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
}

function readStoredTheme(): Theme {
  const stored = getCompatItem(KEYS.theme.new, KEYS.theme.legacy);
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  return 'dark';
}

function writeStoredTheme(theme: Theme) {
  setCompatItem(KEYS.theme.new, KEYS.theme.legacy, theme);
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);

  const resolved = resolveTheme(theme);

  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  useEffect(() => {
    if (theme !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => applyTheme(getSystemPreference());
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [theme]);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    writeStoredTheme(newTheme);
  }, []);

  return { theme, resolved, setTheme };
}
