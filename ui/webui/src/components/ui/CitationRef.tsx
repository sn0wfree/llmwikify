import React, { useState, useRef, useEffect } from 'react';

export interface ReportSource {
  id: string;
  title: string;
  url: string;
  source_type: string;
}

const CITATION_CHARS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';

function md5(s: string): string {
  function L(k: number, d: number) { return (k << d) | (k >>> (32 - d)); }
  function K(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
    a = (a + ((b & c) | (~b & d)) + x + t) | 0;
    return ((a << s) | (a >>> (32 - s))) + b | 0;
  }
  function m(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
    a = (a + ((b & d) | (c & ~d)) + x + t) | 0;
    return ((a << s) | (a >>> (32 - s))) + b | 0;
  }
  function g(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
    a = (a + (b ^ c ^ d) + x + t) | 0;
    return ((a << s) | (a >>> (32 - s))) + b | 0;
  }
  function h(a: number, b: number, c: number, d: number, x: number, s: number, t: number) {
    a = (a + (c ^ (b | ~d)) + x + t) | 0;
    return ((a << s) | (a >>> (32 - s))) + b | 0;
  }
  function cvt(x: number) {
    let r = '';
    for (let i = 0; i < 4; i++) r += ((x >> (i * 8)) & 255).toString(16).padStart(2, '0');
    return r;
  }
  let a = 1732584193, b = -271733879, c = -1732584194, d = 271733878;
  const len = s.length;
  const bytes = new Uint8Array(((len + 8) >>> 6) + 1 << 6);
  for (let i = 0; i < len; i++) bytes[i] = s.charCodeAt(i);
  bytes[len] = 128;
  bytes[bytes.length - 8] = (len * 8) & 255;
  bytes[bytes.length - 7] = (len * 8 >>> 8) & 255;
  for (let i = 0; i < bytes.length; i += 64) {
    const w = new Array<number>(16);
    for (let j = 0; j < 16; j++) w[j] = bytes[i + j * 4] | (bytes[i + j * 4 + 1] << 8) | (bytes[i + j * 4 + 2] << 16) | (bytes[i + j * 4 + 3] << 24);
    const [aa, bb, cc, dd] = [a, b, c, d];
    a = K(a, b, c, d, w[0], 7, -680876936); d = K(d, a, b, c, w[1], 12, -389564586);
    c = K(c, d, a, b, w[2], 17, 606105819); b = K(b, c, d, a, w[3], 22, -1044525330);
    a = K(a, b, c, d, w[4], 7, -176418897); d = K(d, a, b, c, w[5], 12, 1200080426);
    c = K(c, d, a, b, w[6], 17, -1473231341); b = K(b, c, d, a, w[7], 22, -45705983);
    a = K(a, b, c, d, w[8], 7, 1770035416); d = K(d, a, b, c, w[9], 12, -1958414417);
    c = K(c, d, a, b, w[10], 17, -42063); b = K(b, c, d, a, w[11], 22, -1990404162);
    a = K(a, b, c, d, w[12], 7, 1804603682); d = K(d, a, b, c, w[13], 12, -40341101);
    c = K(c, d, a, b, w[14], 17, -1502002290); b = K(b, c, d, a, w[15], 22, 1236535329);
    a = m(a, b, c, d, w[1], 5, -165796510); d = m(d, a, b, c, w[6], 9, -1069501632);
    c = m(c, d, a, b, w[11], 14, 643717713); b = m(b, c, d, a, w[0], 20, -373897302);
    a = m(a, b, c, d, w[5], 5, -701558691); d = m(d, a, b, c, w[10], 9, 38016083);
    c = m(c, d, a, b, w[15], 14, -660478335); b = m(b, c, d, a, w[4], 20, -405537848);
    a = m(a, b, c, d, w[9], 5, 568446438); d = m(d, a, b, c, w[14], 9, -1019803690);
    c = m(c, d, a, b, w[3], 14, -187363961); b = m(b, c, d, a, w[8], 20, 1163531501);
    a = m(a, b, c, d, w[13], 5, -1444681467); d = m(d, a, b, c, w[2], 9, -51403784);
    c = m(c, d, a, b, w[7], 14, 1735328473); b = m(b, c, d, a, w[12], 20, -1926607734);
    a = g(a, b, c, d, w[5], 4, -378558); d = g(d, a, b, c, w[8], 11, -2022574463);
    c = g(c, d, a, b, w[11], 16, 1839030562); b = g(b, c, d, a, w[14], 23, -35309556);
    a = g(a, b, c, d, w[1], 4, -1530992060); d = g(d, a, b, c, w[4], 11, 1272893353);
    c = g(c, d, a, b, w[7], 16, -155497632); b = g(b, c, d, a, w[10], 23, -1094730640);
    a = g(a, b, c, d, w[13], 4, 681279174); d = g(d, a, b, c, w[0], 11, -358537222);
    c = g(c, d, a, b, w[3], 16, -722521979); b = g(b, c, d, a, w[6], 23, 76029189);
    a = g(a, b, c, d, w[9], 4, -640364487); d = g(d, a, b, c, w[12], 11, -421815835);
    c = g(c, d, a, b, w[15], 16, 530742520); b = g(b, c, d, a, w[2], 23, -995338651);
    a = h(a, b, c, d, w[0], 6, -198630844); d = h(d, a, b, c, w[7], 10, 1126891415);
    c = h(c, d, a, b, w[14], 15, -1416354905); b = h(b, c, d, a, w[5], 21, -57434055);
    a = h(a, b, c, d, w[12], 6, 1700485571); d = h(d, a, b, c, w[3], 10, -1894986606);
    c = h(c, d, a, b, w[10], 15, -1051523); b = h(b, c, d, a, w[1], 21, -2054922799);
    a = h(a, b, c, d, w[8], 6, 1873313359); d = h(d, a, b, c, w[15], 10, -30611744);
    c = h(c, d, a, b, w[6], 15, -1560198380); b = h(b, c, d, a, w[13], 21, 1309151649);
    a = h(a, b, c, d, w[4], 6, -145523070); d = h(d, a, b, c, w[11], 10, -1120210379);
    c = h(c, d, a, b, w[2], 15, 718787259); b = h(b, c, d, a, w[9], 21, -343485551);
    a = (a + aa) | 0; b = (b + bb) | 0; c = (c + cc) | 0; d = (d + dd) | 0;
  }
  return cvt(a) + cvt(b) + cvt(c) + cvt(d);
}

