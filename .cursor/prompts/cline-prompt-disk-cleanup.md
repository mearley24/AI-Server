# Cline Prompt: Emergency Disk Cleanup on Bob

## IMPORTANT — Read First
Bob's disk is full. We need to free space immediately. Be careful — do NOT delete any data that's part of the pipeline.

## Step 1: Assess the damage
```
df -h /
du -sh ~/AI-Server/data/* 2>/dev/null | sort -rh | head -20
du -sh /tmp/* 2>/dev/null | sort -rh | head -10
```

## Step 2: Docker cleanup (biggest win)
Docker images, build cache, and stopped containers eat massive space.

```
docker system df
docker system prune -a --volumes -f
docker builder prune -a -f
```

This removes:
- All unused images (they rebuild from docker-compose anyway)
- Build cache
- Stopped containers
- Unused volumes (NOT named volumes with data)

**WARNING**: Named volumes with data (like `x-intake-lab-data`, `redis_data`) are preserved by `docker system prune`. But verify with `docker volume ls` before and after.

## Step 3: Clean Ollama model cache
The benchmark pulled 7 models. Remove the ones we are not using:

```
ollama list
ollama rm gemma3:12b
ollama rm gemma3:4b
ollama rm phi4-mini:3.8b
ollama rm qwen3:4b
ollama rm llama3.2:1b
```

Keep only `llama3.2:3b` (production) and `llama3.1:8b` (if we decide to use it). That frees ~15GB.

## Step 4: Clean old logs
```
find ~/AI-Server/logs -name "*.log" -mtime +7 -delete 2>/dev/null
find ~/AI-Server -name "*.log" -size +50M -delete 2>/dev/null
find /tmp -name "*.log" -mtime +3 -delete 2>/dev/null
truncate -s 0 /tmp/imessage-bridge.log 2>/dev/null
```

## Step 5: Clean old Docker logs
Docker JSON logs can grow huge:
```
sudo find /var/lib/docker/containers -name "*-json.log" -exec truncate -s 0 {} \; 2>/dev/null
```

On macOS Docker Desktop, the log files are inside the VM. Instead:
```
docker compose logs --tail=0 2>/dev/null
```
The `max-size: 10m` and `max-file: 5` in docker-compose.yml should cap this, but check.

## Step 6: Check for large unexpected files
```
find ~/AI-Server -size +100M -type f 2>/dev/null | head -20
find ~ -size +500M -type f -not -path "*/Library/*" -not -path "*/.Trash/*" 2>/dev/null | head -20
```

## Step 7: Verify space recovered
```
df -h /
```

Target: at least 5GB free. Report what was cleaned and how much space was recovered.

## Step 8: Re-run the benchmark
Once space is free:
```
bash scripts/ollama-benchmark.sh http://127.0.0.1:11434
```

But FIRST remove the benchmark models we do not need (Step 3) so the benchmark only tests what we kept. Edit the benchmark or just run it for the models we care about.

## DO NOT delete
- Anything in `data/` subdirectories (SQLite DBs, transcripts, trades, bookmarks)
- Named Docker volumes with live data
- `.env` file
- Any Python source code

## Commit
If any repo files changed: `fix: disk cleanup — remove unused Ollama models and Docker artifacts`
Push to main.
