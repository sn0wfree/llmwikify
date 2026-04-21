"""E2E tests for SearchBar component."""

import pytest
from playwright.sync_api import expect


def test_searchbar_shows_dropdown_results(page, wiki_server):
    """Verify SearchBar shows dropdown results when searching."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Find search input (only one now)
    search_input = page.locator('input[placeholder="Search wiki..."]')
    expect(search_input).to_be_visible()

    # Type search query
    search_input.fill("Machine Learning")

    # Wait for debounce (300ms) + API call
    page.wait_for_timeout(800)

    # Verify dropdown appears with results
    dropdown = page.locator('.absolute.top-full')
    expect(dropdown).to_be_visible()

    # Verify results in dropdown
    results = dropdown.locator('div[class*="hover:bg-slate-700"]')
    result_count = results.count()

    if result_count > 0:
        first_result = results.first
        expect(first_result).to_be_visible()

        # Check for content snippet (should not be empty)
        snippet = first_result.locator('.line-clamp-2').count()
        if snippet > 0:
            snippet_text = first_result.locator('.line-clamp-2').text_content()
            assert len(snippet_text.strip()) > 0, "Search result snippet should not be empty"
    else:
        # Check for "No results found" in dropdown
        no_results = dropdown.locator('text=No results found').count()
        assert no_results > 0, "Should show results or 'No results found' message"

    assert len(errors) == 0, f"JavaScript errors found: {errors}"

    page.screenshot(path="tests/e2e/screenshots/search-results.png")


def test_searchbar_click_result_navigates(page, wiki_server):
    """Verify clicking search result navigates to editor."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    search_input = page.locator('input[placeholder="Search wiki..."]')
    search_input.fill("Machine")
    page.wait_for_timeout(800)

    # Click first result in dropdown
    dropdown = page.locator('.absolute.top-full')
    results = dropdown.locator('div[class*="hover:bg-slate-700"]')
    result_count = results.count()

    if result_count > 0:
        results.first.click()
        page.wait_for_timeout(500)

        # Should navigate to Editor view
        editor = page.locator('textarea')
        expect(editor).to_be_visible()

    assert len(errors) == 0, f"JavaScript errors found: {errors}"


def test_searchbar_empty_query(page, wiki_server):
    """Verify SearchBar handles empty query."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    search_input = page.locator('input[placeholder="Search wiki..."]')
    search_input.fill("")
    page.wait_for_timeout(500)

    # Dropdown should not appear for empty query
    dropdown = page.locator('.absolute.top-full')
    expect(dropdown).not_to_be_visible()

    assert len(errors) == 0, f"JavaScript errors found: {errors}"


def test_searchbar_no_search_nav_button(page, wiki_server):
    """Verify Search navigation button is removed from sidebar."""
    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Search nav button should not exist in sidebar
    # The sidebar nav buttons are inside <nav class="p-2 space-y-1">
    sidebar = page.locator('aside nav')
    search_nav_btn = sidebar.locator('button:has-text("Search")')
    expect(search_nav_btn).not_to_be_visible()
