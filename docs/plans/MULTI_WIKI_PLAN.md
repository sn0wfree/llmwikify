# Multi-Wiki Management System - Implementation Plan

> **Version**: 0.31.0 | **Status**: Draft | **Date**: 2026-05-24

---

## 1. Architecture Overview

### Current State (Single Wiki)

```
User → WikiServer → Wiki(root) → WikiIndex(db_path)
                                  → wiki_dir/ (markdown files)
```

### Target State (Multi-Wiki)

```
User → WikiServer → WikiRegistry
                    ├── WikiInstance("project-a", Wiki("/path/a"))
                    ├── WikiInstance("project-b", Wiki("/path/b"))
                    └── WikiInstance("remote-x", RemoteWiki("http://..."))
```

**Core Principle**: `Wiki` class is unchanged. Multi-wiki is managed by a new `WikiRegistry` layer above it.

---

## 2. File Change List

### 2.1 New Files (Backend)

| File | Purpose |
|------|---------|
| `src/llmwikify/core/wiki_registry.py` | WikiRegistry - manages multiple Wiki instances |
| `src/llmwikify/core/wiki_instance.py` | WikiInstance dataclass - wraps Wiki with metadata |
| `src/llmwikify/core/remote_wiki.py` | RemoteWiki - HTTP client for remote wiki servers |
| `src/llmwikify/core/wiki_discovery.py` | WikiDiscovery - local directory scan + config registration |
| `src/llmwikify/core/cross_wiki_search.py` | CrossWikiSearch - federated search across wikis |
| `tests/test_multi_wiki.py` | Multi-wiki integration tests |
| `tests/test_remote_wiki.py` | Remote wiki client tests |

### 2.2 Modified Files (Backend)

| File | Change Summary |
|------|---------------|
| `src/llmwikify/config.py` | Add `wikis:` config section, `WikiRegistryConfig` |
| `.wiki-config.yaml.example` | Add `wikis:` section documentation |
| `src/llmwikify/server/core.py` | WikiServer accepts WikiRegistry instead of single Wiki |
| `src/llmwikify/server/http/routes.py` | Add `wiki_id` path param, new multi-wiki endpoints |
| `src/llmwikify/mcp/adapter.py` | MCPAdapter wraps WikiRegistry |
| `src/llmwikify/mcp/tools.py` | Add `wiki_id` param to MCP tools |
| `src/llmwikify/__init__.py` | Export WikiRegistry, create_multi_wiki() |
| `src/llmwikify/cli/commands.py` | Add `wikis` subcommand, update `serve` for multi-wiki |

### 2.3 New Files (Frontend)

| File | Purpose |
|------|---------|
| `src/llmwikify/web/webui/src/stores/wikiStore.ts` | Global wiki state (Zustand) |
| `src/llmwikify/web/webui/src/components/WikiSelector.tsx` | Wiki dropdown/switcher |
| `src/llmwikify/web/webui/src/components/WikiManager.tsx` | Wiki management panel |
| `src/llmwikify/web/webui/src/components/CrossWikiSearch.tsx` | Federated search component |

### 2.4 Modified Files (Frontend)

| File | Change Summary |
|------|---------------|
| `src/llmwikify/web/webui/src/api.ts` | Add wiki_id to all API calls, new endpoints |
| `src/llmwikify/web/webui/src/App.tsx` | Integrate WikiSelector, pass wiki context |
| `src/llmwikify/web/webui/src/components/SearchBar.tsx` | Support cross-wiki search |
| `src/llmwikify/web/webui/src/components/Editor.tsx` | Pass wiki_id to API calls |
| `src/llmwikify/web/webui/src/components/PageTree.tsx` | Fetch pages per wiki |
| `src/llmwikify/web/webui/package.json` | Add zustand dependency |

---

## 3. API Design

### 3.1 New Endpoints (Multi-Wiki)

