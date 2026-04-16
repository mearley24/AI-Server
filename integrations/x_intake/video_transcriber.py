"""Video Transcriber — downloads and transcribes videos from X/Twitter posts.

Pipeline:
1. Download video from X post using yt-dlp
2. Transcribe audio (local Whisper first; OpenAI API last resort)
3. Analyze transcript with Ollama first, then GPT-4o-mini for flags and summary
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
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Use standard logging instead of structlog to avoid conflicts with imessage-server

TRANSCRIPT_DIR = Path(os.environ.get("TRANSCRIPT_DIR", os.path.expanduser("~/AI-Server/data/transcripts")))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DOWNLOAD_TIMEOUT_SECONDS = 600
MIN_VALID_AUDIO_BYTES = 10 * 1024


WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434")
OLLAMA_ANALYSIS_MODEL = os.environ.get("OLLAMA_ANALYSIS_MODEL", "qwen3:8b")


def _parse_json_maybe(raw: str) -> Optional[dict]:
    """Parse Ollama/OpenAI JSON; tolerate markdown fences."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    return None


def _transcribe_whisper_cli(audio_path: str) -> Optional[str]:
    """Use whisper.cpp CLI if available (Metal on Apple Silicon)."""
    import shutil

    whisper_bin = shutil.which("whisper-cpp") or shutil.which("whisper")
    if not whisper_bin:
        hp = os.path.expanduser("~/whisper.cpp/main")
        if os.path.isfile(hp) and os.access(hp, os.X_OK):
            whisper_bin = hp
    if not whisper_bin:
        logger.info("whisper_cli_not_found — skipping")
        return None

    model_path = (os.environ.get("WHISPER_CPP_MODEL") or "").strip()
    if not model_path:
        for base in (
            os.path.expanduser("~/whisper.cpp/models"),
            "/opt/homebrew/share/whisper.cpp",
            "/usr/local/share/whisper.cpp",
        ):
            cand = os.path.join(base, f"ggml-{WHISPER_MODEL}.bin")
            if os.path.isfile(cand):
                model_path = cand
                break
    if not model_path:
        logger.info("whisper_cpp_model_not_found — skipping")
        return None

    work_audio = audio_path
    tmp_wav = None
    if not audio_path.lower().endswith((".wav",)):
        try:
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            rc, _ = _run_command_with_progress(
                ["ffmpeg", "-y", "-i", audio_path, "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", tmp_wav],
                timeout=120,
                stage="whisper_prep_wav",
            )
            if rc == 0 and os.path.getsize(tmp_wav) > 0:
                work_audio = tmp_wav
        except Exception as e:
            logger.info("whisper_cli_wav_convert_failed: %s", str(e)[:80])

    try:
        out_base = audio_path + ".whisper"
        cmd = [whisper_bin, "-m", model_path, "-f", work_audio, "-otxt", "-of", out_base]
        rc, _ = _run_command_with_progress(cmd, timeout=300, stage="whisper_cli")
        candidates = [out_base + ".txt", work_audio + ".txt", os.path.splitext(work_audio)[0] + ".txt"]
        for p in candidates:
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    transcript = f.read().strip()
                if transcript:
                    logger.info("whisper_cli_success: %d chars", len(transcript))
                    return transcript
    except Exception as e:
        logger.info("whisper_cli_error: %s", str(e)[:100])
    finally:
        if tmp_wav and os.path.exists(tmp_wav):
            try:
                os.remove(tmp_wav)
            except OSError:
                pass
    return None


def _transcribe_mlx_whisper(audio_path: str) -> Optional[str]:
    """Use mlx-whisper (Apple Silicon) if available."""
    try:
        import mlx_whisper
        repo = f"mlx-community/whisper-{WHISPER_MODEL}-mlx"
        result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=repo)
        transcript = (result.get("text") or "").strip()
        if transcript:
            logger.info("mlx_whisper_success: %d chars", len(transcript))
            return transcript
    except ImportError:
        logger.info("mlx_whisper_not_installed — skipping")
    except Exception as e:
        logger.info("mlx_whisper_error: %s", str(e)[:100])
    return None


