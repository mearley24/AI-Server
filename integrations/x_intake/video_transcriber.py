"""Video Transcriber — downloads and transcribes videos from X/Twitter posts.

Pipeline:
1. Download video from X post using yt-dlp
2. Transcribe audio using OpenAI Whisper API
3. Analyze transcript with GPT-4o-mini for flags and summary
4. Save flagged transcript to /data/transcripts/
5. Return summary with flags for iMessage delivery

Flag system:
  🔨 — something we can build/implement
  💡 — trading edge or alpha insight
  📊 — specific number, threshold, or backtested result
  🔧 — tool, library, or resource
  ⚠️ — warning or pitfall
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TRANSCRIPT_DIR = Path(os.environ.get("TRANSCRIPT_DIR", "/data/transcripts"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def download_video(post_url: str, output_dir: str = None) -> Optional[str]:
    """Download video from an X/Twitter post using yt-dlp.
    
    Returns path to downloaded audio file, or None on failure.
    """
    if not output_dir:
        output_dir = tempfile.mkdtemp()

    output_path = os.path.join(output_dir, "audio.m4a")

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--extract-audio",
                "--audio-format", "m4a",
                "--audio-quality", "0",
                "-o", output_path,
                post_url,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info("video_downloaded", path=output_path, size=os.path.getsize(output_path))
            return output_path
        else:
            # Try downloading as video then extract audio
            video_path = os.path.join(output_dir, "video.mp4")
            result2 = subprocess.run(
                ["yt-dlp", "-o", video_path, post_url],
                capture_output=True, text=True, timeout=120,
            )
            if result2.returncode == 0 and os.path.exists(video_path):
                # Extract audio with ffmpeg
                subprocess.run(
                    ["ffmpeg", "-i", video_path, "-vn", "-acodec", "aac", output_path, "-y"],
                    capture_output=True, timeout=60,
                )
                if os.path.exists(output_path):
                    return output_path
            
            logger.error("video_download_failed", stderr=result.stderr[:200])
            return None
    except FileNotFoundError:
        logger.error("yt-dlp not installed")
        return None
    except subprocess.TimeoutExpired:
        logger.error("video_download_timeout")
        return None
    except Exception as e:
        logger.error("video_download_error", error=str(e)[:200])
        return None


def transcribe_audio(audio_path: str) -> Optional[str]:
    """Transcribe audio using OpenAI Whisper API.
    
    Cost: ~$0.006/minute. A 10-minute video costs ~$0.06.
    """
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set")
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
            )

        logger.info("transcription_complete", length=len(transcript))
        return transcript
    except Exception as e:
        logger.error("transcription_error", error=str(e)[:200])
        return None


def analyze_transcript(transcript: str, author: str = "", post_text: str = "") -> dict:
    """Analyze transcript with GPT-4o-mini for flags and summary.
    
    Returns dict with:
        - summary: brief overview
        - flags: list of {type, text} flagged items
        - strategies: extracted actionable strategies
        - full_flagged: complete transcript with inline flags
    """
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY not set"}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = f"""Analyze this video transcript from @{author} about trading/prediction markets.

Post text: {post_text[:500]}

Transcript:
{transcript[:15000]}

Respond in this exact JSON format:
{{
    "summary": "2-3 sentence overview of the key message",
    "flags": [
        {{"type": "🔨", "text": "specific actionable item"}},
        {{"type": "💡", "text": "trading edge or alpha insight"}},
        {{"type": "📊", "text": "specific number, threshold, or backtested result"}},
        {{"type": "🔧", "text": "tool, library, or resource mentioned"}},
        {{"type": "⚠️", "text": "warning or pitfall to avoid"}}
    ],
    "strategies": [
        {{
            "name": "strategy name",
            "description": "how it works",
            "parameters": "key thresholds or settings",
            "backtested_return": "if mentioned",
            "implementable": true/false,
            "priority": "high/medium/low"
        }}
    ],
    "key_quotes": ["most important direct quotes from the transcript"]
}}

Only include flags that are genuinely present in the transcript. Be specific — include actual numbers, thresholds, and parameters mentioned. Focus on what can be implemented in a Polymarket trading bot."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        analysis = json.loads(response.choices[0].message.content)
        logger.info("analysis_complete", flags=len(analysis.get("flags", [])),
                     strategies=len(analysis.get("strategies", [])))
        return analysis
    except Exception as e:
        logger.error("analysis_error", error=str(e)[:200])
        return {"error": str(e)}