```
GET    /api/wikis                           # List all registered wikis
POST   /api/wikis                           # Register a new wiki
GET    /api/wikis/{wiki_id}                 # Get wiki details
PUT    /api/wikis/{wiki_id}                 # Update wiki config
DELETE /api/wikis/{wiki_id}                 # Unregister wiki
POST   /api/wikis/{wiki_id}/reload         # Reload wiki (re-scan)
GET    /api/wikis/{wiki_id}/health          # Wiki health check

GET    /api/search/cross                    # Cross-wiki search
POST   /api/wikis/scan                      # Trigger directory scan
```

### 3.2 Modified Endpoints (Add `wiki_id`)

All existing endpoints gain a `wiki_id` path parameter:

```
# Before:
GET    /api/wiki/status
GET    /api/wiki/search?q=...
GET    /api/wiki/page/{page_name}
POST   /api/wiki/page
GET    /api/wiki/sink/status
GET    /api/wiki/lint
GET    /api/wiki/recommend
GET    /api/wiki/suggest_synthesis
GET    /api/wiki/graph_analyze
GET    /api/wiki/graph

# After:
GET    /api/wiki/{wiki_id}/status
GET    /api/wiki/{wiki_id}/search?q=...
GET    /api/wiki/{wiki_id}/page/{page_name}
POST   /api/wiki/{wiki_id}/page
GET    /api/wiki/{wiki_id}/sink/status
GET    /api/wiki/{wiki_id}/lint
GET    /api/wiki/{wiki_id}/recommend
GET    /api/wiki/{wiki_id}/suggest_synthesis
GET    /api/wiki/{wiki_id}/graph_analyze
GET    /api/wiki/{wiki_id}/graph

# Legacy (backward compatible):
GET    /api/wiki/status                     # → uses default wiki
GET    /api/wiki/search?q=...               # → uses default wiki
```

### 3.3 Response Schemas

**GET /api/wikis** — List all wikis:
```json
{
  "wikis": [
    {
      "wiki_id": "project-a",
      "name": "Project A",
      "root": "/path/to/project-a",
      "type": "local",
      "status": "ready",
      "page_count": 142,
      "last_accessed": "2026-05-24T10:30:00Z",
      "url": null
    },
    {
      "wiki_id": "remote-docs",
      "name": "Remote Docs",
      "root": null,
      "type": "remote",
      "status": "ready",
      "page_count": 89,
      "last_accessed": "2026-05-24T09:15:00Z",
      "url": "http://wiki-server:8765"
    }
  ],
  "default_wiki_id": "project-a"
}
```

**POST /api/wikis** — Register wiki:
```json
// Request
{
  "wiki_id": "new-project",
  "name": "New Project",
  "root": "/path/to/new-project",
  "type": "local"
}

// Or remote:
{
  "wiki_id": "remote-docs",
  "name": "Remote Docs",
  "url": "http://wiki-server:8765",
  "type": "remote",
  "api_key": "optional-key"
}
```

**GET /api/search/cross** — Cross-wiki search:
```
Query params:
  q: string          # Search query
  limit: int = 10    # Results per wiki
  wikis: string      # Comma-separated wiki_ids (empty = all)
  backend: string = "fts5"

Response:
{
  "results": [
    {
      "wiki_id": "project-a",
      "wiki_name": "Project A",
      "page_name": "Factor Investing",
      "score": 0.95,
      "snippet": "...**factor** investing strategies...",
      "content_length": 2340
    }
  ],
  "total_results": 15,
  "searched_wikis": ["project-a", "remote-docs"]
}
```

---

## 4. Database Schema

### 4.1 Registry Database (New)

Path: `{config_dir}/llmwikify-registry.db`

