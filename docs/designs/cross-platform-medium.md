# 跨平台部署兼容性修复（中优 8 项）

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应跨平台审查中优

## 修复项

### 1. git post-commit hook 平台分支（中）

原实现只写 `#!/bin/sh` + `chmod 0o755`。Windows 原生 Git 依赖
sh 脚本，无 POSIX shell 时 hook 不执行；NTFS 也无执行位概念。

**修复**：同时写 `post-commit`（POSIX）与 `post-commit.bat`（原生 cmd）；
`chmod` 保留（Windows 上无害）。`uninstall_git_hook` 改为清理两个变体，
且不误删用户自己的 hook。

### 2. `_slugify` 未过滤 Windows 保留名（中）

标题为 `con` / `prn` / `aux` / `nul` / `com1-9` / `lpt1-9` 时，
生成的 `.md` 在 Windows 上无法打开。尾随点/空格同样非法。

**修复**：`_WINDOWS_RESERVED_NAMES` 集合 + 尾随点空格剥离，
命中则追加 `-` 后缀。

### 3. worktree 路径比较大小写敏感（中）

`str(target).startswith(str(root) + os.sep)` 在大小写不敏感的文件系统
（Windows/macOS）上会误拒合法路径；Glob 的 `..` 检查只 split `/`。

**修复**：新增 `_is_within()`，用 `os.path.normcase` 对齐宿主文件系统
的大小写语义；Glob 的 `..` 检查改 `re.split(r"[\\/]", pattern)`。

### 4. Grep 硬依赖 ripgrep（中）

Windows 未装 `rg` 时 Grep 直接返回错误，功能不可用。

**修复**：新增 `_grep_fallback()` 纯 Python 扫描（ripgrep 缺失时自动
启用），输出形状与 ripgrep 路径一致，且同样剥掉 worktree 前缀。

### 5. `subprocess` 解码未指定 encoding（中）

`text=True` 按 locale 解码，中文路径/内容可解码失败。

**修复**：`subprocess.run` 补 `encoding="utf-8", errors="replace"`。

### 6. `resolve_by_name` 无大小写回退（中）

SQL 精确匹配，Windows 上 `Concepts/Foo` 与 `concepts/foo` 与 FS
行为不一致。

**修复**：精确匹配未命中时回退 `COLLATE NOCASE` 查询（保留原精确
语义优先）。

### 7. CLI emoji 在 GBK 控制台崩溃（中）

`print("✅ ...")` 在 Windows 默认代码页（GBK）下 `UnicodeEncodeError`。

**修复**（双保险）：
- `_app.main()` 入口统一 `sys.stdout/stderr.reconfigure(encoding="utf-8",
  errors="replace")` —— 覆盖所有直接 print
- `_output._emit()` 检测流编码，不可编码时降级为 ASCII 前缀
  （`[OK]` / `[X]` / `[!]` / `[i]`）

### 8. `scripts/*.sh` 硬编码路径（不改）

50 个 `.sh` 是针对特定 Linux 服务器的运维脚本（部署/探活/回滚），
不属包分发范围，不纳入跨平台修复。

## 验证

- 新增 `tests/test_cross_platform_medium.py`（31 tests）
- 相关回归与 stash 基线一致（8 failed 均为既存）