def _transcribe_local_whisper(audio_path: str) -> Optional[str]:
    """Use the Python openai-whisper package (local model, no API)."""
    try:
        import whisper as openai_whisper_pkg
        model = openai_whisper_pkg.load_model(WHISPER_MODEL)
        result = model.transcribe(audio_path)
        transcript = (result.get("text") or "").strip()
        if transcript:
            logger.info("local_whisper_success: %d chars", len(transcript))
            return transcript
    except ImportError:
        logger.info("openai_whisper_not_installed — skipping")
    except Exception as e:
        logger.info("local_whisper_error: %s", str(e)[:100])
    return None


def _transcribe_openai_api(audio_path: str, openai_api_key: str = "") -> Optional[str]:
    """Last resort: OpenAI Whisper API."""
    api_key = openai_api_key or OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.error("no_transcription_available — no local whisper and no OPENAI_API_KEY")
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        logger.warning("using_openai_whisper_api — install local whisper to avoid cloud costs")
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, response_format="text",
            )
        logger.info("openai_whisper_success: %d chars", len(transcript))
        return transcript
    except Exception as e:
        logger.error("openai_whisper_error: %s", str(e)[:200])
        return None


def _ollama_chat(prompt: str, model=None) -> Optional[str]:
    """Call Ollama /api/chat. Returns assistant text or None."""
    m = model or OLLAMA_ANALYSIS_MODEL
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = json.dumps({
            "model": m,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.3},
        }).encode()
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        content = data.get("message", {}).get("content", "")
        if content:
            logger.info("ollama_chat_success: model=%s chars=%d", m, len(content))
        return content or None
    except Exception as e:
        logger.info("ollama_chat_failed: %s", str(e)[:100])
        return None


def _build_analysis_prompt(transcript: str, author: str, post_text: str) -> str:
    """Shared analysis prompt for Ollama and OpenAI."""
    return f"""Analyze this video transcript from @{author} about trading/prediction markets.

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
            "implementable": true,
            "priority": "high"
        }}
    ],
    "key_quotes": ["most important direct quotes from the transcript"]
}}

Only include flags genuinely present in the transcript. Include actual numbers and parameters. Focus on what can be implemented in a Polymarket trading bot."""



def _extract_x_status_id(post_url: str) -> str:
    match = re.search(r"/status/(\d+)", post_url)
    return match.group(1) if match else ""


def _extract_x_author(post_url: str) -> str:
    match = re.search(r"(?:twitter\.com|x\.com)/([^/]+)/status/", post_url)
    return match.group(1) if match else ""


def _run_command_with_progress(cmd: list[str], timeout: int, stage: str) -> tuple[int, str]:
    """Run a command and stream periodic progress logs from stdout/stderr."""
    logger.info("%s_started: %s", stage, " ".join(cmd[:4]))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    output_lines: list[str] = []
    last_pct_logged = -1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            output_lines.append(line)
            pct_match = re.search(r"(\d{1,3}(?:\.\d+)?)%", line)
            if pct_match:
                pct = int(float(pct_match.group(1)))
                if pct >= last_pct_logged + 10:
                    last_pct_logged = pct
                    logger.info("%s_progress: %s%%", stage, pct)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.error("%s_timeout_after_%ss", stage, timeout)
        return 124, "".join(output_lines)
    except Exception as exc:
        proc.kill()
        logger.error("%s_error: %s", stage, str(exc)[:200])
        return 1, "".join(output_lines)
    return proc.returncode, "".join(output_lines)