```sql
-- Registered wikis
CREATE TABLE IF NOT EXISTS wikis (
    wiki_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT,              -- NULL for remote wikis
    wiki_type TEXT NOT NULL DEFAULT 'local',  -- 'local' | 'remote'
    url TEXT,                    -- NULL for local wikis
    api_key TEXT,                -- encrypted, for remote wikis
    config_json TEXT,            -- serialized wiki config
    is_default BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP
);

-- Scan history (for local wikis)
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wiki_id TEXT NOT NULL,
    scan_type TEXT NOT NULL,     -- 'auto' | 'manual' | 'startup'
    pages_found INTEGER,
    pages_added INTEGER,
    pages_updated INTEGER,
    errors INTEGER,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wiki_id) REFERENCES wikis(wiki_id)
);

-- Cross-wiki link mappings (future: inter-wiki references)
CREATE TABLE IF NOT EXISTS cross_wiki_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_wiki_id TEXT NOT NULL,
    source_page TEXT NOT NULL,
    target_wiki_id TEXT,
    target_page TEXT NOT NULL,
    link_type TEXT DEFAULT 'reference',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_wiki_id) REFERENCES wikis(wiki_id),
    FOREIGN KEY (target_wiki_id) REFERENCES wikis(wiki_id)
);
```

### 4.2 Per-Wiki Database (Unchanged)

Each wiki keeps its existing `.llmwikify.db` with FTS5 tables. No modifications needed.

---

## 5. Configuration System Design

### 5.1 Extended `.wiki-config.yaml`

```yaml
# ============================================================================
# Multi-Wiki Configuration
# ============================================================================

wikis:
  # Default wiki ID (used when no wiki_id specified in API calls)
  default: "project-a"

  # Local wiki definitions (discovered via directory scan)
  local:
    # Explicit registration (optional — scan discovers them too)
    - id: "project-a"
      name: "Project A"
      path: "."                           # relative to config file or absolute
      # Optional overrides:
      # auto_discover: true               # scan for .wiki-config.yaml files

    - id: "project-b"
      name: "Project B"
      path: "/path/to/project-b"

  # Remote wiki definitions
  remote:
    - id: "remote-docs"
      name: "Remote Documentation"
      url: "http://wiki-server:8765"
      api_key: "${WIKI_DOCS_API_KEY}"     # env var expansion
      timeout: 30                         # seconds
      cache_ttl: 300                      # seconds (for read caching)

    - id: "team-wiki"
      name: "Team Wiki"
      url: "https://wiki.example.com:8765"
      api_key: "sk-..."
      verify_ssl: true

  # Discovery settings
  discovery:
    enabled: true
    scan_paths:                           # directories to scan for wikis
      - "."
      - "../"
      - "~/wikis"
    scan_depth: 2                         # max depth for recursive scan
    exclude_patterns:                     # directories to skip
      - "node_modules"
      - ".git"
      - "__pycache__"
    auto_register: false                  # auto-register discovered wikis
    scan_interval: 3600                   # re-scan interval (seconds), 0 = manual only
```

### 5.2 Config File Location Priority

```
1. CLI flag: --config /path/to/config
2. Environment: LLMWIKIFY_CONFIG=/path/to/config
3. Current directory: ./.wiki-config.yaml
4. User home: ~/.llmwikify/config.yaml
5. Built-in defaults
```

### 5.3 Environment Variable Expansion

In config values, `${ENV_VAR}` syntax is expanded:
```yaml
remote:
  - id: "secure-wiki"
    api_key: "${WIKI_API_KEY}"    # reads from os.environ
```

---

## 6. Backend Implementation Details

### 6.1 WikiInstance Dataclass

```python
# src/llmwikify/core/wiki_instance.py

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from datetime import datetime

class WikiType(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"

class WikiStatus(str, Enum):
    READY = "ready"
    LOADING = "loading"
    ERROR = "error"
    OFFLINE = "offline"     # remote wiki unreachable

@dataclass
class WikiInstance:
    """Wraps a Wiki with registry metadata."""
    wiki_id: str
    name: str
    wiki_type: WikiType
    root: Path | None               # None for remote
    url: str | None = None          # None for local
    api_key: str | None = None
    is_default: bool = False
    status: WikiStatus = WikiStatus.READY
    page_count: int = 0
    last_accessed: datetime | None = None
    config: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "wiki_id": self.wiki_id,
            "name": self.name,
            "type": self.wiki_type.value,
            "root": str(self.root) if self.root else None,
            "url": self.url,
            "status": self.status.value,
            "page_count": self.page_count,
            "is_default": self.is_default,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "error": self.error,
        }
```

