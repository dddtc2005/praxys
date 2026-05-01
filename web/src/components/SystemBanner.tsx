import { useEffect, useState } from 'react';
import { X, Info, AlertTriangle, CheckCircle } from 'lucide-react';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { SystemAnnouncement } from '@/types/api';

const STORAGE_KEY = 'praxys_dismissed_banners';

function getDismissed(): Set<number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function saveDismissed(ids: Set<number>): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
}

const TYPE_STYLES = {
  info:    'bg-accent-cobalt/10 border-accent-cobalt/30 text-foreground',
  warning: 'bg-amber-500/10  border-amber-500/30  text-foreground',
  success: 'bg-primary/10    border-primary/30    text-foreground',
};

const TYPE_ICONS = {
  info:    <Info    className="h-4 w-4 text-accent-cobalt shrink-0 mt-0.5" />,
  warning: <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />,
  success: <CheckCircle   className="h-4 w-4 text-primary shrink-0 mt-0.5" />,
};

export default function SystemBanner() {
  const [banners, setBanners] = useState<SystemAnnouncement[]>([]);

  useEffect(() => {
    const headers = getAuthHeaders();
    if (!headers) return;
    fetch(`${API_BASE}/api/announcements`, { headers })
      .then((r) => r.ok ? r.json() : [])
      .then((data: SystemAnnouncement[]) => {
        const dismissed = getDismissed();
        setBanners(data.filter((b) => !dismissed.has(b.id)));
      })
      .catch(() => {});
  }, []);

  function dismiss(id: number) {
    const dismissed = getDismissed();
    dismissed.add(id);
    saveDismissed(dismissed);
    setBanners((prev) => prev.filter((b) => b.id !== id));
  }

  if (banners.length === 0) return null;

  return (
    <div className="space-y-2 px-4 pt-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      {banners.map((banner) => {
        const type = (banner.type as keyof typeof TYPE_STYLES) in TYPE_STYLES
          ? (banner.type as keyof typeof TYPE_STYLES)
          : 'info';
        return (
          <div
            key={banner.id}
            className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${TYPE_STYLES[type]}`}
          >
            {TYPE_ICONS[type]}
            <div className="flex-1 min-w-0">
              <span className="font-medium">{banner.title}</span>
              {banner.body && (
                <span className="ml-1 text-muted-foreground">{banner.body}</span>
              )}
              {banner.link_url && banner.link_text && (
                <a
                  href={banner.link_url}
                  className="ml-2 underline underline-offset-2 font-medium hover:opacity-80"
                >
                  {banner.link_text}
                </a>
              )}
            </div>
            <button
              onClick={() => dismiss(banner.id)}
              className="shrink-0 rounded p-0.5 hover:bg-black/10 transition-colors"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
