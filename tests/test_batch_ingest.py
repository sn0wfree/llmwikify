"""Tests for batch ingest command fix.

Tests for:
- Batch JSON output structure (agent-parseable)
- Multi-level directory scanning (rglob)
- --dry-run support
- stderr vs stdout separation
- User guidance messages
- Partial failure handling
- --self-create integration
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.cli import WikiCLI
from llmwikify.extractors import ExtractedContent


class Args:
    pass


# ============================================================
# Test 1: Batch JSON output structure
# ============================================================
class TestBatchJsonOutput:
    def test_batch_json_output_without_self_create(self, temp_wiki):
        """Without --self-create, stdout should contain valid JSON."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent here")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            result = cli.batch(args)

        assert result == 0
        stdout_content = stdout.getvalue()
        parsed = json.loads(stdout_content)
        assert 'batch_summary' in parsed
        assert 'results' in parsed
        assert 'message' in parsed
        assert parsed['batch_summary']['total'] >= 1
        assert parsed['batch_summary']['success'] >= 1
        assert parsed['batch_summary']['failed'] == 0


# ============================================================
# Test 2: Batch JSON fields
# ============================================================
class TestBatchJsonFields:
    def test_batch_result_has_required_fields(self, temp_wiki):
        """Each result should have required fields for agent processing."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nImportant content")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            cli.batch(args)

        parsed = json.loads(stdout.getvalue())
        assert len(parsed['results']) >= 1
        result = parsed['results'][0]
        required_fields = [
            'source_name', 'source_raw_path', 'source_type',
            'title', 'content', 'content_length', 'content_preview',
            'status', 'instructions',
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"
        assert result['status'] == 'extracted'


# ============================================================
# Test 3: stderr vs stdout separation
# ============================================================
class TestStderrStdoutSeparation:
    def test_summary_goes_to_stderr(self, temp_wiki):
        """Human-readable summary should go to stderr, not stdout."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            cli.batch(args)

        stderr_content = stderr.getvalue()
        assert 'Batch Ingest' in stderr_content
        assert 'Batch Complete' in stderr_content
        assert 'Success:' in stderr_content

        stdout_content = stdout.getvalue()
        assert 'Batch Ingest' not in stdout_content
        parsed = json.loads(stdout_content)
        assert 'batch_summary' in parsed


