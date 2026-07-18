import { useEffect, useState } from 'react';
import { apiFetch } from '@/hooks/useApi';
import { Trans } from '@lingui/react/macro';

interface Props {
  feedbackId: number;
  count: number;
}

/**
 * Admin-only thumbnails for feedback screenshots (issue #337). Each image is
 * private and served from `GET /api/admin/feedback/{id}/image/{index}` behind
 * the admin's bearer token — so a plain `<img src>` (which can't send an auth
 * header) won't work. We fetch each blob, turn it into an object URL, and
 * revoke the URLs on cleanup. Clicking a thumbnail opens the full image.
 */
export default function AdminFeedbackImages({ feedbackId, count }: Props) {
  const [urls, setUrls] = useState<string[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (count <= 0) return;
    const created: string[] = [];
    let cancelled = false;
    (async () => {
      const collected: string[] = [];
      let anyFail = false;
      for (let i = 0; i < count; i++) {
        try {
          const res = await apiFetch(`/api/admin/feedback/${feedbackId}/image/${i}`);
          if (!res.ok) {
            anyFail = true;
            continue;
          }
          const blob = await res.blob();
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          created.push(url);
          collected.push(url);
        } catch {
          anyFail = true;
        }
      }
      if (cancelled) {
        created.forEach((u) => URL.revokeObjectURL(u));
        return;
      }
      // setState only after awaits — never synchronously in the effect body.
      setUrls(collected);
      setFailed(anyFail && collected.length === 0);
    })();
    return () => {
      cancelled = true;
      created.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [feedbackId, count]);

  if (count <= 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {urls.map((src, i) => (
        <a key={i} href={src} target="_blank" rel="noreferrer">
          <img
            src={src}
            alt=""
            className="h-12 w-12 rounded border border-border object-cover transition-opacity hover:opacity-80"
          />
        </a>
      ))}
      {failed && urls.length === 0 && (
        <span className="text-xs text-muted-foreground">
          <Trans>Screenshot unavailable</Trans>
        </span>
      )}
    </div>
  );
}