# IN-8: Entity Resolution for Knowledge Graph Deduplication

## 问题背景

### 现状

当前 `RelationEngine.add_relation()` 使用精确匹配去重：

```python
# relation_engine.py:122-129
existing = self.index.conn.execute(
    "SELECT id FROM relations WHERE source=? AND target=? AND relation=? AND source_file=?",
    (source, target, relation, source_file),
).fetchone()
```

### 问题

不同文档提取关系时，会用不同的名称表述同一个实体：

| 文档 A | 文档 B | 结果 |
|--------|--------|------|
| "Risk Parity" | "risk parity strategy" | 重复关系 |
| "Diversification" | "Portfolio Diversification" | 重复关系 |
| "LLM" | "Large Language Model" | 重复关系 |

**根因**：关系层面去重无法解决实体名称不一致的问题。

## 设计目标

1. **实体层面规范化**：在插入关系前，先规范化实体名称
2. **利用现有结构**：使用 wiki 页面名作为规范名称
3. **可扩展**：支持人工维护和自动学习
4. **向后兼容**：不影响现有功能

## 核心设计

### 分层架构

```
Layer 1: Wiki 页面规范 (实时)
  ↓ 插入时查找 wiki 页面
  ↓ 命中则使用规范名称
  ↓ 未命中则进入 Layer 2

Layer 2: Alias 映射 (实时)
  ↓ 查找 alias 表
  ↓ 命中则使用规范名称
  ↓ 未命中则进入 Layer 3

Layer 3: 模糊匹配 (实时)
  ↓ 匹配现有实体
  ↓ 命中则添加 alias 并使用规范名称
  ↓ 未命中则作为新实体

Layer 4: 定期聚类 (离线，可选)
  ↓ 定期分析图结构
  ↓ 合并相似实体
  ↓ 更新 alias 表
```

### 数据库设计

```sql
-- 实体别名表
CREATE TABLE entity_aliases (
    id INTEGER PRIMARY KEY,
    alias TEXT NOT NULL UNIQUE,
    canonical TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT,  -- 来源 (manual, fuzzy_match, clustering)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_alias_lookup ON entity_aliases(alias);
CREATE INDEX idx_canonical ON entity_aliases(canonical);
```

### API 设计

#### 1. `resolve_entity(name: str) -> str`

规范化实体名称，返回规范名称。

```python
def resolve_entity(self, name: str) -> str:
    """Resolve entity name to canonical form.
    
    Resolution order:
    1. Exact match in wiki pages
    2. Alias lookup
    3. Fuzzy match against existing entities
    4. Return original name (new entity)
    """
```

#### 2. `add_alias(alias: str, canonical: str, source: str = "manual")`

添加实体别名映射。

```python
def add_alias(self, alias: str, canonical: str, source: str = "manual") -> None:
    """Add an alias mapping for an entity."""
```

#### 3. `get_aliases(canonical: str) -> list[str]`

获取实体的所有别名。

```python
def get_aliases(self, canonical: str) -> list[str]:
    """Get all aliases for a canonical entity name."""
```

#### 4. `merge_entities(source: str, target: str)`

合并两个实体（将 source 合并到 target）。

```python
def merge_entities(self, source: str, target: str) -> int:
    """Merge source entity into target.
    
    - Updates all relations from source to target
    - Adds source as alias of target
    - Returns count of affected relations
    """
```

### 集成点

#### 1. `write_relations()` (wiki_mixin_relation.py)

```python
def write_relations(self, relations: list, source_file: str | None = None) -> dict:
    engine = RelationEngine(self.index, wiki_root=self.root)
    
    # 新增：规范化实体名称
    for r in relations:
        r["source"] = engine.resolve_entity(r["source"])
        r["target"] = engine.resolve_entity(r["target"])
        if "source_file" not in r and source_file:
            r["source_file"] = source_file
    
    count = engine.add_relations(relations)
    return {"status": "completed", "count": count}
```

#### 2. `add_relation()` (relation_engine.py)

```python
def add_relation(self, source, target, relation, ...):
    # 规范化实体名称
    canonical_source = self.resolve_entity(source)
    canonical_target = self.resolve_entity(target)
    
    # 检查重复 (精确匹配，因为已规范化)
    existing = self.index.conn.execute(
        "SELECT id FROM relations WHERE source=? AND target=? AND relation=?",
        (canonical_source, canonical_target, relation),
    ).fetchone()
    
    if existing:
        return existing[0]
    
    # 插入关系 (使用规范名称)
    cursor = self.index.conn.execute(
        "INSERT INTO relations (source, target, relation, ...) VALUES (?, ?, ?, ...)",
        (canonical_source, canonical_target, relation, ...),
    )
    return cursor.lastrowid
```

### 模糊匹配算法

使用 SequenceMatcher 计算相似度：

```python
from difflib import SequenceMatcher

def _fuzzy_match_entity(self, name: str, candidates: list[str], threshold: float = 0.85) -> str | None:
    """Find best fuzzy match among candidates."""
    best_match = None
    best_score = 0
    
    for candidate in candidates:
        score = SequenceMatcher(None, name.lower(), candidate.lower()).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate
    
    return best_match
```

### 配置选项

```python
# 默认配置
DEFAULT_CONFIG = {
    "entity_resolution": {
        "enabled": True,
        "fuzzy_threshold": 0.85,  # 模糊匹配阈值
        "auto_alias": True,       # 自动添加 alias
        "case_sensitive": False,  # 大小写敏感
    }
}
```

## 实现步骤

### Phase 1: 基础设施 (本次实现)

1. 创建 `entity_aliases` 表
2. 实现 `resolve_entity()` 方法
3. 实现 `add_alias()` 和 `get_aliases()` 方法
4. 集成到 `write_relations()`
5. 更新测试

### Phase 2: 高级功能 (后续迭代)

1. 实现 `merge_entities()` 方法
2. 实现定期聚类算法
3. 添加 CLI 工具管理 alias
4. 添加 Web UI 管理 alias

## 测试计划

### 单元测试

1. `test_resolve_entity_exact_match` - 精确匹配 wiki 页面
2. `test_resolve_entity_alias_lookup` - alias 查找
3. `test_resolve_entity_fuzzy_match` - 模糊匹配
4. `test_add_alias` - 添加 alias
5. `test_get_aliases` - 获取 alias
6. `test_dedup_after_resolution` - 规范化后去重

### 集成测试

1. `test_write_relations_with_resolution` - 写入关系时规范化
2. `test_ingest_with_dedup` - ingest 流程去重

## 预估

- 核心实现: ~100 行代码
- 测试: ~80 行代码
- 总计: ~180 行代码

## 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 模糊匹配误判 | 实体被错误合并 | 设置高阈值 + 人工审核 |
| 性能开销 | 插入变慢 | 可配置关闭模糊匹配 |
| 向后兼容 | 现有数据受影响 | 渐进式迁移 |