function computeSourceHash(source: ReportSource): string {
  return md5(source.url || source.title || '');
}

export function buildSourceMap(sources: ReportSource[]): Map<string, ReportSource> {
  const map = new Map<string, ReportSource>();
  sources.forEach(src => {
    map.set(computeSourceHash(src), src);
  });
  return map;
}

interface CitationRefProps {
  index: number;
  source: ReportSource;
  onOpenWiki?: (pageName: string) => void;
}

export function CitationRef({ index, source, onOpenWiki }: CitationRefProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const isWiki = source.source_type === 'wiki' || source.url.startsWith('wiki://');

  const label = index <= CITATION_CHARS.length
    ? CITATION_CHARS[index - 1]
    : `[${index}]`;

  const typeLabel = source.source_type === 'arxiv' ? 'arXiv'
    : source.source_type === 'pdf' ? 'PDF'
    : source.source_type === 'wiki' ? 'Wiki'
    : source.source_type === 'youtube' ? 'YouTube'
    : 'Web';

  useEffect(() => {
    if (showTooltip && ref.current) {
      const rect = ref.current.getBoundingClientRect();
      const body = ref.current.closest('.report-body');
      if (body) {
        const br = body.getBoundingClientRect();
        setTooltipPos({ x: rect.left - br.left + rect.width / 2, y: rect.bottom - br.top + 6 });
      } else {
        setTooltipPos({ x: rect.left + rect.width / 2, y: rect.bottom + 6 });
      }
    }
  }, [showTooltip]);

  const handleOpen = () => {
    if (isWiki && onOpenWiki) {
      onOpenWiki(source.title || source.url.replace('wiki://', ''));
    } else {
      window.open(source.url, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <span className="citation-wrapper relative inline-flex">
      <sup>
        <span
          ref={ref}
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
          onClick={() => setShowTooltip(p => !p)}
          className="citation-ref cursor-pointer text-primary hover:underline font-medium text-[10px] leading-none"
        >
          {label}
        </span>
      </sup>

      {showTooltip && (
        <div
          className="fixed z-50 bg-card border border-border rounded-lg shadow-xl p-2.5 text-xs pointer-events-auto"
          style={{ left: tooltipPos.x, top: tooltipPos.y, transform: 'translateX(-50%)', minWidth: 200, maxWidth: 280 }}
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
        >
          <div className="font-medium text-foreground mb-1 leading-snug">
            {source.title || source.url}
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <span className={`px-1 py-px rounded text-[9px] ${
              source.source_type === 'arxiv' ? 'bg-purple-500/20 text-purple-400' :
              source.source_type === 'pdf' ? 'bg-orange-500/20 text-orange-400' :
              source.source_type === 'wiki' ? 'bg-purple-500/20 text-purple-400' :
              source.source_type === 'youtube' ? 'bg-red-500/20 text-red-400' :
              'bg-blue-500/20 text-blue-400'
            }`}>
              {typeLabel}
            </span>
            <span className="text-muted-foreground truncate max-w-[180px]">
              {isWiki ? 'Local wiki page' : (() => { try { return new URL(source.url).hostname.replace('www.', ''); } catch { return source.url; } })()}
            </span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); handleOpen(); }}
            className="mt-1.5 inline-block text-[10px] text-primary hover:underline"
          >
            {isWiki ? 'View Wiki Page →' : 'Open →'}
          </button>
        </div>
      )}
    </span>
  );
}

const CITATION_RE = /\[\[Source:([a-f0-9]+)\]\]/g;

export function renderInlineCitations(
  text: string,
  sourceMap: Map<string, ReportSource>,
  onOpenWiki?: (pageName: string) => void
): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let counter = 0;

  CITATION_RE.lastIndex = 0;
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    const hash = match[1];
    const source = sourceMap.get(hash);
    counter++;

    if (source) {
      parts.push(<CitationRef key={`c-${match.index}`} index={counter} source={source} onOpenWiki={onOpenWiki} />);
    } else {
      parts.push(<span key={`c-${match.index}`} className="text-muted-foreground text-[10px]">[{counter}]</span>);
    }

    lastIndex = CITATION_RE.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length === 0 ? text : <>{parts}</>;
}