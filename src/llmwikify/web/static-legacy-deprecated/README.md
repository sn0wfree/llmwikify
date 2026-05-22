# Legacy WebUI (Deprecated)

## Status
**Archived** - No longer maintained. Retained for reference only.

## Why Archived
This directory contains the original Vanilla JS implementation, which has been replaced by the React WebUI:

- **React WebUI** (`web/webui/`) provides component-based architecture
- Supports confirmation workflow, Dream proposals, and agent chat
- Full TypeScript type safety
- 38+ Vitest tests

## Files
- `index.html` - Legacy HTML page
- `css/app.css` - Legacy styles
- `js/app.js` - Main application logic (~500 lines)
- `js/graph.js` - D3.js graph visualization

## Usage
**Do not use this version.** Use React WebUI instead:

```bash
llmwikify serve --web
```

## Migration
The server now only loads `web/webui/dist/`. This archive is not referenced by any active code.
