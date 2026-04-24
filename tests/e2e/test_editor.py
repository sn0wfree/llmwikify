"""E2E tests for Editor component."""

import pytest
from playwright.sync_api import expect


def test_editor_loads_page_content(page, wiki_server):
    """Verify Editor shows page content as text, not [object Object]."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Click first file in the Editor's file tree (inside main content, not sidebar)
    file_tree = page.locator('main .w-40 button').first
    expect(file_tree).to_be_visible()
    file_tree.click()
    page.wait_for_timeout(1000)

    # Default mode is Graph, switch to Edit
    edit_btn = page.locator('button:text-is("Edit")')
    expect(edit_btn).to_be_visible()
    edit_btn.click()
    page.wait_for_timeout(1000)

    # Verify content is loaded and visible (not [object Object])
    textarea = page.locator('textarea').first
    expect(textarea).to_be_visible()

    # Get the content value
    content_value = textarea.input_value()
    assert len(content_value) > 0, "Editor content should not be empty"
    assert '[object Object]' not in content_value, "Editor should not show [object Object]"
    assert content_value.startswith('#'), "Content should start with markdown heading"

    assert len(errors) == 0, f"JavaScript errors found: {errors}"

    page.screenshot(path="tests/e2e/screenshots/editor-content.png")


def test_editor_file_tree_shows_pages(page, wiki_server):
    """Verify Editor file tree shows page names."""
    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # File tree should have multiple buttons (inside main content)
    file_buttons = page.locator('main .w-40 button')
    expect(file_buttons.first).to_be_visible()

    count = file_buttons.count()
    assert count > 0, "File tree should show at least one page"


def test_editor_save_button_visible(page, wiki_server):
    """Verify Save button is visible in Editor."""
    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Click first file
    file_tree = page.locator('main .w-40 button').first
    file_tree.click()
    page.wait_for_timeout(500)

    # Save button should be visible
    save_btn = page.locator('button:has-text("Save")')
    expect(save_btn).to_be_visible()