### 6.2 WikiRegistry

```python
# src/llmwikify/core/wiki_registry.py

class WikiRegistry:
    """Manages multiple Wiki instances with discovery and lifecycle."""

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._instances: dict[str, WikiInstance] = {}
        self._wiki_objects: dict[str, Wiki] = {}  # lazy-loaded
        self._remote_clients: dict[str, RemoteWiki] = {}
        self._registry_db: sqlite3.Connection | None = None
        self._default_wiki_id: str | None = None

    # --- Lifecycle ---
    def initialize(self) -> None:
        """Load registry from DB, discover local wikis, connect remote."""

    def close(self) -> None:
        """Close all Wiki instances and registry DB."""

    # --- Wiki Management ---
    def register_wiki(self, wiki_id: str, name: str, root: Path,
                      wiki_type: WikiType = WikiType.LOCAL, **kwargs) -> WikiInstance:
        """Register a new wiki."""

    def unregister_wiki(self, wiki_id: str) -> None:
        """Remove wiki from registry."""

    def get_wiki(self, wiki_id: str) -> Wiki:
        """Get Wiki object by ID (lazy-loaded)."""

    def get_wiki_instance(self, wiki_id: str) -> WikiInstance:
        """Get WikiInstance metadata."""

    def list_wikis(self) -> list[WikiInstance]:
        """List all registered wikis."""

    def get_default_wiki(self) -> Wiki:
        """Get the default wiki instance."""

    # --- Discovery ---
    def scan_directories(self, scan_paths: list[str], depth: int = 2) -> list[WikiInstance]:
        """Scan directories for .wiki-config.yaml files."""

    def register_remote(self, wiki_id: str, name: str, url: str,
                        api_key: str | None = None, **kwargs) -> WikiInstance:
        """Register a remote wiki."""

    # --- Cross-Wiki Operations ---
    def cross_wiki_search(self, query: str, wiki_ids: list[str] | None = None,
                          limit: int = 10) -> list[dict]:
        """Search across multiple wikis, merge and rank results."""

    def get_wiki_status(self, wiki_id: str) -> dict:
        """Get detailed status for a wiki."""

    def reload_wiki(self, wiki_id: str) -> dict:
        """Re-index a wiki (rebuild FTS5)."""
```

### 6.3 RemoteWiki Client

```python
# src/llmwikify/core/remote_wiki.py

class RemoteWiki:
    """HTTP client for remote llmwikify server."""

    def __init__(self, url: str, api_key: str | None = None, timeout: int = 30):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session: requests.Session | None = None

    def _get_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health(self) -> dict:
        """Check remote server health."""

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search remote wiki."""

    def read_page(self, page_name: str) -> dict:
        """Read a page from remote wiki."""

    def get_status(self) -> dict:
        """Get remote wiki status."""

    def get_graph(self, **kwargs) -> dict:
        """Get graph data from remote wiki."""
```

### 6.4 WikiDiscovery Scanner

```python
# src/llmwikify/core/wiki_discovery.py

class WikiDiscovery:
    """Scans directories for llmwikify wikis."""

    CONFIG_FILENAME = ".wiki-config.yaml"

    def scan(self, scan_paths: list[str], depth: int = 2,
             exclude: list[str] | None = None) -> list[dict]:
        """Scan paths for wiki roots.

        Returns list of {root: Path, config: dict, wiki_id: str}
        """

    def _find_config_files(self, root: Path, depth: int,
                           exclude: list[str]) -> list[Path]:
        """Recursively find .wiki-config.yaml files."""

    def _extract_wiki_id(self, config: dict, root: Path) -> str:
        """Generate wiki_id from config or directory name."""
```

---

## 7. Frontend Architecture Design

### 7.1 State Management (Zustand)

