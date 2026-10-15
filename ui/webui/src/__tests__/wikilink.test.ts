import { describe, it, expect } from 'vitest';
import { wikilinkPreprocess, isWikiPageHref } from '../components/wiki/wikilink';

describe('wikilinkPreprocess', () => {
  it('converts simple [[page]] brackets', () => {
    const out = wikilinkPreprocess('see [[concepts/X]] here');
    expect(out).toContain('see [concepts/X](wiki-page://');
    expect(out).toContain(') here');
  });

  it('converts [[page|display]] syntax', () => {
    const out = wikilinkPreprocess('see [[concepts/X|the X]] here');
    expect(out).toContain('see [the X](wiki-page://');
    expect(out).toContain(') here');
  });

  it('skips inline code spans', () => {
    expect(wikilinkPreprocess('`[[ignored]]` but [[real]]')).toBe(
      '`[[ignored]]` but [real](wiki-page://real)',
    );
  });

  it('skips fenced code blocks', () => {
    const input = '```\n[[block]]\n```\nbut [[real]]';
    expect(wikilinkPreprocess(input)).toBe('```\n[[block]]\n```\nbut [real](wiki-page://real)');
  });

  it('preserves brackets with invalid chars', () => {
    expect(wikilinkPreprocess('[[bad<chars>]]')).toBe('[[bad<chars>]]');
  });

  it('returns empty string unchanged', () => {
    expect(wikilinkPreprocess('')).toBe('');
  });

  it('preserves URLs untouched', () => {
    expect(wikilinkPreprocess('see https://example.com and [[real]]')).toBe(
      'see https://example.com and [real](wiki-page://real)',
    );
  });

  it('roundtrips via isWikiPageHref', () => {
    const out = wikilinkPreprocess('see [[concepts/Alpha Decay]] here');
    const match = out.match(/wiki-page:\/\/([^)\s]+)/);
    expect(match).not.toBeNull();
    const decoded = isWikiPageHref(`wiki-page://${match![1]}`);
    expect(decoded).toBe('concepts/Alpha Decay');
  });
});

describe('isWikiPageHref', () => {
  it('decodes valid wiki-page URLs', () => {
    expect(isWikiPageHref('wiki-page://concepts%2FX')).toBe('concepts/X');
  });

  it('returns null for non-wiki hrefs', () => {
    expect(isWikiPageHref('https://example.com')).toBeNull();
    expect(isWikiPageHref('')).toBeNull();
    expect(isWikiPageHref(null)).toBeNull();
    expect(isWikiPageHref(undefined)).toBeNull();
  });
});