"""E2E tests for Insights page."""

import pytest
from playwright.sync_api import expect


def test_insights_page_loads(page, wiki_server):
    """Verify Insights page loads with all three sections visible."""
    console_messages = []
    errors = []

    page.on("console", lambda msg: console_messages.append(msg.text))
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")

    # Click Insights navigation button
    page.click('button:has-text("Insights")')
    page.wait_for_timeout(1000)

    # Verify all three section headings are visible
    expect(page.locator('h2:has-text("Insights")')).to_be_visible()
    expect(page.locator('h3:has-text("Recommendations")')).to_be_visible()
    expect(page.locator('h3:has-text("Synthesis")')).to_be_visible()
    expect(page.locator('h3:has-text("Graph Analysis")')).to_be_visible()

    # Verify Recommendations section shows content (even if empty)
    rec_section = page.locator('section:has-text("Recommendations")')
    expect(rec_section).to_be_visible()

    # Should show either recommendations or "No recommendations" message
    has_items = page.locator('section:has-text("Recommendations") .space-y-2 > div').count()
    has_empty = page.locator('text=No recommendations').count()
    assert has_items > 0 or has_empty > 0, "Recommendations section should show content or empty message"

    # Check for JS errors
    assert len(errors) == 0, f"JavaScript errors found: {errors}"

    page.screenshot(path="tests/e2e/screenshots/insights-loaded.png")


def test_synthesis_analyze_button(page, wiki_server):
    """Verify Synthesis Analyze button works."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.click('button:has-text("Insights")')
    page.wait_for_timeout(500)

    # Find and click Synthesis Analyze button
    graph_section = page.locator('section:has-text("Synthesis")')
    analyze_btn = graph_section.locator('button:has-text("Analyze")')
    expect(analyze_btn).to_be_visible()
    analyze_btn.click()

    # Wait for analysis to complete
    page.wait_for_timeout(2000)

    # Verify section is still visible
    expect(graph_section).to_be_visible()

    # Check for JS errors
    assert len(errors) == 0, f"JavaScript errors found: {errors}"

    page.screenshot(path="tests/e2e/screenshots/synthesis-analyze.png")


def test_graph_analysis_button(page, wiki_server):
    """Verify Graph Analysis button works and shows stats."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.click('button:has-text("Insights")')
    page.wait_for_timeout(500)

    # Find and click Graph Analysis Analyze button
    graph_section = page.locator('section:has-text("Graph Analysis")')
    analyze_btn = graph_section.locator('button:has-text("Analyze")')
    expect(analyze_btn).to_be_visible()
    analyze_btn.click()

    # Wait for analysis to complete
    page.wait_for_timeout(2000)

    # Verify section is still visible
    expect(graph_section).to_be_visible()

    # Check for JS errors
    assert len(errors) == 0, f"JavaScript errors found: {errors}"

    page.screenshot(path="tests/e2e/screenshots/graph-analysis.png")


def test_insights_no_js_errors(page, wiki_server):
    """Verify no JavaScript errors on Insights page."""
    console_messages = []
    errors = []

    page.on("console", lambda msg: console_messages.append(msg.text))
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.click('button:has-text("Insights")')
    page.wait_for_timeout(2000)

    # Check for any JavaScript errors
    if errors:
        pytest.fail(f"JavaScript errors detected: {errors}")

    # Log any warnings for debugging
    for msg in console_messages:
        if "error" in msg.lower():
            print(f"Console error: {msg}")