```typescript
// src/llmwikify/web/webui/src/stores/wikiStore.ts

import { create } from 'zustand';

interface WikiInfo {
  wiki_id: string;
  name: string;
  type: 'local' | 'remote';
  root: string | null;
  url: string | null;
  status: 'ready' | 'loading' | 'error' | 'offline';
  page_count: number;
  is_default: boolean;
}

interface WikiState {
  // State
  wikis: WikiInfo[];
  currentWikiId: string | null;
  loading: boolean;
  error: string | null;

  // Actions
  loadWikis: () => Promise<void>;
  switchWiki: (wikiId: string) => void;
  registerWiki: (wiki: Partial<WikiInfo>) => Promise<void>;
  unregisterWiki: (wikiId: string) => Promise<void>;
  scanWikis: () => Promise<void>;

  // Derived
  currentWiki: () => WikiInfo | undefined;
  wikiIds: () => string[];
}
```

### 7.2 Component Architecture

```
App
├── WikiSelector (dropdown in sidebar header)
├── Sidebar
│   ├── NavButtons (Editor, Dashboard, Insights, ...)
│   ├── PageTree (filtered by currentWikiId)
│   └── HealthStatus (per-wiki)
├── TopBar
│   ├── CrossWikiSearch (replaces SearchBar when multiple wikis)
│   └── Notifications
└── MainContent
    ├── Editor (uses currentWikiId)
    ├── KnowledgeGrowth (per-wiki)
    ├── Insights (per-wiki)
    └── WikiManager (new view, manages all wikis)
```

### 7.3 Key Components

**WikiSelector** — Dropdown in sidebar header:
```tsx
// Shows current wiki name, click to switch
// When >1 wiki: shows dropdown list
// "+" button to register new wiki
// Remote wikis show connection status indicator
```

**CrossWikiSearch** — Enhanced search bar:
```tsx
// Toggle: "This Wiki" vs "All Wikis"
// Results grouped by wiki with wiki badge
// Click result → switch to that wiki + open page
```

**WikiManager** — New dashboard view:
```tsx
// List all wikis with status
// Register new wiki (local path or remote URL)
// Trigger scan, reload, health check
// Set default wiki
// Remove wiki from registry
```

### 7.4 API Client Changes

```typescript
// All existing API calls become wiki-scoped:

// Before:
api.wiki.search(query)
api.wiki.readPage(pageName)
api.wiki.status()

// After:
api.wiki.search(wikiId, query)
api.wiki.readPage(wikiId, pageName)
api.wiki.status(wikiId)

// New:
api.wikis.list()
api.wikis.register({...})
api.wikis.unregister(wikiId)
api.wikis.scan()
api.search.cross(query, wikiIds?)
```

---

## 8. Backward Compatibility Strategy

### 8.1 Single Wiki Mode (Zero Config)

When no `wikis:` section exists in config:
1. `WikiRegistry` creates a single wiki from the existing `Wiki(root)` path
2. Wiki ID defaults to directory name (e.g., `"my-project"`)
3. API routes work **without** `wiki_id` — the default wiki is used
4. Frontend works identically to current version

### 8.2 Legacy API Routes

```python
# In routes.py:

# New multi-wiki routes
@wiki_router.get("/{wiki_id}/status")
async def wiki_status_by_id(wiki_id: str):
    wiki = registry.get_wiki(wiki_id)
    return wiki.status()

# Legacy fallback (no wiki_id)
@wiki_router.get("/status")
async def wiki_status_legacy():
    wiki = registry.get_default_wiki()
    return wiki.status()
```

This means all existing API clients continue to work without changes.

### 8.3 Migration Path

```
Phase 1: Single wiki, no config changes needed
Phase 2: Add wikis: section to config → multi-wiki activated
Phase 3: Old single-wiki API routes deprecated (but still functional)
Phase 4: Old routes removed in v0.32.0
```

---

## 9. Implementation Phases

### Phase 1: Core Registry (Week 1-2)

**Goal**: Backend multi-wiki management, backward compatible

1. Create `WikiInstance` dataclass
2. Create `WikiRegistry` with SQLite-backed persistence
3. Create `WikiDiscovery` scanner
4. Create `RemoteWiki` HTTP client
5. Add `wikis:` config section to `config.py`
6. Write unit tests for registry, discovery, remote client