def _ffprobe_duration_seconds(media_path: str) -> float:
    """Return media duration in seconds (0 when not readable)."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                media_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return 0.0
        return float((result.stdout or "0").strip() or "0")
    except Exception:
        return 0.0


def _is_valid_audio_file(audio_path: str) -> bool:
    if not os.path.exists(audio_path):
        return False
    size_bytes = os.path.getsize(audio_path)
    duration = _ffprobe_duration_seconds(audio_path)
    logger.info("audio_validation: size=%d duration=%.2fs", size_bytes, duration)
    return size_bytes >= MIN_VALID_AUDIO_BYTES and duration > 0


def _video_has_audio_stream(video_path: str) -> bool:
    """Return True if the video file has at least one audio stream."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_streams", "-select_streams", "a", video_path],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _extract_audio_from_video(video_path: str, audio_path: str) -> bool:
    """Extract audio from a video file, with multiple ffmpeg fallbacks.

    Strategy:
    1. -vn -acodec aac  (standard audio strip)
    2. -map 0:a:0 -c:a aac  (explicit stream mapping for oddly-muxed files)
    3. If neither works, probe for audio streams; if none, log and return False.
    """
    # Attempt 1: standard approach
    rc, output = _run_command_with_progress(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "aac", audio_path],
        timeout=180,
        stage="ffmpeg_audio_extract",
    )
    if rc == 0 and _is_valid_audio_file(audio_path):
        return True

    logger.warning("ffmpeg_audio_extract_attempt1_failed — trying explicit stream mapping: %s", output[-200:])

    # Attempt 2: explicit audio stream mapping
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass
    rc2, output2 = _run_command_with_progress(
        ["ffmpeg", "-y", "-i", video_path, "-map", "0:a:0", "-c:a", "aac", audio_path],
        timeout=180,
        stage="ffmpeg_audio_extract_map",
    )
    if rc2 == 0 and _is_valid_audio_file(audio_path):
        return True

    logger.warning("ffmpeg_audio_extract_attempt2_failed: %s", output2[-200:])

    # Attempt 3: check if the file has any audio at all
    if not _video_has_audio_stream(video_path):
        logger.info("video_has_no_audio_stream — skipping transcription")
    else:
        logger.error("ffmpeg_audio_extract_all_attempts_failed")
    return False


