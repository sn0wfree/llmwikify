/home/ll/.local/lib/python3.10/site-packages/pytest_asyncio/plugin.py:247: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the fixture caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to function scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))
============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-8.2.0, pluggy-1.5.0 -- /usr/bin/python3
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: /home/ll/llmwikify
configfile: pyproject.toml
plugins: base-url-2.1.0, cov-7.1.0, anyio-4.12.1, asyncio-1.3.0, playwright-0.7.2, hypothesis-6.155.6, mock-3.15.1, typeguard-4.2.1, dash-2.17.0
asyncio: mode=auto, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 46 items

tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_1_init_wiki PASSED [  2%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_2_write_page PASSED [  4%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_3_write_multiple_pages PASSED [  6%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_4_search PASSED [  8%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_5_build_index PASSED [ 10%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_6_bidirectional_links PASSED [ 13%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_7_lint PASSED [ 15%]
tests/scenarios/test_01_wiki_core.py::TestWikiCore::test_1_8_status PASSED [ 17%]
tests/scenarios/test_02_knowledge_graph.py::TestKnowledgeGraph::test_2_1_build_index PASSED [ 19%]
tests/scenarios/test_02_knowledge_graph.py::TestKnowledgeGraph::test_2_2_analyze_source SKIPPED [ 21%]
tests/scenarios/test_02_knowledge_graph.py::TestKnowledgeGraph::test_2_3_suggest_synthesis PASSED [ 23%]
tests/scenarios/test_02_knowledge_graph.py::TestKnowledgeGraph::test_2_4_knowledge_gaps_via_cli PASSED [ 26%]
tests/scenarios/test_02_knowledge_graph.py::TestKnowledgeGraph::test_2_5_graph_analyze_via_cli PASSED [ 28%]
tests/scenarios/test_02_knowledge_graph.py::TestKnowledgeGraph::test_2_6_export_graph_via_cli PASSED [ 30%]
tests/scenarios/test_03_multi_wiki.py::TestMultiWiki::test_3_1_register_wiki PASSED [ 32%]
tests/scenarios/test_03_multi_wiki.py::TestMultiWiki::test_3_2_list_wikis PASSED [ 34%]
tests/scenarios/test_03_multi_wiki.py::TestMultiWiki::test_3_3_switch_wiki PASSED [ 36%]
tests/scenarios/test_03_multi_wiki.py::TestMultiWiki::test_3_4_unregister_wiki PASSED [ 39%]
tests/scenarios/test_03_multi_wiki.py::TestMultiWiki::test_3_5_wiki_discovery PASSED [ 41%]
tests/scenarios/test_04_chat_react.py::TestChatReAct::test_4_1_health_check PASSED [ 43%]
tests/scenarios/test_04_chat_react.py::TestChatReAct::test_4_2_auth_optional PASSED [ 45%]
tests/scenarios/test_04_chat_react.py::TestChatReAct::test_4_3_chat_sse PASSED [ 47%]
tests/scenarios/test_04_chat_react.py::TestChatReAct::test_4_4_chat_with_wiki_tool PASSED [ 50%]
tests/scenarios/test_04_chat_react.py::TestChatReAct::test_4_5_chat_session_list PASSED [ 52%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_1_quant_init_via_cli PASSED [ 54%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_2_write_factor PASSED [ 56%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_3_list_factors PASSED [ 58%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_4_read_factor PASSED [ 60%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_5_duckdb_schema PASSED [ 63%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_6_paper_api PASSED [ 65%]
tests/scenarios/test_05_quant_pipeline.py::TestQuantPipeline::test_5_7_factor_library_list PASSED [ 67%]
tests/scenarios/test_06_lint_rules.py::TestLintRules::test_6_1_dated_claim PASSED [ 69%]
tests/scenarios/test_06_lint_rules.py::TestLintRules::test_6_2_potentially_outdated PASSED [ 71%]
tests/scenarios/test_06_lint_rules.py::TestLintRules::test_6_3_unsourced_claims PASSED [ 73%]
tests/scenarios/test_06_lint_rules.py::TestLintRules::test_6_4_orphan_page PASSED [ 76%]
tests/scenarios/test_06_lint_rules.py::TestLintRules::test_6_5_brief_mode PASSED [ 78%]
tests/scenarios/test_07_yaml_templates.py::TestYAMLTemplates::test_7_1_parse_personal_kb PASSED [ 80%]
tests/scenarios/test_07_yaml_templates.py::TestYAMLTemplates::test_7_2_parse_project_docs PASSED [ 82%]
tests/scenarios/test_07_yaml_templates.py::TestYAMLTemplates::test_7_3_parse_research_wiki PASSED [ 84%]
tests/scenarios/test_07_yaml_templates.py::TestYAMLTemplates::test_7_4_parse_mining_news PASSED [ 86%]
tests/scenarios/test_07_yaml_templates.py::TestYAMLTemplates::test_7_5_custom_config PASSED [ 89%]
tests/scenarios/test_08_section_anchors.py::TestSectionAnchors::test_8_1_write_target_page PASSED [ 91%]
tests/scenarios/test_08_section_anchors.py::TestSectionAnchors::test_8_2_write_source_page PASSED [ 93%]
tests/scenarios/test_08_section_anchors.py::TestSectionAnchors::test_8_3_inbound_links PASSED [ 95%]
tests/scenarios/test_08_section_anchors.py::TestSectionAnchors::test_8_4_outbound_links PASSED [ 97%]
tests/scenarios/test_08_section_anchors.py::TestSectionAnchors::test_8_5_include_context PASSED [100%]

======================== 45 passed, 1 skipped in 48.42s ========================
