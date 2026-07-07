const WIKI_PAGE_SCHEME = 'wiki-page://';

export const WIKILINK_SCHEME = WIKI_PAGE_SCHEME;

export function wikilinkPreprocess(md: string): string {
  if (!md) return md;

  const segments: string[] = [];
  let cursor = 0;

  while (cursor < md.length) {
    const fenceMatch = md.slice(cursor).match(/^(```|~~~)/);
    if (fenceMatch) {
      const fence = fenceMatch[0];
      const fenceStart = md.indexOf('\n', cursor + fence.length);
      if (fenceStart === -1) {
        segments.push(md.slice(cursor));
        return segments.join('');
      }
      const fenceEnd = md.indexOf(fence, fenceStart + 1);
      const endIdx = fenceEnd === -1 ? md.length : fenceEnd + fence.length;
      segments.push(md.slice(cursor, endIdx));
      cursor = endIdx;
      continue;
    }

    const inlineCodeStart = md.indexOf('`', cursor);
    if (inlineCodeStart === -1) {
      segments.push(replaceBrackets(md.slice(cursor)));
      break;
    }
    segments.push(replaceBrackets(md.slice(cursor, inlineCodeStart)));
    const inlineCodeEnd = md.indexOf('`', inlineCodeStart + 1);
    if (inlineCodeEnd === -1) {
      segments.push(md.slice(inlineCodeStart));
      break;
    }
    segments.push(md.slice(inlineCodeStart, inlineCodeEnd + 1));
    cursor = inlineCodeEnd + 1;
  }

  return segments.join('');
}

function replaceBrackets(text: string): string {
  return text.replace(/\[\[([^\]\n|]+?)(?:\|([^\]\n]+?))?\]\]/g, (_, target: string, display?: string) => {
    const page = target.trim();
    const label = (display ?? page).trim();
    if (!page || !/^[A-Za-z0-9_\-\.\/\u4e00-\u9fff ]+$/.test(page)) return _;
    return `[${label}](${WIKI_PAGE_SCHEME}${encodeURIComponent(page)})`;
  });
}

export function isWikiPageHref(href: string | undefined | null): string | null {
  if (!href) return null;
  if (!href.startsWith(WIKI_PAGE_SCHEME)) return null;
  try {
    return decodeURIComponent(href.slice(WIKI_PAGE_SCHEME.length));
  } catch {
    return null;
  }
}