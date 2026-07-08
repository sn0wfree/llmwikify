import { ComponentPropsWithoutRef, MouseEvent, useCallback, useMemo } from 'react';
import ReactMarkdown, { Components, defaultUrlTransform } from 'react-markdown';
import type { Pluggable } from 'unified';
import remarkGfm from 'remark-gfm';
import { api } from '../../api';
import { isWikiPageHref, WIKILINK_SCHEME, wikilinkPreprocess } from './wikilink';

type AnchorProps = ComponentPropsWithoutRef<'a'>;
type ImageProps = ComponentPropsWithoutRef<'img'>;

interface WikiMarkdownProps {
  source: string;
  remarkPlugins?: Pluggable[];
  className?: string;
  wikiId?: string;
  onPageSelect?: (page: string) => void;
}

// Tight whitelist: only known-safe schemes are "external". data:, javascript:,
// file:, vbscript:, ftp: etc. all fall through to the internal-file branch
// (where urlTransform has already stripped them or the router rejects them).
function isExternalUrl(href: string): boolean {
  return /^(https?|mailto):/i.test(href);
}

export function WikiMarkdown({ source, remarkPlugins, className, wikiId, onPageSelect }: WikiMarkdownProps) {
  const processed = useMemo(() => wikilinkPreprocess(source ?? ''), [source]);

  const urlTransform = useCallback((url: string) => {
    if (url.startsWith(WIKILINK_SCHEME)) return url;
    return defaultUrlTransform(url);
  }, []);

  const components: Components = useMemo(() => ({
    a: ({ href, children, onClick, ...rest }: AnchorProps & { onClick?: (e: MouseEvent<HTMLAnchorElement>) => void }) => {
      const page = isWikiPageHref(href);
      if (page) {
        return (
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              onPageSelect?.(page);
            }}
            className="text-primary hover:underline cursor-pointer"
            data-wikilink={page}
            {...rest}
          >
            {children}
          </a>
        );
      }
      if (href && !isExternalUrl(href) && !href.startsWith('#') && !href.startsWith('?')) {
        const fileUrl = api.wiki.fileUrl(href, wikiId);
        return (
          <a
            href={fileUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onClick}
            {...rest}
          >
            {children}
          </a>
        );
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onClick}
          {...rest}
        >
          {children}
        </a>
      );
    },
    img: ({ src, alt, ...rest }: ImageProps) => {
      // Relative path (no http/mailto scheme) → route through wiki file API so
      // it hits the same Content-Disposition: inline handler as inline links.
      if (src && !isExternalUrl(src)) {
        return <img src={api.wiki.fileUrl(src, wikiId)} alt={alt} {...rest} />;
      }
      return <img src={src} alt={alt} {...rest} />;
    },
  }), [onPageSelect, wikiId]);

  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins ?? [remarkGfm]}
        components={components}
        urlTransform={urlTransform}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}