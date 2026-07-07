import { ComponentPropsWithoutRef, MouseEvent, useMemo } from 'react';
import ReactMarkdown, { Components } from 'react-markdown';
import type { Pluggable } from 'unified';
import remarkGfm from 'remark-gfm';
import { useNavigate } from 'react-router-dom';
import { isWikiPageHref, wikilinkPreprocess } from './wikilink';

type AnchorProps = ComponentPropsWithoutRef<'a'>;

interface WikiMarkdownProps {
  source: string;
  remarkPlugins?: Pluggable[];
  className?: string;
}

export function WikiMarkdown({ source, remarkPlugins, className }: WikiMarkdownProps) {
  const navigate = useNavigate();
  const processed = useMemo(() => wikilinkPreprocess(source ?? ''), [source]);

  const components: Components = useMemo(() => ({
    a: ({ href, children, onClick, ...rest }: AnchorProps & { onClick?: (e: MouseEvent<HTMLAnchorElement>) => void }) => {
      const page = isWikiPageHref(href);
      if (page) {
        return (
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              navigate(`/edit?page=${encodeURIComponent(page)}`);
            }}
            className="text-primary hover:underline cursor-pointer"
            data-wikilink={page}
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
  }), [navigate]);

  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins ?? [remarkGfm]}
        components={components}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}