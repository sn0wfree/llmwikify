import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('API Client', () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn();
  });

  it('should throw error with message from response body', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ error: 'Internal server error' }),
    });

    const { api } = await import('../api');
    await expect(api.wiki.readPage('Test')).rejects.toThrow('Internal server error');
  });

  it('should throw error with status when body is not JSON', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 502,
      json: () => Promise.reject(new Error('Invalid JSON')),
    });

    const { api } = await import('../api');
    await expect(api.wiki.readPage('Test')).rejects.toThrow('API error: 502');
  });

  it('should return undefined for 204 response', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 204,
    });

    const { api } = await import('../api');
    const result = await api.agent.status();
    expect(result).toBeUndefined();
  });

  it('should parse JSON response on success', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ page_name: 'Test', content: 'Hello' }),
    });

    const { api } = await import('../api');
    const result = await api.wiki.readPage('Test');
    expect(result).toEqual({ page_name: 'Test', content: 'Hello' });
  });

  it('should use message field when error is present', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ message: 'Bad request' }),
    });

    const { api } = await import('../api');
    await expect(api.wiki.search('query')).rejects.toThrow('Bad request');
  });

  it('should use detail field when error is present', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: 'Validation failed' }),
    });

    const { api } = await import('../api');
    await expect(api.wiki.writePage('Test', 'content')).rejects.toThrow('Validation failed');
  });
});
