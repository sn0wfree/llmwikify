# Wikilink & Image Regression Test

This page is a permanent manual regression-test fixture for the WikiMarkdown renderer.
Visit `/edit?page=WIKILINK_TEST` to verify the following still work after any
renderer change.

## Wikilinks (4 cases)

- See [[overview]] for an overview.
- See [[TestCurl]] for the TestCurl page.
- See [[中文页面]] for the CJK page.
- See [[concepts/Alpha|Alpha Decay]] for a labeled wikilink.
- Inline code `[[ignored]]` should NOT be a link.

## Images (4 cases — H2/H3 fix verification)

- Relative path: ![local](raw/test-pixel.png)
- External HTTPS: ![external](https://placehold.co/50)
- Data URL (XSS blocked): ![xss](data:image/svg+xml,<svg/onload=alert(1)>)
- Wiki-page scheme on img (should route via fileUrl, not wikilink):
  ![fake](wiki-page://TestCurl)

## Raw file links (CJK double-encoding fix)

- ASCII path: [open report](raw/test-pixel.png)
- CJK path: [中文路径](raw/中文文件.png)

## What to check manually

1. **Wikilinks** (4): each `<a data-wikilink="...">` should be clickable,
   URL becomes `?page=<encoded>`, content switches.
2. **Local image**: `<img src="/api/wiki/file/raw/test-pixel.png">`
   served 200 by `/api/wiki/file/raw/test-pixel.png`.
3. **External image**: src preserved as `https://placehold.co/50`.
4. **Data URL image**: NO `<img>` with `data:...` src (urlTransform blocks).
5. **CJK raw link**: href is single-encoded (`%E4%B8%AD` not `%25E4%25B8`).
6. **Click wikilink → confirm dialog if content dirty, then URL changes**.