def _collect_media_urls(node: object, urls: list[str]) -> None:
    """Recursively collect image/video URLs from arbitrary API JSON."""
    if isinstance(node, dict):
        for value in node.values():
            _collect_media_urls(value, urls)
    elif isinstance(node, list):
        for item in node:
            _collect_media_urls(item, urls)
    elif isinstance(node, str):
        lower = node.lower()
        if any(ext in lower for ext in (".mp4", ".m3u8", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp")):
            if node.startswith("http"):
                urls.append(node)


def _fetch_x_media_urls(post_url: str) -> tuple[list[str], list[str]]:
    """Fetch media URLs from vxtwitter/fxtwitter APIs (videos, images)."""
    post_id = _extract_x_status_id(post_url)
    author = _extract_x_author(post_url)
    if not post_id or not author:
        return [], []

    candidate_apis = [
        f"https://api.vxtwitter.com/{author}/status/{post_id}",
        f"https://api.fxtwitter.com/{author}/status/{post_id}",
    ]
    urls: list[str] = []
    for api_url in candidate_apis:
        try:
            req = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read())
            _collect_media_urls(payload, urls)
            if urls:
                logger.info("x_media_api_success: %s urls=%d", api_url, len(urls))
                break
        except Exception as exc:
            logger.info("x_media_api_failed: %s err=%s", api_url, str(exc)[:120])

    deduped = []
    seen = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    videos = [u for u in deduped if any(ext in u.lower() for ext in (".mp4", ".m3u8", ".mov", ".webm"))]
    images = [u for u in deduped if any(ext in u.lower() for ext in (".jpg", ".jpeg", ".png", ".webp"))]
    return videos, images


def _download_with_gallery_dl(post_url: str, output_dir: str) -> Optional[str]:
    """Fallback downloader using gallery-dl, returns downloaded video path if found."""
    rc, output = _run_command_with_progress(
        ["gallery-dl", "-d", output_dir, post_url],
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        stage="gallery_dl_download",
    )
    if rc != 0:
        logger.error("gallery_dl_failed: %s", output[-300:])
        return None

    candidates = []
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
                path = os.path.join(root, name)
                candidates.append((os.path.getsize(path), path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _download_direct_media(video_url: str, output_video_path: str) -> bool:
    """Download direct media URL to MP4 file with yt-dlp then ffmpeg fallback."""
    rc, output = _run_command_with_progress(
        ["yt-dlp", "--newline", "-o", output_video_path, video_url],
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        stage="direct_media_download",
    )
    if rc == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > MIN_VALID_AUDIO_BYTES:
        return True

    rc_ffmpeg, ffmpeg_out = _run_command_with_progress(
        ["ffmpeg", "-y", "-i", video_url, "-c", "copy", output_video_path],
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        stage="direct_media_ffmpeg_download",
    )
    if rc_ffmpeg != 0:
        logger.error("direct_media_download_failed: %s | %s", output[-180:], ffmpeg_out[-180:])
        return False
    return os.path.exists(output_video_path) and os.path.getsize(output_video_path) > MIN_VALID_AUDIO_BYTES


def download_video(post_url: str, output_dir: str = None) -> Optional[str]:
    """Download video from an X/Twitter post using yt-dlp.
    
    Returns path to downloaded audio file, or None on failure.
    """
    if not output_dir:
        output_dir = tempfile.mkdtemp()

    output_path = os.path.join(output_dir, "audio.m4a")
    video_path = os.path.join(output_dir, "video.mp4")

    try:
        logger.info("download_started: %s", post_url)

        # Primary path: yt-dlp audio extraction.
        rc, output = _run_command_with_progress(
            [
                "yt-dlp",
                "--newline",
                "--extract-audio",
                "--audio-format",
                "m4a",
                "--audio-quality",
                "0",
                "-o",
                output_path,
                post_url,
            ],
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            stage="yt_dlp_audio_download",
        )
        if rc == 0 and _is_valid_audio_file(output_path):
            logger.info("video_downloaded: %s (%d bytes)", output_path, os.path.getsize(output_path))
            return output_path

        logger.warning("yt_dlp_audio_failed_or_invalid: %s", output[-300:])

        # Secondary: download video via yt-dlp and extract audio with ffmpeg.
        rc_video, output_video = _run_command_with_progress(
            ["yt-dlp", "--newline", "-o", video_path, post_url],
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            stage="yt_dlp_video_download",
        )
        if rc_video == 0 and os.path.exists(video_path):
            if _extract_audio_from_video(video_path, output_path):
                return output_path
            logger.warning("video_downloaded_but_audio_invalid")
        else:
            logger.warning("yt_dlp_video_failed: %s", output_video[-300:])

        # Tertiary fallback: gallery-dl.
        fallback_video = _download_with_gallery_dl(post_url, output_dir)
        if fallback_video:
            logger.info("gallery_dl_video_found: %s", fallback_video)
            if _extract_audio_from_video(fallback_video, output_path):
                return output_path

        # Final fallback: vxtwitter/fxtwitter media URL extraction.
        media_videos, _ = _fetch_x_media_urls(post_url)
        for media_url in media_videos:
            logger.info("trying_direct_media_url: %s", media_url[:120])
            if _download_direct_media(media_url, video_path) and _extract_audio_from_video(video_path, output_path):
                return output_path

        logger.error("video_download_failed_all_fallbacks")
        return None
    except FileNotFoundError:
        logger.error("downloader_not_installed (yt-dlp/gallery-dl/ffmpeg missing)")
        return None
    except subprocess.TimeoutExpired:
        logger.error("video_download_timeout")
        return None
    except Exception as e:
        logger.error("video_download_error: %s", str(e)[:200])
        return None


def _chunk_and_transcribe_openai(audio_path: str, openai_api_key: str, chunk_seconds: int = 300) -> Optional[str]:
    """Split audio into chunks and transcribe each via OpenAI Whisper API.

    Used for videos longer than chunk_seconds to prevent a single blocking upload.
    """
    duration = _ffprobe_duration_seconds(audio_path)
    if duration <= chunk_seconds:
        return _transcribe_openai_api(audio_path, openai_api_key)

    logger.info("chunked_transcription_start: duration=%.1fs chunks=%d", duration, int(duration / chunk_seconds) + 1)
    tmp_dir = tempfile.mkdtemp(prefix="whisper_chunks_")
    chunk_pattern = os.path.join(tmp_dir, "chunk_%03d.m4a")
    try:
        rc, output = _run_command_with_progress(
            [
                "ffmpeg", "-y", "-i", audio_path,
                "-f", "segment", "-segment_time", str(chunk_seconds),
                "-c", "copy", chunk_pattern,
            ],
            timeout=300,
            stage="ffmpeg_chunk_split",
        )
        if rc != 0:
            logger.warning("chunk_split_failed — falling back to single upload: %s", output[-200:])
            return _transcribe_openai_api(audio_path, openai_api_key)

        chunk_files = sorted(
            p for p in (os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir))
            if os.path.isfile(p)
        )
        if not chunk_files:
            logger.warning("no_chunks_produced — falling back to single upload")
            return _transcribe_openai_api(audio_path, openai_api_key)

        parts: list[str] = []
        for i, chunk in enumerate(chunk_files):
            logger.info("transcribing_chunk: %d/%d %s", i + 1, len(chunk_files), chunk)
            text = _transcribe_openai_api(chunk, openai_api_key)
            if text:
                parts.append(text)
        return " ".join(parts) if parts else None
    finally:
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def transcribe_audio(audio_path: str, openai_api_key: str = "") -> Optional[str]:
    """Transcribe audio locally first; OpenAI Whisper API only as last resort.

    For audio longer than 300s (5 min), the OpenAI API path uses chunked upload
    so the event loop is not blocked by a single long API call.
    """
    logger.info("transcription_started: %s", audio_path)

    transcript = _transcribe_whisper_cli(audio_path)
    if transcript:
        return transcript

    transcript = _transcribe_mlx_whisper(audio_path)
    if transcript:
        return transcript

    transcript = _transcribe_local_whisper(audio_path)
    if transcript:
        return transcript

    logger.warning("all_local_whisper_failed — falling back to OpenAI API")
    duration = _ffprobe_duration_seconds(audio_path)
    if duration > 300:
        logger.info("long_audio_detected: %.1fs — using chunked transcription", duration)
        return _chunk_and_transcribe_openai(audio_path, openai_api_key)
    return _transcribe_openai_api(audio_path, openai_api_key)


def analyze_transcript(transcript: str, author: str = "", post_text: str = "", openai_api_key: str = "") -> dict:
    """Analyze transcript with local Ollama first; GPT-4o-mini fallback."""
    logger.info("analysis_started: transcript_chars=%d", len(transcript))
    prompt = _build_analysis_prompt(transcript, author, post_text)

    response = _ollama_chat(prompt)
    if response:
        parsed = _parse_json_maybe(response)
        if parsed:
            logger.info(
                "analysis_complete: %d flags, %d strategies",
                len(parsed.get("flags", [])),
                len(parsed.get("strategies", [])),
            )
            return parsed
        logger.warning("ollama_json_parse_failed — trying cloud fallback")

    api_key = openai_api_key or OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"error": "Analysis unavailable — Ollama down and no OPENAI_API_KEY"}

    logger.warning("using_openai_for_analysis — Ollama was unavailable or returned invalid JSON")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error("analysis_error: %s", str(e)[:200])
        return {"error": str(e)}


def analyze_images(image_urls: list[str], author: str = "", post_text: str = "", openai_api_key: str = "") -> dict:
    """Analyze image-only posts with GPT-4o vision."""
    api_key = openai_api_key or OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}
    if not image_urls:
        return {"error": "No images to analyze"}

    try:
        from openai import OpenAI

        logger.warning("using_openai_vision — no local alternative available for image analysis")
        client = OpenAI(api_key=api_key)
        logger.info("analysis_started: image_count=%d", len(image_urls))

        prompt = (
            f"Analyze these images from @{author}'s X post for actionable insights. "
            f"Post text context: {post_text[:500]}\n\n"
            "Return strict JSON with keys: summary, flags, strategies, key_quotes.\n"
            "flags should be [{type, text}] using: 🔨 💡 📊 🔧 ⚠️."
        )

        content = [{"type": "text", "text": prompt}]
        for image_url in image_urls[:8]:
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        analysis = json.loads(response.choices[0].message.content)
        logger.info(
            "image_analysis_complete: %d flags, %d strategies",
            len(analysis.get("flags", [])),
            len(analysis.get("strategies", [])),
        )
        return analysis
    except Exception as exc:
        logger.error("image_analysis_error: %s", str(exc)[:200])
        return {"error": str(exc)}


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

    logger.info("transcript_saved: %s", output_path)
    return str(output_path)


