# Reference Tracing & Build Index 讨论

**日期**: 2026-04-10  
**版本**: v0.11.0  
**状态**: 需要修复和优化  

---

## 📊 当前状态

### 测试失败分析

当前失败的测试 (18 个中有 8 个与 Reference Tracing 和 Build Index 相关):

```
FAILED tests/test_wiki_core.py::TestWiki::test_init
FAILED tests/test_wiki_core.py::TestWiki::test_append_log  
FAILED tests/test_wiki_core.py::TestWiki::test_should_exclude_orphan_dated_page
FAILED tests/test_wiki_core.py::TestWiki::test_should_exclude_orphan_user_config
FAILED tests/test_index.py::TestWikiIndex::test_get_inbound_links
FAILED tests/test_index.py::TestWikiIndex::test_get_outbound_links
FAILED tests/test_index.py::TestWikiIndex::test_export_json
FAILED tests/test_recommend.py::TestRecommend::test_recommend_orphan_pages
```

### 失败原因分类

#### A. 配置系统相关 (4 个)
- `test_init` - 期望特定的初始化行为
- `test_append_log` - 日志格式或路径问题
- `test_should_exclude_orphan_*` - 配置加载逻辑需要调整

#### B. Reference Tracing 核心问题 (4 个)
- `test_get_inbound_links` - 入站链接查询失败
- `test_get_outbound_links` - 出站链接查询失败
- `test_export_json` - JSON 导出结构问题
- `test_recommend_orphan_pages` - 孤立页检测逻辑

---

## 🔍 Reference Tracing 问题分析

### 当前实现

`core/index.py` 中的引用追踪流程：

```python
def upsert_page(self, page_name: str, content: str, file_path: str = ""):
    # 1. 解析 [[wikilinks]]
    links = self._parse_links(content, file_path)
    
    # 2. 删除旧链接
    self.conn.execute("DELETE FROM page_links WHERE source_page = ?", (page_name,))
    
    # 3. 插入新链接
    if links:
        self.conn.executemany(
            "INSERT INTO page_links (...) VALUES (?, ?, ?, ?, ?)",
            [(l['source_page'], l['target'], l['section'], l['display'], l['file_path']) 
             for l in links]
        )
```

### 问题诊断

#### 1. 链接解析逻辑

**当前实现**: `core/index.py:154-180`

```python
def _parse_links(self, content: str, file_path: str = "") -> List[dict]:
    pattern = r'\[\[([^\]]+)\]\]'
    links = []
    
    for match in re.finditer(pattern, content):
        link_text = match.group(1)
        parts = link_text.split('|')
        
        if len(parts) == 2:
            target_part = parts[0]
            display = parts[1]
        else:
            target_part = link_text
            display = target_part
        
        # Split target and section
        if '#' in target_part:
            target, section = target_part.split('#', 1)
            section = '#' + section
        else:
            target = target_part
            section = ''
        
        links.append({
            "source_page": Path(file_path).stem if file_path else "",
            "target": target.strip(),
            "section": section,
            "display": display.strip(),
            "file_path": file_path,
        })
    
    return links
```

**潜在问题**:
- 当 `file_path` 为空时，`source_page` 也为空
- 测试可能期望 `source_page` 总是有值
- 没有处理链接文本的空白字符

#### 2. 入站/出站链接查询

**当前实现**: `core/index.py:82-114`

```python
def get_inbound_links(self, page_name: str) -> List[dict]:
    cursor = self.conn.execute(
        """SELECT source_page, section, file_path
           FROM page_links
           WHERE target_page = ?
           ORDER BY created_at DESC""",
        (page_name,)
    )
    
    return [
        {
            "source": row['source_page'],
            "section": row['section'],
            "file": row['file_path'],
        }
        for row in cursor.fetchall()
    ]

def get_outbound_links(self, page_name: str) -> List[dict]:
    cursor = self.conn.execute(
        """SELECT target_page, section, display_text, file_path
           FROM page_links
           WHERE source_page = ?
           ORDER BY created_at DESC""",
        (page_name,)
    )
    
    return [
        {
            "target": row['target_page'],
            "section": row['section'],
            "display": row['display_text'],
            "file": row['file_path'],
        }
        for row in cursor.fetchall()
    ]
```

**潜在问题**:
- 测试可能期望不同的返回字段名
- 排序可能导致结果顺序不同
- 空结果的处理

#### 3. JSON 导出

**当前实现**: `core/index.py:233-266`

