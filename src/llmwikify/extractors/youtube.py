"""YouTube video transcript extractor."""

from typing import Optional
from .base import ExtractedContent


def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract the video ID from various YouTube URL formats."""
    from urllib.parse import urlparse, parse_qs
    
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


def _extract_youtube(url: str) -> ExtractedContent:
    """Extract transcript from a YouTube video."""
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
    
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
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
        
    except Exception as e:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": str(e)},
        )


# Export with consistent name
extract_youtube = _extract_youtube
extract_youtube_id = _extract_youtube_id
