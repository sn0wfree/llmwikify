# 08 — 章节级双向引用 (section anchor tracking)

> 对应 [docs/TUTORIAL.md §Part 3 — 功能 Playbook 索引 (08 section_anchor_tracking)](../../docs/TUTORIAL.md#part-3--功能-playbook-索引)

## 跑法

```bash
cd examples/08_section_anchor_tracking
PYTHONPATH=../.. python3 play.py
```

## 目标

REFERENCE_TRACKING_GUIDE.md §数据格式 提到 `[[page#section]]` 章节级引用,
但 5 个 playbook 都只演示了 `[[page]]` page 级。8 个 playbook 补这个缺口。

## 支持的 wikilink 语法

| 语法 | 含义 |
|---|---|
| `[[page]]` | 页面级链接 |
| `[[page\|display]]` | 页面级 + 显示文本 |
| `[[page#section]]` | 章节级 (e.g. `[[python-style#Naming]]`) |
| `[[page#section\|display]]` | 章节级 + 显示文本 |

## 索引存储

`page_links` 表 (kernel/storage/index.py):

| column | type | 说明 |
|---|---|---|
| `source_page` | TEXT | 源页 |
| `target_page` | TEXT | 目标页 |
| `section` | TEXT (nullable) | 章节锚, e.g. `#Naming` |
| `display_text` | TEXT (nullable) | 显示文本 (e.g. `the naming section`) |
| `file_path` | TEXT | 源页相对路径 |

每个 link 一行, 通过 `section` 字段区分 page-level vs section-level。

## 涉及 API

- `wiki.write_page(name, content)` — 写页面
- `wiki.build_index()` — 重建索引
- `wiki.get_inbound_links(page, include_context=True)` — 谁引用了我
- `wiki.get_outbound_links(page)` — 我引用了谁
- `wiki.fix_wikilinks(dry_run=True)` — 修复 broken wikilink (rename 时)

## 预期输出 (节选)

```
=== Step 5: get_inbound_links('python-style') ===
   from coding-notes section='#Naming' display=''
   from coding-notes section='#Imports' display=''
   from coding-notes section='#Overview' display=''
   from team-wiki section='#Naming' display='the naming section'
   from team-wiki section='#Imports' display=''

=== Step 7: get_outbound_links('team-wiki') ===
   → python-style section='#Naming' display='the naming section'
   → python-style section='#Imports' display='python-style#Imports'
```

注意 `display` 字段在无 `|disp` 时回退到 `target` (parser 行为)。

## 对应 TUTORIAL

- **REFERENCE_TRACKING_GUIDE.md §数据格式** — section/anchor 引用格式定义
- **TUTORIAL.md §1.3** — page-level 双向引用 (本剧本扩展)