def save_transcript(post_id: str, author: str, transcript: str, analysis: dict) -> str:
    """Save flagged transcript to /data/transcripts/."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clean filename: @author — topic — date.md
    import datetime
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    topic = analysis.get("summary", "")[:50].strip().rstrip(".")
    if not topic:
        topic = post_id
    safe_topic = "".join(c if c.isalnum() or c in " -" else "" for c in topic).strip()[:50]
    filename = f"@{author} \u2014 {safe_topic} \u2014 {date_str}.md"
    output_path = TRANSCRIPT_DIR / filename
    
    lines = [
        f"# Video Transcript: @{author}",
        f"Post ID: {post_id}",
        f"",
        f"## Summary",
        analysis.get("summary", "No summary available"),
        f"",
        f"## Flags",
    ]

    for flag in analysis.get("flags", []):
        lines.append(f"- {flag['type']} {flag['text']}")

    lines.append("")
    lines.append("## Strategies")
    for strat in analysis.get("strategies", []):
        lines.append(f"### {strat.get('name', 'Unnamed')}")
        lines.append(f"- **Description:** {strat.get('description', '')}")
        lines.append(f"- **Parameters:** {strat.get('parameters', '')}")
        lines.append(f"- **Backtested Return:** {strat.get('backtested_return', 'N/A')}")
        lines.append(f"- **Implementable:** {'Yes' if strat.get('implementable') else 'No'}")
        lines.append(f"- **Priority:** {strat.get('priority', 'N/A')}")
        lines.append("")

    if analysis.get("key_quotes"):
        lines.append("## Key Quotes")
        for quote in analysis["key_quotes"]:
            lines.append(f"> {quote}")
            lines.append("")

    lines.append("## Full Transcript")
    lines.append(transcript)

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    logger.info("transcript_saved", path=str(output_path))
    return str(output_path)


def format_imessage_summary(author: str, analysis: dict) -> str:
    """Format the analysis into a clean iMessage summary."""
    lines = [f"[VIDEO SUMMARY] @{author}", ""]

    if analysis.get("summary"):
        lines.append(analysis["summary"])
        lines.append("")

    for flag in analysis.get("flags", []):
        lines.append(f"{flag['type']} {flag['text']}")

    if analysis.get("strategies"):
        lines.append("")
        for strat in analysis["strategies"]:
            if strat.get("implementable") and strat.get("priority") in ("high", "medium"):
                lines.append(f"Strategy: {strat.get('name', '')} — {strat.get('description', '')[:80]}")

    return "\n".join(lines)


def process_x_video(post_url: str, post_id: str = "", author: str = "", post_text: str = "") -> dict:
    """Full pipeline: download → transcribe → analyze → save → format.
    
    Returns dict with summary, flags, and transcript path.
    """
    # Extract post_id from URL if not provided
    if not post_id:
        import re
        match = re.search(r'/status/(\d+)', post_url)
        post_id = match.group(1) if match else "unknown"

    logger.info("processing_video", post_id=post_id, author=author)

    # 1. Download
    audio_path = download_video(post_url)
    if not audio_path:
        return {"error": "Failed to download video", "post_id": post_id}

    # 2. Transcribe
    transcript = transcribe_audio(audio_path)
    if not transcript:
        return {"error": "Failed to transcribe audio", "post_id": post_id}

    # 3. Analyze
    analysis = analyze_transcript(transcript, author, post_text)

    # 4. Save
    transcript_path = save_transcript(post_id, author, transcript, analysis)

    # 5. Format for iMessage
    imessage_summary = format_imessage_summary(author, analysis)

    # Cleanup temp audio
    try:
        os.remove(audio_path)
        os.rmdir(os.path.dirname(audio_path))
    except Exception:
        pass

    return {
        "post_id": post_id,
        "author": author,
        "summary": imessage_summary,
        "analysis": analysis,
        "transcript_path": transcript_path,
        "transcript_length": len(transcript),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python video_transcriber.py <x_post_url>")
        sys.exit(1)

    url = sys.argv[1]
    result = process_x_video(url)
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(result["summary"])
        print(f"\nFull transcript: {result['transcript_path']}")