```python
def export_json(self, output_path: Path) -> dict:
    data = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": self.get_page_count(),
        "outbound_links": {},
        "inbound_links": {},
        "summary": {
            "pages_with_outbound": 0,
            "pages_with_inbound": 0,
        },
    }
    
    # Get all outbound links
    cursor = self.conn.execute(
        """SELECT DISTINCT source_page FROM page_links"""
    )
    pages_with_outbound = set(row[0] for row in cursor.fetchall())
    data["summary"]["pages_with_outbound"] = len(pages_with_outbound)
    
    for page in pages_with_outbound:
        data["outbound_links"][page] = self.get_outbound_links(page)
    
    # Get all inbound links
    cursor = self.conn.execute(
        """SELECT DISTINCT target_page FROM page_links"""
    )
    pages_with_inbound = set(row[0] for row in cursor.fetchall())
    data["summary"]["pages_with_inbound"] = len(pages_with_inbound)
    
    for page in pages_with_inbound:
        data["inbound_links"][page] = self.get_inbound_links(page)
    
    output_path.write_text(json.dumps(data, indent=2))
    
    data["json_export"] = str(output_path)
    return data
```

**潜在问题**:
- 测试可能期望特定的 JSON 结构
- 空数据的处理
- 时间戳格式

---

## 🏗️ Build Index 问题分析

### 当前实现

`core/index.py:182-231`

```python
def build_index_from_files(self, wiki_dir: Path, batch_size: int = 100) -> dict:
    import time
    start_time = time.time()
    
    # Clear existing index
    self.conn.execute("DELETE FROM pages_fts")
    self.conn.execute("DELETE FROM page_links")
    self.conn.execute("DELETE FROM pages")
    
    # Process all markdown files
    md_files = list(wiki_dir.glob("*.md"))
    total = len(md_files)
    
    for i, md_file in enumerate(md_files):
        if (i + 1) % batch_size == 0 or (i + 1) == total:
            elapsed = time.time() - start_time
            speed = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"\r  Processing: {i+1}/{total} ({(i+1)/total*100:.1f}%) - {speed:.1f} files/sec", end='', flush=True)
        
        content = md_file.read_text()
        page_name = md_file.stem
        rel_path = str(md_file.relative_to(wiki_dir))
        
        self.upsert_page(page_name, content, rel_path)
    
    print()  # New line after progress
    
    elapsed = time.time() - start_time
    speed = total / elapsed if elapsed > 0 else 0
    
    return {
        "total_pages": total,
        "total_links": self.get_link_count(),
        "processed": total,
        "errors": 0,
        "elapsed_seconds": round(elapsed, 2),
        "files_per_second": round(speed, 1),
    }
```

### 性能分析

**优势**:
- ✅ 批量处理 (batch_size 参数)
- ✅ 进度报告
- ✅ 性能统计
- ✅ 当前速度：~2,833 文件/秒

**潜在问题**:
- ❌ 每次重建都清空所有数据（低效）
- ❌ 没有增量更新
- ❌ 没有缓存机制
- ❌ 没有错误处理（单个文件失败会中断整个流程）

---

## 💡 改进建议

### Reference Tracing 改进

#### 1. 链接解析增强

```python
def _parse_links(self, content: str, file_path: str = "") -> List[dict]:
    pattern = r'\[\[([^\]]+)\]\]'
    links = []
    source_page = Path(file_path).stem if file_path else "unknown"
    
    for match in re.finditer(pattern, content):
        link_text = match.group(1).strip()
        
        # Handle [[target|display]] or [[target#section|display]]
        parts = link_text.split('|')
        target_part = parts[0].strip()
        display = parts[1].strip() if len(parts) == 2 else target_part
        
        # Handle [[target#section]]
        if '#' in target_part:
            target, section = target_part.split('#', 1)
            section = '#' + section
        else:
            target = target_part
            section = ''
        
        links.append({
            "source_page": source_page,
            "target": target.strip(),
            "section": section,
            "display": display,
            "file_path": file_path,
        })
    
    return links
```

#### 2. 增量更新支持

```python
def upsert_page_incremental(self, page_name: str, content: str, file_path: str) -> bool:
    """Check if update is needed before processing."""
    # Check if page exists and content is unchanged
    cursor = self.conn.execute(
        "SELECT content_length FROM pages WHERE page_name = ?",
        (page_name,)
    )
    row = cursor.fetchone()
    
    if row and len(content) == row[0]:
        # Content unchanged, skip update
        return False
    
    # Content changed, perform full update
    self.upsert_page(page_name, content, file_path)
    return True
```

#### 3. 错误处理

```python
def build_index_from_files(self, wiki_dir: Path, batch_size: int = 100) -> dict:
    errors = []
    
    for i, md_file in enumerate(md_files):
        try:
            content = md_file.read_text()
            page_name = md_file.stem
            rel_path = str(md_file.relative_to(wiki_dir))
            self.upsert_page(page_name, content, rel_path)
        except Exception as e:
            errors.append({
                "file": str(md_file),
                "error": str(e),
            })
    
    return {
        "total_pages": total,
        "total_links": self.get_link_count(),
        "processed": total - len(errors),
        "errors": len(errors),
        "error_details": errors,
        # ... other stats
    }
```

