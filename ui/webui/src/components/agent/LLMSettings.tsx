import { useState, useEffect, useCallback, type ChangeEvent } from 'react';
import { api, LLMConfig } from '../../api';
import { useToast } from '../wiki/Toast';
import { Button } from '../ui/legacy-button';
import { Panel } from '../ui/Panel';
import { Select } from '../ui/native-select';
import { Toggle } from '../ui/Toggle';
import { Card } from '../ui/legacy-card';

const PROVIDERS = [
  // LAL (PR 4): provider id renamed from `minimax` to `minimax`.
  { value: 'minimax', label: 'MiniMax' },
  { value: 'xiaomi', label: 'Xiaomi MiMo' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'lmstudio', label: 'LM Studio' },
];

const MODEL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  // LAL (PR 4): model names lowercased to match the canonical
  // server-side identifiers.
  minimax: [
    { value: 'minimax-M3', label: 'minimax-M3' },
    { value: 'minimax-M2.7', label: 'minimax-M2.7' },
    { value: 'minimax-M2.7-highspeed', label: 'minimax-M2.7-highspeed' },
    { value: 'minimax-M2.5', label: 'minimax-M2.5' },
    { value: 'minimax-M2.5-highspeed', label: 'minimax-M2.5-highspeed' },
    { value: 'minimax-M2.1', label: 'minimax-M2.1' },
    { value: 'minimax-M2.1-highspeed', label: 'minimax-M2.1-highspeed' },
    { value: 'minimax-M2', label: 'minimax-M2' },
  ],
  openai: [
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4o-mini', label: 'GPT-4o mini' },
    { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
    { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
  ],
  ollama: [
    { value: 'llama3', label: 'Llama 3' },
    { value: 'llama3.1', label: 'Llama 3.1' },
    { value: 'mistral', label: 'Mistral' },
    { value: 'mixtral', label: 'Mixtral' },
    { value: 'qwen2', label: 'Qwen 2' },
  ],
  lmstudio: [
    { value: 'local-model', label: 'Local Model' },
  ],
  xiaomi: [
    { value: 'mimo-v2.5-pro', label: 'MiMo-V2.5 Pro' },
    { value: 'mimo-v2.5', label: 'MiMo-V2.5 Omni' },
    { value: 'mimo-v2-flash', label: 'MiMo-V2 Flash' },
    { value: 'mimo-v2-pro', label: 'MiMo-V2 Pro' },
    { value: 'mimo-v2-omni', label: 'MiMo-V2 Omni' },
  ],
};

const BASE_URL_DEFAULTS: Record<string, string> = {
  minimax: 'https://api.minimaxi.com/v1',
  xiaomi: 'https://token-plan-cn.xiaomimimo.com/v1',
  openai: 'https://api.openai.com/v1',
  ollama: 'http://localhost:11434/v1',
  lmstudio: 'http://localhost:1234/v1',
};

// LAL (PR 4): EMPTY_CONFIG represents the *unconfigured* state.
// Previously it carried a default provider/model/api_key,
// which gave the impression that LLM was already wired up.
// Now the fields are blank and the UI shows a "未配置"
// banner until the user explicitly saves a real config.
const EMPTY_CONFIG: LLMConfig = {
  enabled: true,
  provider: '',
  model: '',
  base_url: '',
  api_key: '',
  timeout: 120,
};

function maskDisplay(apiKey: string): string {
  if (!apiKey) return '';
  if (apiKey.startsWith('env:')) return apiKey;
  if (apiKey.length > 8) return apiKey.slice(0, 4) + '***' + apiKey.slice(-4);
  return '***';
}

export function LLMSettings() {
  const [config, setConfig] = useState<LLMConfig>(EMPTY_CONFIG);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showApiKey, setShowApiKey] = useState(false);
  const [apiKeyMode, setApiKeyMode] = useState<'direct' | 'env'>('direct');
  const [originalApiKey, setOriginalApiKey] = useState('');
  const { addToast } = useToast();

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.agent.getConfig();
        setConfig(data);
        setOriginalApiKey(data.api_key);
        if (data.api_key.startsWith('env:')) {
          setApiKeyMode('env');
        }
      } catch {
        setConfig(EMPTY_CONFIG);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleProviderChange = useCallback((e: ChangeEvent<HTMLSelectElement>) => {
    const provider = e.target.value;
    const defaultUrl = BASE_URL_DEFAULTS[provider] || '';
    const models = MODEL_OPTIONS[provider] || [];
    setConfig((prev) => ({
      ...prev,
      provider,
      base_url: defaultUrl,
      model: models[0]?.value || '',
    }));
  }, []);

  const handleApiKeyChange = useCallback((rawValue: string) => {
    const val = apiKeyMode === 'env'
      ? (rawValue.startsWith('env:') ? rawValue : `env:${rawValue}`)
      : rawValue;
    setConfig((prev) => ({ ...prev, api_key: val }));
    setOriginalApiKey(val);
  }, [apiKeyMode]);

  const handleSave = useCallback(async () => {
    if (config.api_key && config.api_key.includes('***')) {
      if (!window.confirm('API Key appears to be masked (contains ***). The real key will be preserved.\n\nIf you need to change the key, paste the new real key first.\n\nProceed with save?')) {
        return;
      }
    }
    setSaving(true);
    try {
      await api.agent.saveConfig(config);
      try {
        await api.agent.reloadConfig();
        addToast('success', 'LLM settings saved and reloaded');
      } catch {
        addToast('info', 'Settings saved — will reload on next request');
      }
    } catch (e) {
      addToast('error', `Failed to save: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setSaving(false);
    }
  }, [config, addToast]);

  const displayApiKey = maskDisplay(config.api_key);
  const inputValue = apiKeyMode === 'env' && config.api_key.startsWith('env:')
    ? config.api_key
    : (config.api_key || '');

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Panel border="top">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-primary">LLM Settings</h2>
        </div>
      </Panel>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-2xl space-y-6">
          <Card variant="bordered" padding="md">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">Enable LLM</span>
                <Toggle
                  checked={config.enabled}
                  onChange={(checked) => setConfig((prev) => ({ ...prev, enabled: checked }))}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1.5">Provider</label>
                  <Select
                    value={config.provider}
                    onChange={handleProviderChange}
                    options={PROVIDERS}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1.5">Model</label>
                  <Select
                    value={config.model}
                    onChange={(e) => setConfig((prev) => ({ ...prev, model: e.target.value }))}
                    options={MODEL_OPTIONS[config.provider] || []}
                    className="w-full"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs text-muted-foreground mb-1.5">Base URL</label>
                <input
                  type="text"
                  value={config.base_url}
                  onChange={(e) => setConfig((prev) => ({ ...prev, base_url: e.target.value }))}
                  className="w-full bg-card border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/40"
                />
              </div>

              <div>
                <label className="block text-xs text-muted-foreground mb-1.5">API Key</label>
                <div className="flex items-center gap-2 mb-2">
                  <button
                    onClick={() => setApiKeyMode('direct')}
                    className={`text-xs px-2 py-1 rounded ${apiKeyMode === 'direct' ? 'bg-primary/20 text-primary' : 'text-muted-foreground'}`}
                  >
                    Direct
                  </button>
                  <button
                    onClick={() => setApiKeyMode('env')}
                    className={`text-xs px-2 py-1 rounded ${apiKeyMode === 'env' ? 'bg-primary/20 text-primary' : 'text-muted-foreground'}`}
                  >
                    env:VAR_NAME
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    value={inputValue}
                    onChange={(e) => handleApiKeyChange(e.target.value)}
                    placeholder={apiKeyMode === 'env' ? 'env:MY_API_KEY' : 'sk-...'}
                    className="w-full bg-card border border-border rounded-md px-3 py-2 pr-20 text-sm text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/40"
                  />
                  <button
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground hover:text-primary"
                  >
                    {showApiKey ? 'Hide' : 'Show'}
                  </button>
                </div>
                {originalApiKey && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {originalApiKey.includes('***') ? (
                      <span className="text-yellow-500">Key is masked — real key is preserved on save. Paste new key to change.</span>
                    ) : (
                      <span>Current: {displayApiKey}</span>
                    )}
                  </div>
                )}
              </div>

              <div>
                <label className="block text-xs text-muted-foreground mb-1.5">Timeout (seconds)</label>
                <input
                  type="number"
                  value={config.timeout}
                  onChange={(e) => setConfig((prev) => ({ ...prev, timeout: parseInt(e.target.value) || 120 }))}
                  min={10}
                  max={300}
                  className="w-full bg-card border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/40"
                />
              </div>
            </div>
          </Card>

          <div className="flex items-center gap-2">
            <Button onClick={handleSave} disabled={saving || !config.enabled} variant="primary">
              {saving ? 'Saving...' : 'Save & Reload'}
            </Button>
          </div>

          <div className="text-xs text-muted-foreground space-y-1">
            <p>Config stored globally at <code className="bg-muted px-1 rounded">~/.llmwikify/llmwikify.json</code></p>
            <p>Per-wiki config overrides: <code className="bg-muted px-1 rounded">.wiki-config.yaml</code></p>
          </div>
        </div>
      </div>
    </div>
  );
}