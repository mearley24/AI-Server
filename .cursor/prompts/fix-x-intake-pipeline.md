-- fix-x-intake-pipeline.md --
-- Run with Claude Code: cd ~/AI-Server && claude --
-- Read .clinerules first for full project context --

GOAL: Fix three bugs in the x-intake video transcription pipeline. All bugs are in integrations/x_intake/

Read the docker logs for context:
cd ~/AI-Server && docker compose logs x-intake --tail 150 2>&1 | grep -v "health"


BUG 1: CONTAINER RESTARTS MID-TRANSCRIPTION
---------------------------------------------
Symptom: The @svpino video (587 seconds, 9.5MB) downloaded and transcribed successfully (7,871 chars via OpenAI Whisper API), then the container restarted before the LLM analysis reply was sent. Same with @juliangoldieseo. The user never gets the result.

Likely cause: Docker healthcheck timeout. The healthcheck fires every 30s and if the container is busy transcribing a 10-minute video for 60+ seconds, the health endpoint doesn't respond, Docker marks it unhealthy and restarts.

Fix options (implement all):
1. In docker-compose.yml under x-intake healthcheck: increase timeout to 120s and retries to 5. Long transcriptions can take 2-3 minutes.
2. In main.py: Run the heavy pipeline (_analyze_url) in a background asyncio task so the main event loop stays responsive to health checks. The Redis listener should spawn the analysis as a task, not await it inline.
3. In video_transcriber.py: For videos longer than 300 seconds (5 min), chunk the audio into 5-minute segments before sending to Whisper API. This prevents a single 10-minute upload from blocking. Use ffmpeg to split: ffmpeg -i input.m4a -f segment -segment_time 300 -c copy chunk_%03d.m4a


BUG 2: FFMPEG AUDIO EXTRACTION FAILS ON SOME VIDEOS
------------------------------------------------------
Symptom: @0x__tom's video downloaded as MP4 (8.7MB) but ffmpeg errored:
"Output file does not contain any stream" and "Error opening output file: Invalid argument"

Root cause: The MP4 container has no separate audio track — its a screen recording or the audio is muxed differently. The current ffmpeg command uses -vn (strip video, keep audio) but there is no audio-only stream to keep.

Fix in video_transcriber.py:
1. First try: ffmpeg -y -i input.mp4 -vn -acodec aac output.m4a (current approach)
2. If that fails, try: ffmpeg -y -i input.mp4 -map 0:a:0 -c:a aac output.m4a (explicit audio stream mapping)
3. If that also fails (truly no audio), check if the video has ANY audio at all: ffprobe -v quiet -show_streams -select_streams a input.mp4
4. If ffprobe shows no audio streams, skip transcription and fall through to image/text analysis. Log: "video_has_no_audio_stream — skipping transcription"
5. Also fix the yt-dlp audio extraction: the first attempt with --extract-audio fails with "unable to obtain file audio codec with ffprobe" because the downloaded file format isn't recognized. After yt-dlp --extract-audio fails, try downloading the full video first then extracting audio with ffmpeg as step 1-4 above.


BUG 3: 'str' OBJECT HAS NO ATTRIBUTE 'get' 
----------------------------------------------
Symptom: First link (@shedntcare_) had no video, image vision analysis succeeded (3 flags, 3 strategies), then main.py line crashed with: video_transcription_unavailable error="'str' object has no attribute 'get'"

Root cause: In main.py _analyze_url(), the process_x_video function returns different types depending on the path:
- Video path: returns a dict with "summary", "transcript_length", etc.
- Image vision path: returns a string (the formatted summary) 
- Error path: returns a dict with "error" key

The code after the call assumes it always gets a dict and calls result.get() — but on the image vision path its a string.

Fix in main.py _analyze_url():
1. After calling process_x_video(), check the return type: if isinstance(result, str), wrap it as {"summary": result, "has_video": False, "has_images": True}
2. Make sure all code paths through process_x_video return a consistent dict format. Check every return statement in video_transcriber.py process_x_video() and normalize them.
3. The image analysis is working (it found 3 flags and 3 strategies) — the data is there, its just not making it through to the LLM analysis and iMessage reply because of the type error.


ADDITIONAL IMPROVEMENT: GALLERY-DL FALLBACK
----------------------------------------------
The logs show: "downloader_not_installed (yt-dlp/gallery-dl/ffmpeg missing)" — gallery-dl is referenced as a fallback but not installed in the container.

Fix: Add gallery-dl to requirements.txt. It handles image galleries and some video downloads that yt-dlp misses.
Also add it to the Dockerfile: pip install gallery-dl


TESTING:
After all fixes, rebuild and test with all three types of posts:
1. Video post: docker compose exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 PUBLISH events:imessage '{"text":"https://x.com/svpino/status/2042258928596390359"}'
2. Image-only post: docker compose exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 PUBLISH events:imessage '{"text":"https://x.com/shedntcare_/status/2042491865216454801"}'
3. Screen recording (no audio track): docker compose exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 PUBLISH events:imessage '{"text":"https://x.com/0x__tom/status/2042531411517935834"}'

Verify in logs that:
- Video post: downloads, transcribes, analyzes, sends iMessage reply WITHOUT container restart
- Image post: skips transcription cleanly, does vision analysis, sends reply
- Screen recording: handles missing audio gracefully, falls back to text/image analysis

Rebuild: docker compose up -d --build x-intake
Logs: docker compose logs -f x-intake 2>&1 | grep -v "health"

Commit when all three tests pass.