### Build Index 改进

#### 1. 增量构建

```python
def build_index_incremental(self, wiki_dir: Path) -> dict:
    """Only process files that changed since last build."""
    # Load last build manifest
    manifest_path = wiki_dir / ".build_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {}
    
    changed_files = []
    for md_file in wiki_dir.glob("*.md"):
        stat = md_file.stat()
        file_hash = hash((str(md_file), stat.st_mtime, stat.st_size))
        
        if md_file.stem not in manifest or manifest[md_file.stem] != file_hash:
            changed_files.append(md_file)
            manifest[md_file.stem] = file_hash
    
    # Only process changed files
    for md_file in changed_files:
        content = md_file.read_text()
        page_name = md_file.stem
        rel_path = str(md_file.relative_to(wiki_dir))
        self.upsert_page(page_name, content, rel_path)
    
    # Save updated manifest
    manifest_path.write_text(json.dumps(manifest, indent=2))
    
    return {
        "total_pages": self.get_page_count(),
        "processed": len(changed_files),
        "unchanged": len(list(wiki_dir.glob("*.md"))) - len(changed_files),
    }
```

#### 2. 并发处理

```python
def build_index_parallel(self, wiki_dir: Path, workers: int = 4) -> dict:
    """Build index using multiple workers."""
    from concurrent.futures import ThreadPoolExecutor
    
    md_files = list(wiki_dir.glob("*.md"))
    
    def process_file(md_file):
        content = md_file.read_text()
        page_name = md_file.stem
        rel_path = str(md_file.relative_to(wiki_dir))
        return (page_name, content, rel_path)
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(process_file, md_files))
    
    # Batch insert
    for page_name, content, rel_path in results:
        self.upsert_page(page_name, content, rel_path)
```

---

## 📝 下一步行动

### 必须修复 (Must Fix)

1. **修复链接解析** - 确保 `source_page` 总是有值
2. **修复查询逻辑** - 确保入站/出站链接返回正确格式
3. **修复测试** - 适配配置系统变更

### 短期改进 (Short-term)

1. **增量更新** - 只处理变化的文件
2. **错误处理** - 单个文件失败不影响整体
3. **构建缓存** - 避免重复处理未变化的文件

### 长期优化 (Long-term)

1. **并发处理** - 多线程/多进程构建
2. **索引压缩** - 减少磁盘占用
3. **索引验证** - 自动检测和修复损坏的索引

---

## 🤔 讨论问题

### 1. 引用格式支持

当前支持:
- `[[Page Name]]` ✅
- `[[Page|Display Text]]` ✅
- `[[Page#section]]` ✅
- `[[Page#section|Display]]` ✅

**需要支持更多吗？**
- `[[Page>Alias]]` (Obsidian 别名)
- `[[Page#^block-id]]` (块引用)
- 嵌入链接 `![[Page]]`

### 2. 索引后端

当前：SQLite FTS5

**需要考虑其他后端吗？**
- Elasticsearch (大规模)
- MeiliSearch (快速搜索)
- Whoosh (纯 Python)
- 保持 SQLite (简单够用)

### 3. 增量策略

**选项**:
- A) 基于文件修改时间
- B) 基于文件内容哈希
- C) 基于用户标记
- D) 混合策略

**建议**: B (内容哈希) - 最可靠

### 4. 索引文件格式

当前导出：JSON

**需要其他格式吗？**
- JSON Lines (流式处理)
- MessagePack (二进制，更小)
- SQLite (直接查询)
- 保持 JSON (人类可读，Obsidian 兼容)

---

## 📊 性能目标

### 当前性能

| 指标 | 数值 |
|------|------|
| 157 页构建 | 0.06s |
| 处理速度 | 2,833 文件/秒 |
| 内存占用 | 低 |

### 目标性能 (v0.12.0)

| 指标 | 目标 | 改进 |
|------|------|------|
| 1000 页构建 | <0.5s | 增量更新 |
| 10000 页构建 | <5s | 并发处理 |
| 内存占用 | +10% | 可接受 |

---

## ✅ 测试修复清单

- [ ] `test_wiki_core.py::test_init` - 检查初始化逻辑
- [ ] `test_wiki_core.py::test_append_log` - 检查日志格式
- [ ] `test_wiki_core.py::test_should_exclude_orphan_dated_page` - 配置加载
- [ ] `test_wiki_core.py::test_should_exclude_orphan_user_config` - 配置优先级
- [ ] `test_index.py::test_get_inbound_links` - 链接查询
- [ ] `test_index.py::test_get_outbound_links` - 链接查询
- [ ] `test_index.py::test_export_json` - JSON 结构
- [ ] `test_recommend.py::test_recommend_orphan_pages` - 孤立页检测

---

*待讨论完成后更新*
