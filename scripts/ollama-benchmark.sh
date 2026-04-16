#!/bin/zsh
set -euo pipefail

HOST="${1:-http://127.0.0.1:11434}"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
HOSTNAME_SHORT=$(hostname -s)
OUTFILE="data/benchmarks/ollama_${HOSTNAME_SHORT}_${TIMESTAMP}.md"
mkdir -p data/benchmarks

printf '## Ollama Benchmark: %s\n' "$HOSTNAME_SHORT" > "$OUTFILE"
printf 'Date: %s\n' "$(date)" >> "$OUTFILE"
printf 'Host: %s\n\n' "$HOST" >> "$OUTFILE"

printf '| Model | Size | Eval Rate (tok/s) | Prompt Rate (tok/s) | Status |\n' >> "$OUTFILE"
printf '|-------|------|-------------------|---------------------|--------|\n' >> "$OUTFILE"

TEST_PROMPT="Explain the concept of supply and demand in economics in exactly three sentences."

benchmark_model() {
  local model="$1"
  printf 'Benchmarking %s...\n' "$model"

  ollama pull "$model" 2>/dev/null || true

  local result
  result=$(curl -s -X POST "${HOST}/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"${model}\", \"prompt\": \"${TEST_PROMPT}\", \"stream\": false, \"options\": {\"temperature\": 0}}" \
    --max-time 120 2>/dev/null || echo "TIMEOUT")

  if [ "$result" = "TIMEOUT" ]; then
    printf '| %s | - | TIMEOUT | TIMEOUT | FAIL |\n' "$model" >> "$OUTFILE"
    printf '  %s: TIMEOUT\n' "$model"
    return
  fi

  local eval_count eval_duration prompt_count prompt_duration
  eval_count=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('eval_count',0))" 2>/dev/null || echo "0")
  eval_duration=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('eval_duration',1))" 2>/dev/null || echo "1")
  prompt_count=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('prompt_eval_count',0))" 2>/dev/null || echo "0")
  prompt_duration=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('prompt_eval_duration',1))" 2>/dev/null || echo "1")

  local eval_rate prompt_rate model_size
  eval_rate=$(python3 -c "print(f'{${eval_count}/(${eval_duration}/1e9):.1f}')" 2>/dev/null || echo "0")
  prompt_rate=$(python3 -c "print(f'{${prompt_count}/(${prompt_duration}/1e9):.1f}')" 2>/dev/null || echo "0")
  model_size=$(ollama list 2>/dev/null | grep "^${model}" | awk '{print $3 $4}' || echo "?")

  printf '| %s | %s | %s | %s | OK |\n' "$model" "$model_size" "$eval_rate" "$prompt_rate" >> "$OUTFILE"
  printf '  %s: %s tok/s eval, %s tok/s prompt\n' "$model" "$eval_rate" "$prompt_rate"
}

printf '\nStarting benchmarks against %s...\n\n' "$HOST"

benchmark_model "llama3.2:3b"
benchmark_model "llama3.2:1b"
benchmark_model "gemma3:4b"
benchmark_model "phi4-mini:3.8b"
benchmark_model "qwen3:4b"
benchmark_model "llama3.1:8b"
benchmark_model "gemma3:12b"

printf '\n### Memory After Benchmarks\n\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"
ollama ps >> "$OUTFILE" 2>/dev/null || printf 'ollama ps unavailable\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"

printf '\n### System Info\n\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"
system_profiler SPHardwareDataType 2>/dev/null | grep -E "Chip|Memory|Cores" >> "$OUTFILE" || printf 'system_profiler unavailable\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"

printf '\nBenchmark complete. Results saved to %s\n' "$OUTFILE"
cat "$OUTFILE"
