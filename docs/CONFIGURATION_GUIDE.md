# Configuration Guide

**llmwikify** uses a flexible configuration system that allows you to customize behavior while maintaining zero core dependencies.

---

## 📋 Overview

Configuration is loaded in this priority order (highest to lowest):

1. **Programmatic config** - Dict passed to `Wiki()` or `create_wiki()`
2. **User config file** - `.wiki-config.yaml` in wiki root
3. **Built-in defaults** - Embedded in `config.py`

This design ensures:
- ✅ Zero dependencies (defaults are embedded)
- ✅ Easy customization (YAML file)
- ✅ Full control (programmatic API)

---

## 📁 Configuration Files

### .wiki-config.yaml.example

Located in the wiki root, this is a **template** with:
- All available configuration options
- Detailed comments
- Use case examples

**Copy and customize**:
```bash
cp .wiki-config.yaml.example .wiki-config.yaml
```

### .wiki-config.yaml

Your **actual configuration** (optional):
- Only include options you want to change
- Omitted options use defaults
- Fully documented in the example file

---

## ⚙️ Configuration Options

### 1. directories

Control the directory structure:

```yaml
directories:
  raw: "raw"   # Source files (PDFs, exports, etc.)
  wiki: "wiki" # Wiki pages (markdown files)
```

**Use case**: Organize sources differently
```yaml
directories:
  raw: "sources"
  wiki: "knowledge"
```

---

### 2. files

Configure file names:

```yaml
files:
  index: "index.md"  # Wiki index file
  log: "log.md"      # Activity log
```

---

### 3. database

Database configuration:

```yaml
database:
  name: ".llmwikify.db"
```

**Use case**: Multiple wikis with different databases
```yaml
database:
  name: ".research-notes.db"
```

---

### 4. reference_index

JSON export settings:

```yaml
reference_index:
  name: "reference_index.json"  # Export filename
  auto_export: true             # Auto-export after build
```

---

### 5. orphan_detection

Control which pages are excluded from orphan detection:

```yaml
orphan_detection:
  # Regex patterns for page names
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Dates (2025-07-31)
    - '^meeting-.*'          # Meeting notes
  
  # Frontmatter keys that mark exclusion
  exclude_frontmatter:
    - 'redirect_to'          # Redirect pages
    - 'template: true'       # Template pages
  
  # Directory names that indicate archives
  archive_directories:
    - 'archive'
    - 'logs'
    - 'old'
```

**Default patterns** (always applied):
- `^\d{4}-\d{2}-\d{2}$` - Dates
- `^\d{4}-\d{2}$` - Months
- `^\d{4}-Q[1-4]$` - Quarters

---

### 6. performance

Performance tuning:

```yaml
performance:
  batch_size: 100      # Files per batch during index build
  cache_size: 64000    # SQLite cache size in KB
```

**Tips**:
- Higher `batch_size` = faster but more memory
- `cache_size`: -1000 = 1MB, -64000 = 64MB

---

## 🎯 Use Case Examples

### Example 1: Personal Knowledge Base

```yaml
# Personal wiki with journal and book notes
database:
  name: ".personal-wiki.db"

orphan_detection:
  exclude_patterns:
    - '^journal-.*'
    - '^daily-.*'
    - '^book-note-.*'
  archive_directories:
    - 'archive'
    - 'old'
```

---

### Example 2: Project Documentation

```yaml
# Project docs with releases and meetings
database:
  name: ".project-docs.db"

orphan_detection:
  exclude_patterns:
    - '^release-.*'
    - '^changelog-.*'
    - '^meeting-.*'
  archive_directories:
    - 'releases'
    - 'meetings'
    - 'rfcs'
```

---

### Example 3: Research Wiki

```yaml
# Research notes with experiments and papers
database:
  name: ".research-notes.db"

directories:
  raw: "papers"
  wiki: "notes"

orphan_detection:
  exclude_patterns:
    - '^experiment-.*'
    - '^paper-note-.*'
  archive_directories:
    - 'experiments'
    - 'papers'
    - 'data'
```

---

### Example 4: Team Wiki

```yaml
# Team wiki with meeting notes and decisions
database:
  name: ".team-wiki.db"

orphan_detection:
  exclude_patterns:
    - '^meeting-.*'
    - '^decision-.*'
    - '^rfc-.*'
  archive_directories:
    - 'meetings'
    - 'decisions'
    - 'archive'
```

---

## 💻 Programmatic Configuration

For full control, pass config dict directly:

```python
from llmwikify import create_wiki

custom_config = {
    "database": {
        "name": ".custom.db"
    },
    "directories": {
        "raw": "sources",
        "wiki": "pages"
    },
    "orphan_detection": {
        "exclude_patterns": ["^draft-.*"]
    }
}

wiki = create_wiki("/path/to/wiki", config=custom_config)
```

---

## 🔍 Configuration Helpers

Use helper functions to work with configuration:

```python
from llmwikify import get_default_config, load_config
from pathlib import Path

# Get default config
default = get_default_config()
print(default['database']['name'])  # .llmwikify.db

# Load user config (merged with defaults)
wiki_root = Path("/path/to/wiki")
config = load_config(wiki_root)
print(config['database']['name'])  # From .wiki-config.yaml or default
```

---

## ⚠️ Troubleshooting

### Config file not loading?

**Check**:
1. File is named `.wiki-config.yaml` (not `.wiki-config.yml`)
2. File is in wiki root directory
3. YAML syntax is valid
4. PyYAML is installed: `pip install pyyaml`

### Changes not taking effect?

**Try**:
1. Restart Python interpreter
2. Check config priority (programmatic > file > defaults)
3. Verify YAML indentation
4. Use `get_default_config()` to see defaults

### Database name not changing?

**Check**:
1. Config is loaded **before** `Wiki()` initialization
2. `database.name` key is correct
3. No typos in YAML

---

## 📚 Related

- [Configuration System Design](../archive/reports/MODULARIZATION_REPORT.md)
- [Wiki Initialization](../README.md#initialization)
- [Orphan Detection Guide](./ORPHAN_DETECTION.md)

---

*Last updated: 2026-04-10 | Version: 0.11.0*
