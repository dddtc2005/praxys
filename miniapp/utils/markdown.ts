/**
 * Tiny markdown → HTML converter sized for theory descriptions and
 * science-note copy. WeChat's <rich-text nodes="..."> consumes a small
 * subset of HTML — `<p>`, `<h1-h3>`, `<ul>`, `<ol>`, `<li>`, `<strong>`,
 * `<em>`, `<code>`, `<pre>`, `<a>` — and ignores click events on links,
 * so we also extract every `[text](url)` into a `links[]` list that the
 * caller can render as a separate tappable References section.
 *
 * Supported markdown (the subset that shows up in our science YAML):
 *
 *   # / ## / ### headers
 *   **bold** and *italic* / _italic_
 *   `inline code` and ```fenced``` code blocks
 *   - / * unordered lists
 *   1. ordered lists
 *   [text](url) links — rendered as text + extracted to links[]
 *   blank line = paragraph break
 *
 * Edge cases out of scope: tables, blockquotes, images, HTML pass-through,
 * nested lists. If the corpus ever needs them, switch to a real parser
 * like `marked` (5KB gzip) — for now this keeps the bundle at zero deps.
 */

export interface ExtractedLink {
  text: string;
  url: string;
}

export interface ParsedMarkdown {
  html: string;
  links: ExtractedLink[];
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function applyInline(escaped: string, links: ExtractedLink[]): string {
  // Order matters: code first (its content is opaque to other rules), then
  // links (consume their `[...](...)`), then bold (`**`) before italic
  // (single `*`/`_`) so `**` isn't misread as two italic markers.
  let out = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text: string, url: string) => {
    // Links go into the extracted list and also render as plain text in
    // rich-text. WeChat doesn't navigate <a> targets in mini programs,
    // so we surface URLs separately for tappable copy-to-clipboard rows.
    links.push({ text, url });
    return `<a>${text}</a>`;
  });

  out = out.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, '$1<em>$2</em>');
  out = out.replace(/(^|[^_])_([^_\n]+?)_(?!_)/g, '$1<em>$2</em>');

  return out;
}

export function parseMarkdown(md: string): ParsedMarkdown {
  if (!md) return { html: '', links: [] };

  const links: ExtractedLink[] = [];
  const lines = md.split(/\r?\n/);
  const blocks: string[] = [];

  let paragraphBuf: string[] = [];
  let inList = false;
  let listKind: 'ul' | 'ol' = 'ul';
  let inFence = false;
  let fenceBuf: string[] = [];

  const flushParagraph = () => {
    if (paragraphBuf.length === 0) return;
    const escaped = escapeHtml(paragraphBuf.join(' '));
    blocks.push(`<p>${applyInline(escaped, links)}</p>`);
    paragraphBuf = [];
  };
  const closeList = () => {
    if (inList) {
      blocks.push(`</${listKind}>`);
      inList = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine ?? '';

    if (/^```/.test(line)) {
      if (inFence) {
        blocks.push(`<pre><code>${escapeHtml(fenceBuf.join('\n'))}</code></pre>`);
        fenceBuf = [];
        inFence = false;
      } else {
        flushParagraph();
        closeList();
        inFence = true;
      }
      continue;
    }
    if (inFence) {
      fenceBuf.push(line);
      continue;
    }

    if (line.trim() === '') {
      flushParagraph();
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      const escaped = escapeHtml(heading[2]);
      blocks.push(`<h${level}>${applyInline(escaped, links)}</h${level}>`);
      continue;
    }

    const ulItem = line.match(/^[-*+]\s+(.+)$/);
    if (ulItem) {
      flushParagraph();
      if (!inList || listKind !== 'ul') {
        closeList();
        blocks.push('<ul>');
        listKind = 'ul';
        inList = true;
      }
      const escaped = escapeHtml(ulItem[1]);
      blocks.push(`<li>${applyInline(escaped, links)}</li>`);
      continue;
    }

    const olItem = line.match(/^\d+\.\s+(.+)$/);
    if (olItem) {
      flushParagraph();
      if (!inList || listKind !== 'ol') {
        closeList();
        blocks.push('<ol>');
        listKind = 'ol';
        inList = true;
      }
      const escaped = escapeHtml(olItem[1]);
      blocks.push(`<li>${applyInline(escaped, links)}</li>`);
      continue;
    }

    closeList();
    paragraphBuf.push(line);
  }

  flushParagraph();
  closeList();
  if (inFence && fenceBuf.length) {
    blocks.push(`<pre><code>${escapeHtml(fenceBuf.join('\n'))}</code></pre>`);
  }

  return { html: blocks.join(''), links };
}

/**
 * Copy a URL to the clipboard and surface a brief toast. Used by the
 * tappable "References" / "Source" rows since WeChat <rich-text>'s <a>
 * tags do not navigate in mini programs.
 */
export function copyUrlToClipboard(url: string): void {
  wx.setClipboardData({
    data: url,
    success: () => {
      wx.showToast({ title: 'URL copied', icon: 'success', duration: 1500 });
    },
    fail: () => {
      wx.showToast({ title: 'Copy failed', icon: 'none', duration: 1500 });
    },
  });
}