**Files created/modified**:
- `core/wiki_instance.py` (new)
- `core/wiki_registry.py` (new)
- `core/wiki_discovery.py` (new)
- `core/remote_wiki.py` (new)
- `config.py` (modified)
- `tests/test_multi_wiki.py` (new)
- `tests/test_remote_wiki.py` (new)

### Phase 2: API Layer (Week 2-3)

**Goal**: Multi-wiki REST API endpoints

1. Add `wiki_id` parameter to existing routes
2. Create `/api/wikis` CRUD endpoints
3. Create `/api/search/cross` endpoint
4. Update `WikiServer` to accept `WikiRegistry`
5. Maintain backward compatibility for legacy routes
6. Write API integration tests

**Files created/modified**:
- `server/core.py` (modified)
- `server/http/routes.py` (modified, split into `routes_wiki.py` + `routes_multi.py`)

### Phase 3: Frontend Multi-Wiki (Week 3-4)

**Goal**: UI for wiki switching and management

1. Add zustand dependency
2. Create `wikiStore.ts` global state
3. Create `WikiSelector` component
4. Create `CrossWikiSearch` component
5. Create `WikiManager` panel
6. Update all components to use wiki context
7. Write frontend tests

**Files created/modified**:
- `web/webui/src/stores/wikiStore.ts` (new)
- `web/webui/src/components/WikiSelector.tsx` (new)
- `web/webui/src/components/WikiManager.tsx` (new)
- `web/webui/src/components/CrossWikiSearch.tsx` (new)
- `web/webui/src/App.tsx` (modified)
- `web/webui/src/api.ts` (modified)
- `web/webui/src/components/SearchBar.tsx` (modified)
- `web/webui/src/components/Editor.tsx` (modified)

### Phase 4: MCP Integration (Week 4-5)

**Goal**: MCP tools support multi-wiki

1. Add `wiki_id` parameter to all MCP tools
2. Update `MCPAdapter` to wrap `WikiRegistry`
3. Add `list_wikis` MCP tool
4. Add `switch_wiki` MCP tool
5. Write MCP integration tests

**Files created/modified**:
- `mcp/adapter.py` (modified)
- `mcp/tools.py` (modified)

### Phase 5: CLI & Polish (Week 5-6)

**Goal**: CLI commands, documentation, edge cases

1. Add `llmwikify wikis list` command
2. Add `llmwikify wikis add` command
3. Add `llmwikify wikis remove` command
4. Add `llmwikify wikis scan` command
5. Update `llmwikify serve` for multi-wiki mode
6. Update `.wiki-config.yaml.example` with wikis section
7. Update ARCHITECTURE.md
8. Update README.md

**Files created/modified**:
- `cli/commands.py` (modified)
- `.wiki-config.yaml.example` (modified)
- `ARCHITECTURE.md` (modified)

---

## 10. Test Strategy

### 10.1 Unit Tests

**test_multi_wiki.py**:
```python
class TestWikiRegistry:
    def test_register_local_wiki(tmp_path):
        """Register a local wiki from path."""

    def test_register_remote_wiki():
        """Register a remote wiki from URL."""

    def test_unregister_wiki():
        """Remove wiki from registry."""

    def test_get_default_wiki():
        """Default wiki returns correctly."""

    def test_switch_default():
        """Change default wiki."""

    def test_persistence():
        """Wikis survive registry restart."""

class TestWikiDiscovery:
    def test_scan_single_wiki(tmp_path):
        """Discover a single wiki in directory."""

    def test_scan_nested_wikis(tmp_path):
        """Discover wikis at different depths."""

    def test_exclude_patterns(tmp_path):
        """Respect exclude patterns."""

    def test_extract_wiki_id():
        """Generate wiki_id from config or dir name."""

class TestRemoteWiki:
    def test_health_check():
        """Remote server health check."""

    def test_search():
        """Search remote wiki."""

    def test_read_page():
        """Read page from remote wiki."""

    def test_timeout_handling():
        """Graceful handling of timeouts."""

    def test_auth_headers():
        """API key sent in headers."""

class TestCrossWikiSearch:
    def test_search_single_wiki():
        """Search in one wiki."""

    def test_search_all_wikis():
        """Search across all wikis."""

    def test_merge_results():
        """Results merged and ranked correctly."""

    def test_empty_results():
        """Handle no results gracefully."""
```