# ============================================================
# Test 4: Multi-level directory scanning
# ============================================================
class TestBatchMultiLevelDirs:
    def test_batch_scans_subdirectories(self, temp_wiki):
        """Batch should recursively scan subdirectories."""
        subdir = temp_wiki / 'raw' / 'subdir'
        subdir.mkdir(parents=True, exist_ok=True)
        (temp_wiki / 'raw' / 'root.md').write_text("# Root Document")
        (subdir / 'nested.md').write_text("# Nested Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            cli.batch(args)

        parsed = json.loads(stdout.getvalue())
        assert parsed['batch_summary']['total'] >= 2


# ============================================================
# Test 5: --dry-run support
# ============================================================
class TestBatchDryRun:
    def test_batch_dry_run_no_ingest(self, temp_wiki):
        """--dry-run should output JSON preview without calling ingest_source."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = True
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            with patch.object(cli.wiki, 'ingest_source', return_value={}) as mock_ingest:
                result = cli.batch(args)

        mock_ingest.assert_not_called()
        assert result == 0
        parsed = json.loads(stdout.getvalue())
        assert parsed['batch_summary']['dry_run'] is True
        assert len(parsed['results']) >= 1
        assert parsed['results'][0]['status'] == 'dry_run'

    def test_batch_dry_run_with_self_create(self, temp_wiki):
        """--dry-run --self-create should show LLM preview message."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = True
        args.smart = False
        args.dry_run = True
        args.limit = 0

        stderr = StringIO()
        with patch('sys.stdout', StringIO()), patch('sys.stderr', stderr):
            with patch.object(cli.wiki, 'ingest_source', return_value={}):
                cli.batch(args)

        stderr_content = stderr.getvalue()
        assert 'DRY RUN' in stderr_content
        assert 'self-create' in stderr_content.lower()


# ============================================================
# Test 6: Partial failure handling
# ============================================================
class TestBatchPartialFailure:
    def test_batch_partial_failure(self, temp_wiki):
        """Some sources fail, others succeed; JSON reflects per-source status."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        failing_file = temp_wiki / 'raw' / 'fail.txt'
        failing_file.write_text("binary-like content")

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        def mock_ingest(source):
            if 'fail' in source:
                return {'error': 'Extraction failed'}
            return {
                'source_name': 'test.md',
                'source_raw_path': 'raw/test.md',
                'source_type': 'markdown',
                'file_type': 'markdown',
                'title': 'Test Document',
                'content': '# Test Document\n\nContent',
                'content_length': 30,
                'content_preview': 'Test Document...',
                'word_count': 5,
                'file_size': 100,
                'has_images': False,
                'image_count': 0,
                'saved_to_raw': False,
                'already_exists': False,
                'hint': '',
                'instructions': '',
            }

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr), \
             patch.object(cli.wiki, 'ingest_source', side_effect=mock_ingest):
            result = cli.batch(args)

        parsed = json.loads(stdout.getvalue())
        assert parsed['batch_summary']['failed'] >= 1
        statuses = [r['status'] for r in parsed['results']]
        assert 'error' in statuses
        assert 'extracted' in statuses


# ============================================================
# Test 7: --self-create integration
# ============================================================
class TestBatchSelfCreate:
    def test_batch_self_create_processes_files(self, temp_wiki):
        """With --self-create, LLM processing should execute."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = True
        args.smart = False
        args.dry_run = False
        args.limit = 0

        ingest_result = {
            'source_name': 'test.md',
            'source_raw_path': 'raw/test.md',
            'source_type': 'markdown',
            'file_type': 'markdown',
            'title': 'Test Document',
            'content': '# Test Document\n\nContent',
            'content_length': 30,
            'content_preview': 'Test Document...',
            'word_count': 5,
            'file_size': 100,
            'has_images': False,
            'image_count': 0,
            'saved_to_raw': False,
            'already_exists': False,
            'hint': '',
        }

        llm_result = {
            'operations': [
                {'action': 'write_page', 'page_name': 'Test Document', 'content': '# Test Document'},
                {'action': 'log', 'operation': 'create', 'details': 'Created Test Document'},
            ],
            'relations': [],
        }

        exec_result = {
            'operations_executed': 2,
            'results': [
                {'status': 'done', 'action': 'write_page', 'page': 'Test Document'},
                {'status': 'done', 'action': 'log', 'operation': 'create'},
            ],
        }

        stderr = StringIO()
        with patch('sys.stdout', StringIO()), patch('sys.stderr', stderr), \
             patch.object(cli.wiki, 'ingest_source', return_value=ingest_result), \
             patch.object(cli.wiki, '_llm_process_source', return_value=llm_result), \
             patch.object(cli.wiki, 'execute_operations', return_value=exec_result):
            result = cli.batch(args)

        stderr_content = stderr.getvalue()
        assert 'operations executed' in stderr_content
        assert result == 0

    def test_batch_self_create_llm_failure(self, temp_wiki):
        """With --self-create, LLM failure should be handled gracefully."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = True
        args.smart = False
        args.dry_run = False
        args.limit = 0

        ingest_result = {
            'source_name': 'test.md',
            'source_raw_path': 'raw/test.md',
            'source_type': 'markdown',
            'title': 'Test Document',
            'content': '# Test Document',
            'content_length': 15,
            'content_preview': 'Test Document',
            'word_count': 2,
            'file_size': 50,
            'has_images': False,
            'image_count': 0,
            'saved_to_raw': False,
            'already_exists': False,
            'hint': '',
        }

        stderr = StringIO()
        with patch('sys.stdout', StringIO()), patch('sys.stderr', stderr), \
             patch.object(cli.wiki, 'ingest_source', return_value=ingest_result), \
             patch.object(cli.wiki, '_llm_process_source', side_effect=ConnectionError("LLM unavailable")):
            result = cli.batch(args)

        stderr_content = stderr.getvalue()
        assert 'LLM processing skipped' in stderr_content
        assert result == 0


# ============================================================
# Test 8: User guidance message
# ============================================================
class TestBatchUserGuidance:
    def test_user_guidance_shown_without_self_create(self, temp_wiki):
        """stderr should contain guidance message when pages not created."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stderr = StringIO()
        with patch('sys.stdout', StringIO()), patch('sys.stderr', stderr):
            cli.batch(args)

        stderr_content = stderr.getvalue()
        assert 'Pages were NOT created' in stderr_content
        assert '--self-create' in stderr_content
        assert 'parse the JSON output' in stderr_content


# ============================================================
# Test 9: Empty directory
# ============================================================
class TestBatchEmptyDirectory:
    def test_batch_empty_directory(self, temp_wiki):
        """Empty directory should return exit code 1."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        result = cli.batch(args)
        assert result == 1


# ============================================================
# Test 10: Glob pattern source
# ============================================================
class TestBatchGlobPattern:
    def test_batch_with_glob_pattern(self, temp_wiki):
        """Batch should support glob patterns as source."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        (temp_wiki / 'raw' / 'doc1.md').write_text("# Doc 1")
        (temp_wiki / 'raw' / 'doc2.md').write_text("# Doc 2")
        (temp_wiki / 'raw' / 'skip.txt').write_text("skip")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(temp_wiki / 'raw' / '*.md')
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            result = cli.batch(args)

        assert result == 0
        parsed = json.loads(stdout.getvalue())
        assert parsed['batch_summary']['total'] == 2
