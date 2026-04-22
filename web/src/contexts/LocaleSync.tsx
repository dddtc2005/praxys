import { useEffect } from 'react';
import { useSettings } from './SettingsContext';
import { useLocale } from './LocaleContext';
import { isSupportedLocale } from '../i18n/init';

/**
 * Mounts inside SettingsProvider + LocaleProvider. When the server returns a
 * `config.language` preference, activate it. Takes precedence over the
 * browser-detected locale that LocaleProvider picked on first paint.
 */
export default function LocaleSync() {
  const { config } = useSettings();
  const { locale, setLocale } = useLocale();

  useEffect(() => {
    const serverLocale = config?.language;
    if (!serverLocale) return;
    if (!isSupportedLocale(serverLocale)) return;
    if (serverLocale === locale) return;
    void setLocale(serverLocale);
  }, [config?.language, locale, setLocale]);

  return null;
}