### 10.2 Integration Tests

**test_api_multi_wiki.py** (in `tests/e2e/`):
```python
class TestMultiWikiAPI:
    def test_list_wikis():
        """GET /api/wikis returns all wikis."""

    def test_register_wiki():
        """POST /api/wikis registers new wiki."""

    def test_wiki_scoped_status():
        """GET /api/wiki/{id}/status returns wiki status."""

    def test_legacy_status():
        """GET /api/wiki/status still works (backward compat)."""

    def test_cross_wiki_search():
        """GET /api/search/cross returns federated results."""

    def test_switch_default_wiki():
        """PUT /api/wikis/{id} changes default."""
```

### 10.3 Frontend Tests

```typescript
// WikiSelector.test.tsx
describe('WikiSelector', () => {
  it('renders current wiki name');
  it('shows dropdown with all wikis');
  it('switches wiki on selection');
  it('shows "+" button for adding wiki');
  it('displays remote wiki status indicator');
});

// CrossWikiSearch.test.tsx
describe('CrossWikiSearch', () => {
  it('searches current wiki by default');
  it('toggles to cross-wiki search');
  it('groups results by wiki');
  it('switches wiki when clicking remote result');
});

// wikiStore.test.ts
describe('wikiStore', () => {
  it('loads wikis on init');
  it('switches current wiki');
  it('registers new wiki');
  it('unregisters wiki');
});
```

### 10.4 Test Configuration

```python
# tests/conftest.py additions

@pytest.fixture
def multi_wiki_registry(tmp_path):
    """Create a registry with 2 test wikis."""
    wiki_a = tmp_path / "wiki-a"
    wiki_b = tmp_path / "wiki-b"
    wiki_a.mkdir()
    wiki_b.mkdir()
    # Initialize both wikis
    Wiki(wiki_a).init()
    Wiki(wiki_b).init()
    # Create registry
    config = {"wikis": {"default": "wiki-a"}}
    registry = WikiRegistry(config)
    registry.register_wiki("wiki-a", "Wiki A", wiki_a)
    registry.register_wiki("wiki-b", "Wiki B", wiki_b)
    yield registry
    registry.close()

@pytest.fixture
def mock_remote_wiki():
    """Mock RemoteWiki for testing."""
    with patch('llmwikify.core.remote_wiki.RemoteWiki') as mock:
        mock.return_value.search.return_value = [
            {"page_name": "test", "score": 0.9, "snippet": "test content"}
        ]
        yield mock
```

---

## 11. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Registry DB corruption | Auto-recreate from config on startup |
| Remote wiki unreachable | Offline status, cached results, graceful degradation |
| Performance with many wikis | Lazy loading, connection pooling, search timeout |
| Config conflicts | Single source of truth: `.wiki-config.yaml` |
| Breaking existing users | Zero-config backward compatibility, legacy API routes |
| Thread safety | Registry uses thread lock for wiki instance access |

---

## 12. Dependencies

### Backend
- `pyyaml` (existing) — config parsing
- `requests` (existing) — remote wiki HTTP client
- No new Python dependencies needed

### Frontend
- `zustand` (new) — lightweight state management (~1KB)
- No other new dependencies

---

## 13. Versioning

| Version | Changes |
|---------|---------|
| 0.31.0 | Phase 1-2: Core registry + API |
| 0.31.1 | Phase 3: Frontend multi-wiki UI |
| 0.31.2 | Phase 4: MCP integration |
| 0.32.0 | Phase 5: CLI + deprecate legacy routes |

---

*Plan created: 2026-05-24 | Target: v0.31.0*
