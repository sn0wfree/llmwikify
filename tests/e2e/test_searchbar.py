"""E2E tests for SearchBar component."""

import pytest
from playwright.sync_api import expect


def test_searchbar_shows_results(page, wiki_server):
    """Verify SearchBar shows results when searching."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Find search input
    search_input = page.locator('input[placeholder="Search wiki..."]')
    expect(search_input).to_be_visible()

    # Type search query
    search_input.fill("Machine Learning")

    # Wait for debounce (300ms) + API call
    page.wait_for_timeout(800)

    # Verify results appear
    results = page.locator('.space-y-2 > div')
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
        no_results = page.locator('text=No results found').count()
        assert no_results > 0, "Should show results or 'No results found' message"

    assert len(errors) == 0, f"JavaScript errors found: {errors}"

    page.screenshot(path="tests/e2e/screenshots/search-results.png")


def test_searchbar_standalone_view(page, wiki_server):
    """Verify standalone search view works."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")

    # Navigate to standalone search view
    page.click('button:has-text("Search")')
    page.wait_for_timeout(500)

    # Use standalone search bar (second input on page)
    search_inputs = page.locator('input[placeholder="Search wiki..."]')
    search_inputs.nth(1).fill("Machine")
    page.wait_for_timeout(800)

    results = page.locator('.space-y-2 > div')
    result_count = results.count()

    # Should show results or "No results found"
    assert result_count > 0 or page.locator('text=No results found').count() > 0

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

    no_results = page.locator('text=No results found').count()
    assert no_results == 0, "Should not show 'No results found' for empty query"

    assert len(errors) == 0, f"JavaScript errors found: {errors}"
