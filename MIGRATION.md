# Migration Guide: v0.11.0 → v0.11.1

## Breaking Changes

### Zero Domain Assumption Fix

**v0.11.0**: Default exclusion patterns were preset  
**v0.11.1**: All exclusion patterns are empty by default

---

## What Changed?

| Setting | v0.11.0 | v0.11.1 |
|---------|---------|---------|
| `default_exclude_patterns` | `[日期，月份，季度]` | `[]` |
| `exclude_frontmatter` | `["redirect_to"]` | `[]` |
| `archive_directories` | `["archive", "logs", "history"]` | `[]` |

---

## How to Migrate

If you relied on default exclusions, add them to your `.wiki-config.yaml`:

```yaml
orphan_detection:
  # Date-based pages (if you use them)
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Dates: 2025-07-31
    - '^\d{4}-\d{2}$'        # Months: 2025-07
    - '^\d{4}-q[1-4]$'       # Quarters: 2025-Q1 (case-insensitive)
  
  # Custom redirect convention (if you use it)
  exclude_frontmatter:
    - 'redirect_to'
  
  # Archive directories (if you use them)
  archive_directories:
    - 'archive'
    - 'logs'
    - 'history'
```

---

## Why This Change?

llmwikify is a **general-purpose tool** that makes no domain assumptions.

Previous defaults assumed:
- ❌ Date-based pages (not all wikis have them)
- ❌ English directory names (cultural bias)
- ❌ Custom `redirect_to` convention (not standardized, Obsidian incompatible)

Now all exclusions must be **explicitly configured** by users.

---

## Examples

### Example 1: Personal Knowledge Base

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'      # Daily journal
    - '^book-note-.*'            # Book notes
  archive_directories:
    - 'journal'
    - 'archive'
```

### Example 2: Project Documentation

```yaml
orphan_detection:
  exclude_patterns:
    - '^release-.*'              # Release notes
    - '^meeting-.*'              # Meeting notes
  archive_directories:
    - 'releases'
    - 'meetings'
```

### Example 3: Research Wiki

```yaml
orphan_detection:
  exclude_patterns:
    - '^experiment-.*'           # Experiment logs
    - '^paper-note-.*'           # Paper notes
  archive_directories:
    - 'experiments'
    - 'papers'
```

---

## Need Help?

See `.wiki-config.yaml.example` for detailed configuration options and examples.
