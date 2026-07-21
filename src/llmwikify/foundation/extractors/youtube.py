"""YouTube video transcript extractor."""

import concurrent.futures
import logging

from .base import ExtractedContent

logger = logging.getLogger(__name__)

# youtube-transcript-api is blocking and has no timeout parameter
# (verified against 1.0.3). Wrap it in a ThreadPoolExecutor so a
# slow / unreachable YouTube API does not hang the caller. Mirrors
# the same pattern as web.py's _extract_url.
YOUTUBE_FETCH_TIMEOUT = 15  # seconds

# Module-level executor. youtube-transcript-api is blocking; without
# the timeout wrapper, a network failure or DNS timeout hangs the
# caller indefinitely (regression caught by
# tests/test_v020_markitdown_extractor.py::test_preserves_youtube_routing
# hanging for minutes).
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _extract_youtube_id(url: str) -> str | None:
    """Extract the video ID from various YouTube URL formats."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)

    # youtu.be/{id}
    if parsed.hostname == 'youtu.be':
        return parsed.path[1:]

    # youtube.com/watch?v={id}
    if parsed.hostname in ('youtube.com', 'www.youtube.com'):
        query = parse_qs(parsed.query)
        return query.get('v', [None])[0]

    # youtube.com/embed/{id}
    if '/embed/' in url:
        return url.split('/embed/')[-1].split('?')[0].split('/')[0]

    return None


def _extract_youtube(
    url: str,
    timeout: int = YOUTUBE_FETCH_TIMEOUT,
) -> ExtractedContent:
    """Extract transcript from a YouTube video.

    Args:
        url: YouTube video URL.
        timeout: Seconds to wait for the upstream API before giving up.
            youtube-transcript-api is a blocking library without a
            timeout parameter, so we run it in a thread and bound the
            wait time here. Default 15s.

    Returns:
        ExtractedContent with the transcript on success, or
        source_type="error" with metadata.error describing the failure
        (network timeout, missing package, invalid video id, etc).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": "youtube-transcript-api not installed. Install with: pip install youtube-transcript-api"}
        )

    video_id = _extract_youtube_id(url)
    if not video_id:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"Could not extract video ID from: {url}"}
        )

    # Run the blocking get_transcript in a thread so we can enforce
    # a timeout. If the network is unreachable or the API is slow,
    # future.result(timeout=...) raises TimeoutError instead of
    # hanging the caller.
    future = _executor.submit(YouTubeTranscriptApi.get_transcript, video_id)
    try:
        transcript = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        logger.warning(
            "YouTube transcript fetch timed out after %ds: %s", timeout, url,
        )
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"YouTube transcript fetch timed out after {timeout}s"},
        )
    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": str(e)},
        )

    text = "\n".join([entry['text'] for entry in transcript])
    return ExtractedContent(
        text=text,
        source_type="youtube",
        title=f"YouTube Video ({video_id})",
        metadata={
            "url": url,
            "video_id": video_id,
        },
    )


# Export with consistent name
extract_youtube = _extract_youtube
extract_youtube_id = _extract_youtube_id
