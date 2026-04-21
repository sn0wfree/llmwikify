"""Debug tests to diagnose blank Insights page issue."""

import pytest
import urllib.request
import json


def test_debug_insights_dom(page, wiki_server):
    """Debug: Inspect DOM structure of Insights page."""
    console_messages = []
    errors = []

    page.on("console", lambda msg: console_messages.append(msg.text))
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")

    # Log all console messages
    print("\n=== Console Messages ===")
    for msg in console_messages:
        print(f"  {msg}")

    # Log all page errors
    print("\n=== Page Errors ===")
    for err in errors:
        print(f"  {err}")

    # Click Insights
    page.click('button:has-text("Insights")')
    page.wait_for_timeout(2000)

    # Check DOM structure
    print("\n=== DOM Structure ===")

    main_div = page.locator('.max-w-6xl').count()
    print(f"  .max-w-6xl containers: {main_div}")

    h2_count = page.locator('h2:has-text("Insights")').count()
    print(f"  h2 'Insights': {h2_count}")

    for section in ["Recommendations", "Synthesis", "Graph Analysis"]:
        h3_count = page.locator(f'h3:has-text("{section}")').count()
        print(f"  h3 '{section}': {h3_count}")

    loading = page.locator('text=Loading insights').count()
    print(f"  Loading state: {loading}")

    # Get full HTML for debugging
    html = page.content()
    with open("tests/e2e/screenshots/insights-debug.html", "w") as f:
        f.write(html)
    print(f"\n  Full HTML saved to tests/e2e/screenshots/insights-debug.html")

    page.screenshot(path="tests/e2e/screenshots/insights-debug.png", full_page=True)
    print(f"  Screenshot saved to tests/e2e/screenshots/insights-debug.png")

    assert h2_count > 0, "Insights heading not found"
    assert loading == 0, "Still in loading state after 2s"


def test_debug_api_responses(wiki_server):
    """Debug: Check API responses directly."""
    endpoints = [
        "/api/wiki/status",
        "/api/wiki/recommend",
        "/api/wiki/suggest_synthesis",
        "/api/wiki/graph_analyze",
    ]

    print("\n=== API Responses ===")
    for ep in endpoints:
        try:
            url = f"{wiki_server}{ep}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                print(f"\n{ep}:")
                print(f"  Status: {resp.status}")
                print(f"  Type: {type(data).__name__}")
                if isinstance(data, dict):
                    print(f"  Keys: {list(data.keys())}")
                elif isinstance(data, list):
                    print(f"  Length: {len(data)}")
        except Exception as e:
            print(f"\n{ep}: ERROR - {e}")


def test_debug_network_requests(page, wiki_server):
    """Debug: Monitor network requests."""
    network_requests = []
    network_responses = []

    page.on("request", lambda req: network_requests.append(req.url))
    page.on("response", lambda resp: network_responses.append({
        "url": resp.url,
        "status": resp.status,
    }))

    page.goto(wiki_server)
    page.wait_for_load_state("networkidle")
    page.click('button:has-text("Insights")')
    page.wait_for_timeout(2000)

    print("\n=== Network Requests ===")
    for url in network_requests:
        if "/api/" in url:
            print(f"  {url}")

    print("\n=== Network Responses ===")
    for resp in network_responses:
        if "/api/" in resp["url"]:
            print(f"  {resp['url']} -> {resp['status']}")