def format_imessage_summary(author: str, analysis: dict) -> str:
    """Format the analysis into a clean iMessage summary."""
    lines = [f"[VIDEO SUMMARY] @{author}", ""]

    if analysis.get("summary"):
        lines.append(str(analysis["summary"]))
        lines.append("")

    for flag in analysis.get("flags", []):
        # Guard: API sometimes returns strings instead of {"type", "text"} dicts
        if isinstance(flag, dict):
            lines.append(f"{flag.get('type', '')} {flag.get('text', '')}")
        elif isinstance(flag, str):
            lines.append(flag)

    if analysis.get("strategies"):
        lines.append("")
        for strat in analysis["strategies"]:
            # Guard: API sometimes returns strings instead of strategy dicts
            if isinstance(strat, dict):
                if strat.get("implementable") and strat.get("priority") in ("high", "medium"):
                    lines.append(f"Strategy: {strat.get('name', '')} — {strat.get('description', '')[:80]}")
            elif isinstance(strat, str):
                lines.append(f"Strategy: {strat[:80]}")

    return "\n".join(lines)


def process_x_video(
    post_url: str,
    post_id: str = "",
    author: str = "",
    post_text: str = "",
    openai_api_key: str = "",
) -> dict:
    """Full pipeline: download → transcribe → analyze → save → format.
    
    Returns dict with summary, flags, and transcript path.
    """
    # Extract post_id from URL if not provided
    if not post_id:
        post_id = _extract_x_status_id(post_url) or "unknown"
    if not author:
        author = _extract_x_author(post_url)

    logger.info("processing_video: %s @%s", post_id, author)

    # 1. Download / extract media
    logger.info("download_stage_start: post_id=%s", post_id)
    audio_path = download_video(post_url)
    if not audio_path:
        video_urls, image_urls = _fetch_x_media_urls(post_url)
        if image_urls and not video_urls:
            logger.info("no_video_found_using_image_vision: images=%d", len(image_urls))
            analysis = analyze_images(
                image_urls=image_urls,
                author=author,
                post_text=post_text,
                openai_api_key=openai_api_key,
            )
            if "error" in analysis:
                return {"error": "Failed to analyze image-only post", "post_id": post_id}
            imessage_summary = format_imessage_summary(author, analysis)
            return {
                "post_id": post_id,
                "author": author,
                "summary": imessage_summary,
                "analysis": analysis,
                "transcript_path": "",
                "transcript_length": 0,
                "mode": "image_vision",
            }
        return {"error": "Failed to download video", "post_id": post_id}

    # 2. Transcribe
    transcript = transcribe_audio(audio_path, openai_api_key=openai_api_key)
    if not transcript:
        return {"error": "Failed to transcribe audio", "post_id": post_id}
    if len(transcript.strip()) <= 1:
        logger.error("transcription_too_short: %d chars", len(transcript.strip()))
        return {"error": "Transcription too short; likely bad audio extraction", "post_id": post_id}

    # 3. Analyze
    analysis = analyze_transcript(
        transcript=transcript,
        author=author,
        post_text=post_text,
        openai_api_key=openai_api_key,
    )

    # 4. Save (best-effort — don't fail if directory doesn't exist)
    transcript_path = ""
    try:
        transcript_path = save_transcript(post_id, author, transcript, analysis)
    except Exception as e:
        logger.error("save_transcript_failed: %s", str(e)[:100])

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
