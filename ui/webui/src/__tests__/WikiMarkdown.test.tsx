import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from './test-utils';
import { WikiMarkdown } from '../components/wiki/WikiMarkdown';

vi.mock('../api', () => ({
  api: {
    wiki: {
      fileUrl: (path: string, wikiId?: string) => {
        // Mirror the real fix: decode first (handles pre-encoded paths from
        // react-markdown's urlTransform), then re-encode once.
        let normalized = path;
        try { normalized = decodeURIComponent(path); } catch { normalized = path; }
        const segments = normalized.split('/').map((s) => encodeURIComponent(s)).join('/');
        return wikiId
          ? `/api/wiki/${wikiId}/file/${segments}`
          : `/api/wiki/file/${segments}`;
      },
    },
  },
}));

describe('WikiMarkdown', () => {
  describe('wikilinks', () => {
    it('renders [[Page]] as a wikilink anchor with data-wikilink', () => {
      const { container } = render(<WikiMarkdown source="see [[concepts/X]] here" />);
      const anchors = container.querySelectorAll('a[data-wikilink]');
      expect(anchors.length).toBe(1);
      expect(anchors[0].getAttribute('data-wikilink')).toBe('concepts/X');
      expect(anchors[0].textContent).toBe('concepts/X');
    });

    it('renders [[Page|label]] with display label', () => {
      const { container } = render(
        <WikiMarkdown source="see [[concepts/X|the X concept]] here" />,
      );
      const anchor = container.querySelector('a[data-wikilink]');
      expect(anchor).not.toBeNull();
      expect(anchor!.getAttribute('data-wikilink')).toBe('concepts/X');
      expect(anchor!.textContent).toBe('the X concept');
    });

    it('renders CJK wikilink targets', () => {
      const { container } = render(<WikiMarkdown source="看 [[中文页面]] 这里" />);
      const anchor = container.querySelector('a[data-wikilink]');
      expect(anchor).not.toBeNull();
      expect(anchor!.getAttribute('data-wikilink')).toBe('中文页面');
    });

    it('keeps [[Page]] as raw text when it has invalid characters', () => {
      // The regex allows /alphanum/dash/CJK/space/._; rejects < > etc.
      const { container } = render(<WikiMarkdown source="[[bad<chars>]]" />);
      const anchor = container.querySelector('a[data-wikilink]');
      expect(anchor).toBeNull();
      // Original text is preserved (no preprocessing applied)
      expect(container.textContent).toContain('[[bad<chars>]]');
    });

    it('does not preprocess inside fenced code blocks', () => {
      const md = '```\n[[block]]\n```\nbut [[real]]';
      const { container } = render(<WikiMarkdown source={md} />);
      const anchors = container.querySelectorAll('a[data-wikilink]');
      expect(anchors.length).toBe(1);
      expect(anchors[0].getAttribute('data-wikilink')).toBe('real');
    });

    it('does not preprocess inside inline code spans', () => {
      const md = '`[[not-a-link]]` but [[real]]';
      const { container } = render(<WikiMarkdown source={md} />);
      const anchors = container.querySelectorAll('a[data-wikilink]');
      expect(anchors.length).toBe(1);
      expect(anchors[0].getAttribute('data-wikilink')).toBe('real');
    });

    it('calls onPageSelect callback on click', () => {
      const onSelect = vi.fn();
      const { container } = render(
        <WikiMarkdown source="see [[Target]] here" onPageSelect={onSelect} />,
      );
      const anchor = container.querySelector('a[data-wikilink]')!;
      fireEvent.click(anchor);
      expect(onSelect).toHaveBeenCalledWith('Target');
    });

    it('href is "#" with cursor-pointer class to prevent default navigation', () => {
      const { container } = render(<WikiMarkdown source="[[Page]]" />);
      const anchor = container.querySelector('a[data-wikilink]')!;
      expect(anchor.getAttribute('href')).toBe('#');
      expect(anchor.className).toContain('cursor-pointer');
    });
  });

  describe('images (H2 fix)', () => {
    it('rewrites relative image src through fileUrl', () => {
      const { container } = render(
        <WikiMarkdown source="![alt](raw/test-pixel.png)" />,
      );
      const img = container.querySelector('img');
      expect(img).not.toBeNull();
      expect(img!.getAttribute('src')).toBe('/api/wiki/file/raw/test-pixel.png');
      expect(img!.getAttribute('alt')).toBe('alt');
    });

    it('preserves external https image src untouched', () => {
      const { container } = render(
        <WikiMarkdown source="![ext](https://placehold.co/50)" />,
      );
      const img = container.querySelector('img');
      expect(img!.getAttribute('src')).toBe('https://placehold.co/50');
    });

    it('blocks data: URL XSS via urlTransform (empty src)', () => {
      const { container } = render(
        <WikiMarkdown source="![xss](data:image/svg+xml,<svg/onload=alert(1)>)" />,
      );
      const imgs = container.querySelectorAll('img');
      // data: blocked by urlTransform → no img element or src empty
      const matching = Array.from(imgs).filter((i) => i.getAttribute('alt') === 'xss');
      for (const img of matching) {
        const src = img.getAttribute('src');
        expect(src === null || src === '').toBe(true);
      }
    });

    it('blocks javascript: URL in image src', () => {
      const { container } = render(
        <WikiMarkdown source="![js](javascript:alert(1))" />,
      );
      const imgs = container.querySelectorAll('img');
      const matching = Array.from(imgs).filter((i) => i.getAttribute('alt') === 'js');
      for (const img of matching) {
        const src = img.getAttribute('src');
        expect(src === null || src === '').toBe(true);
      }
    });

    it('routes CJK image paths via fileUrl (single-encoded, not double)', () => {
      const { container } = render(
        <WikiMarkdown source="![中文图](raw/中文.png)" />,
      );
      const img = container.querySelector('img');
      expect(img).not.toBeNull();
      const src = img!.getAttribute('src') || '';
      // urlTransform pre-encodes CJK; our handler should single-encode, not double
      expect(src.startsWith('/api/wiki/file/raw/')).toBe(true);
      expect(src).not.toContain('%25');
    });

    it('uses wikiId when provided for image src', () => {
      const { container } = render(
        <WikiMarkdown source="![alt](raw/test.png)" wikiId="strategy" />,
      );
      const img = container.querySelector('img');
      expect(img!.getAttribute('src')).toBe('/api/wiki/strategy/file/raw/test.png');
    });
  });

  describe('regular links', () => {
    it('rewrites relative file link through fileUrl', () => {
      const { container } = render(
        <WikiMarkdown source="[open](raw/report.pdf)" />,
      );
      const link = container.querySelector('a[href*="/api/wiki/file/"]');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('/api/wiki/file/raw/report.pdf');
      // Should open in new tab with rel=noopener
      expect(link!.getAttribute('target')).toBe('_blank');
      expect(link!.getAttribute('rel')).toContain('noopener');
    });

    it('preserves external https link', () => {
      const { container } = render(
        <WikiMarkdown source="[ext](https://example.com)" />,
      );
      const link = container.querySelector('a[href*="example.com"]');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('https://example.com');
    });

    it('blocks data: URL link via urlTransform (no anchor with raw data: href)', () => {
      const { container } = render(
        <WikiMarkdown source="[xss](data:text/html,<script>alert(1)</script>)" />,
      );
      const anchors = container.querySelectorAll('a');
      for (const a of anchors) {
        const href = a.getAttribute('href') || '';
        expect(href.startsWith('data:')).toBe(false);
      }
    });

    it('blocks javascript: link', () => {
      const { container } = render(
        <WikiMarkdown source="[js](javascript:alert(1))" />,
      );
      const anchors = container.querySelectorAll('a');
      for (const a of anchors) {
        const href = a.getAttribute('href') || '';
        expect(href.startsWith('javascript:')).toBe(false);
      }
    });

    it('preserves mailto link', () => {
      const { container } = render(
        <WikiMarkdown source="[email](mailto:user@example.com)" />,
      );
      const link = container.querySelector('a[href^="mailto:"]');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toBe('mailto:user@example.com');
    });

    it('preserves anchor link (#)', () => {
      const { container } = render(
        <WikiMarkdown source="[section](#section-1)" />,
      );
      const link = container.querySelector('a[href="#section-1"]');
      expect(link).not.toBeNull();
    });
  });

  describe('edge cases', () => {
    it('renders empty source without error', () => {
      const { container } = render(<WikiMarkdown source="" />);
      expect(container).toBeInTheDocument();
    });

    it('renders undefined source without error', () => {
      const { container } = render(<WikiMarkdown source={undefined as unknown as string} />);
      expect(container).toBeInTheDocument();
    });

    it('renders plain text without preprocessing artifacts', () => {
      const { container } = render(
        <WikiMarkdown source="just plain text without any links" />,
      );
      expect(container.querySelectorAll('a')).toHaveLength(0);
      expect(container.querySelectorAll('img')).toHaveLength(0);
      expect(container.textContent).toContain('just plain text');
    });

    it('renders GFM tables', () => {
      const md = '| Col A | Col B |\n| --- | --- |\n| 1 | 2 |';
      const { container } = render(<WikiMarkdown source={md} />);
      const table = container.querySelector('table');
      expect(table).not.toBeNull();
    });

    it('renders GFM strikethrough', () => {
      const { container } = render(<WikiMarkdown source="~~deleted~~" />);
      expect(container.querySelector('del')).not.toBeNull();
    });

    it('renders GFM task lists', () => {
      const md = '- [x] done\n- [ ] pending';
      const { container } = render(<WikiMarkdown source={md} />);
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      expect(checkboxes.length).toBe(2);
    });
  });
});
