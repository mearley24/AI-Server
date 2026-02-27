#!/usr/bin/env bash
# =============================================================================
# test_ollama_worker.sh
# Symphony Smart Homes — Ollama Worker Diagnostic & Test Script
# Target: 2019 iMac (Intel Core i3, 64GB RAM)
#
# Runs a comprehensive diagnostic suite to verify:
#   1. Ollama service is running
#   2. API is responding
#   3. All required models are installed
#   4. bob-classifier produces correct output
#   5. bob-summarizer produces correct output
#   6. Network accessibility from LAN (Bob the Mac Mini M4)
#   7. Performance benchmarks
#
# Usage:
#   chmod +x test_ollama_worker.sh
#   ./test_ollama_worker.sh
#   ./test_ollama_worker.sh --quick   (skip slow inference tests)
#   ./test_ollama_worker.sh --verbose (show full model output)
# =============================================================================

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASS() { echo -e "  ${GREEN}[PASS]${NC} $*"; ((TESTS_PASSED++)); }
FAIL() { echo -e "  ${RED}[FAIL]${NC} $*"; ((TESTS_FAILED++)); }
SKIP() { echo -e "  ${YELLOW}[SKIP]${NC} $*"; ((TESTS_SKIPPED++)); }
INFO() { echo -e "  ${CYAN}[INFO]${NC} $*"; }
HEAD() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}\n"; }

# ── Argument parsing ────────────────────────────────────────────────────────
QUICK_MODE=false
VERBOSE=false

for arg in "$@"; do
  case "$arg" in
    --quick)   QUICK_MODE=true ;;
    --verbose) VERBOSE=true ;;
    *) ;;
  esac
done

# ── Counters ───────────────────────────────────────────────────────────────────
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# ── Helper: API call ──────────────────────────────────────────────────────────
ollama_generate() {
  local model="$1"
  local prompt="$2"
  local timeout="${3:-60}"

  curl -s --max-time "$timeout" -X POST http://localhost:11434/api/generate \
    -H 'Content-Type: application/json' \
    -d "{\"model\": \"$model\", \"prompt\": \"$prompt\", \"stream\": false}" \
    2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('response','').strip())" 2>/dev/null || echo 'ERROR'
}

# ============================================================================
# TEST SUITE
# ============================================================================

echo -e "\n${BOLD}Ollama Worker Diagnostic Suite${NC}"
echo -e "Symphony Smart Homes | $(date)"
$QUICK_MODE && echo -e "${YELLOW}Quick mode: inference tests will be skipped${NC}"
echo ""

# ============================================================================
# Section 1: System checks
# ============================================================================

HEAD "Section 1: System"

# 1.1 macOS check
if [[ "$(uname)" == "Darwin" ]]; then
  PASS "macOS detected: $(sw_vers -productVersion)"
else
  FAIL "Not macOS: $(uname)"
fi

# 1.2 Memory check
RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
if [[ "$RAM_GB" -ge 32 ]]; then
  PASS "RAM: ${RAM_GB}GB"
else
  FAIL "RAM: ${RAM_GB}GB (minimum 32GB recommended for full model suite)"
fi

# 1.3 Disk space check
DISK_FREE_GB=$(df -g / | awk 'NR==2 {print $4}')
if [[ "$DISK_FREE_GB" -ge 20 ]]; then
  PASS "Disk free: ${DISK_FREE_GB}GB"
else
  FAIL "Disk free: ${DISK_FREE_GB}GB (20GB+ recommended for model storage)"
fi

# 1.4 CPU check
CPU_INFO=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'unknown')
INFO "CPU: $CPU_INFO"

# ============================================================================
# Section 2: Ollama binary
# ============================================================================

HEAD "Section 2: Ollama binary"

# 2.1 Ollama installed
if command -v ollama &>/dev/null; then
  OLLAMA_VER=$(ollama --version 2>/dev/null || echo 'unknown')
  PASS "Ollama binary: $OLLAMA_VER"
else
  FAIL "Ollama not found in PATH"
  echo -e "\n${RED}CRITICAL: Ollama not installed. Run setup_ollama_worker.sh first.${NC}"
  exit 1
fi

# 2.2 launchd service
if launchctl list | grep -q 'com.ollama'; then
  PASS "Ollama launchd service is loaded."
else
  FAIL "Ollama launchd service NOT found. Run: launchctl load ~/Library/LaunchAgents/com.ollama.plist"
fi

# ============================================================================
# Section 3: API health
# ============================================================================

HEAD "Section 3: API health"

# 3.1 API responding
if curl -s --max-time 5 http://localhost:11434/ | grep -q 'Ollama'; then
  PASS "Ollama API root: OK"
else
  FAIL "Ollama API root not responding at http://localhost:11434/"
fi

# 3.2 /api/tags endpoint
TAGS_RESPONSE=$(curl -s --max-time 5 http://localhost:11434/api/tags 2>/dev/null || echo '{}')
if echo "$TAGS_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if 'models' in d else 1)" 2>/dev/null; then
  MODEL_COUNT=$(echo "$TAGS_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('models', [])))")
  PASS "/api/tags: $MODEL_COUNT model(s) in library"
else
  FAIL "/api/tags endpoint failed or returned unexpected response"
fi

# ============================================================================
# Section 4: Model availability
# ============================================================================

HEAD "Section 4: Model availability"

REQUIRED_MODELS=("llama3.2:3b" "llama3.1:8b" "mistral:7b" "bob-classifier" "bob-summarizer")

for MODEL in "${REQUIRED_MODELS[@]}"; do
  if ollama list 2>/dev/null | grep -q "^${MODEL}"; then
    MODEL_SIZE=$(ollama list 2>/dev/null | grep "^${MODEL}" | awk '{print $3, $4}' || echo 'size unknown')
    PASS "Model: $MODEL ($MODEL_SIZE)"
  else
    FAIL "Model NOT found: $MODEL"
    case "$MODEL" in
      llama3.2:3b|llama3.1:8b|mistral:7b)
        INFO "  Fix: ollama pull $MODEL"
        ;;
      bob-classifier)
        INFO "  Fix: ollama create bob-classifier -f Modelfile.bob-classifier"
        ;;
      bob-summarizer)
        INFO "  Fix: ollama create bob-summarizer -f Modelfile.bob-summarizer"
        ;;
    esac
  fi
done

# ============================================================================
# Section 5: bob-classifier tests
# ============================================================================

HEAD "Section 5: bob-classifier tests"

if $QUICK_MODE; then
  SKIP "Inference tests skipped (--quick mode)"
else
  # Classification test cases: prompt => expected_result
  declare -A CLASSIFIER_TESTS=(
    ["Control4 EA-5 Programming Guide v3.3.2"]="Manual"
    ["Symphony Smart Homes Proposal for Jones Residence"]="Proposal"
    ["Main Level Floor Plan Sheet A1.2 Lighting Layout"]="Drawing"
    ["Lutron RadioRA 3 Spec Sheet Part Number RR-MAIN-REP-WH"]="Spec"
    ["Hi Mark following up on the proposal from last week"]="Email"
    ["Invoice 2891 Symphony Smart Homes Total 47320"]="Invoice"
  )

  for PROMPT in "${!CLASSIFIER_TESTS[@]}"; do
    EXPECTED="${CLASSIFIER_TESTS[$PROMPT]}"
    INFO "Testing: \"$PROMPT\""
    RESULT=$(ollama_generate "bob-classifier" "$PROMPT" 30)

    if [[ "$VERBOSE" == "true" ]]; then
      INFO "  Raw output: \"$RESULT\""
    fi

    # Normalize: trim whitespace, take first word
    FIRST_WORD=$(echo "$RESULT" | awk '{print $1}' | tr -d '[:punct:]')

    if [[ "$FIRST_WORD" == "$EXPECTED" ]]; then
      PASS "bob-classifier: \"$PROMPT\" → $RESULT"
    else
      FAIL "bob-classifier: \"$PROMPT\" → got \"$RESULT\" (expected \"$EXPECTED\")"
    fi
  done
fi

# ============================================================================
# Section 6: bob-summarizer tests
# ============================================================================

HEAD "Section 6: bob-summarizer tests"

if $QUICK_MODE; then
  SKIP "Inference tests skipped (--quick mode)"
else
  # Single summarization test (full test would take too long)
  SUMMARY_PROMPT="Summarize: Symphony Smart Homes proposal for Williams Residence. 3,200 sq ft. Control4 EA-5, Lutron RadioRA 3 (18 dimmers, 6 keypads, 10 shades), Sonos 6-zone, Luma 6 cameras. Better tier. Total: \$38,500."

  INFO "Running summarization test (may take 30-90 seconds)..."
  SUMMARY_RESULT=$(ollama_generate "bob-summarizer" "$SUMMARY_PROMPT" 120)

  if [[ "$VERBOSE" == "true" ]]; then
    echo "  Output:"
    echo "$SUMMARY_RESULT" | sed 's/^/    /'
  fi

  # Check that the output contains expected structural elements
  if echo "$SUMMARY_RESULT" | grep -qi "Type:"; then
    PASS "bob-summarizer: Output contains 'Type:' field"
  else
    FAIL "bob-summarizer: Output missing 'Type:' field (expected structured format)"
  fi

  if echo "$SUMMARY_RESULT" | grep -qi "Subject:"; then
    PASS "bob-summarizer: Output contains 'Subject:' field"
  else
    FAIL "bob-summarizer: Output missing 'Subject:' field"
  fi

  if echo "$SUMMARY_RESULT" | grep -qi "Key Points:"; then
    PASS "bob-summarizer: Output contains 'Key Points:' section"
  else
    FAIL "bob-summarizer: Output missing 'Key Points:' section"
  fi
fi

# ============================================================================
# Section 7: Network accessibility
# ============================================================================

HEAD "Section 7: Network accessibility"

# Get local IPs
ETH_IP=$(ipconfig getifaddr en1 2>/dev/null || echo '')
WIFI_IP=$(ipconfig getifaddr en0 2>/dev/null || echo '')

if [[ -n "$ETH_IP" ]]; then
  INFO "Ethernet IP (en1): $ETH_IP"
  LAN_IP="$ETH_IP"
elif [[ -n "$WIFI_IP" ]]; then
  INFO "Wi-Fi IP (en0): $WIFI_IP"
  LAN_IP="$WIFI_IP"
else
  FAIL "Could not determine local IP address"
  LAN_IP=""
fi

if [[ -n "$LAN_IP" ]]; then
  # Test LAN accessibility
  if curl -s --max-time 5 "http://${LAN_IP}:11434/api/tags" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0)" 2>/dev/null; then
    PASS "LAN API accessible: http://${LAN_IP}:11434"
  else
    FAIL "LAN API not accessible at http://${LAN_IP}:11434"
    INFO "  Check: System Preferences → Security → Firewall → Allow Ollama"
  fi
fi

# Check OLLAMA_HOST setting
if [[ "${OLLAMA_HOST:-}" == "0.0.0.0:11434" ]]; then
  PASS "OLLAMA_HOST=0.0.0.0:11434 (LAN accessible)"
else
  INFO "OLLAMA_HOST=${OLLAMA_HOST:-not set} (check ollama_worker.env)"
fi

# ============================================================================
# Section 8: Performance benchmark
# ============================================================================

HEAD "Section 8: Performance benchmark"

if $QUICK_MODE; then
  SKIP "Performance benchmarks skipped (--quick mode)"
else
  INFO "Running bob-classifier speed test (10 requests)..."
  START_TIME=$(date +%s%N)

  for i in $(seq 1 10); do
    ollama_generate "bob-classifier" "Control4 EA-5 Installation Guide" 30 >/dev/null 2>&1
  done

  END_TIME=$(date +%s%N)
  ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))
  AVG_MS=$(( ELAPSED_MS / 10 ))

  INFO "  10 classification requests: ${ELAPSED_MS}ms total, ${AVG_MS}ms avg"

  if [[ "$AVG_MS" -lt 5000 ]]; then
    PASS "Classifier speed: ${AVG_MS}ms avg (target: <5000ms)"
  elif [[ "$AVG_MS" -lt 10000 ]]; then
    PASS "Classifier speed: ${AVG_MS}ms avg (acceptable, slightly slow)"
  else
    FAIL "Classifier speed: ${AVG_MS}ms avg (too slow, >10s per request)"
  fi
fi

# ============================================================================
# Section 9: Logs check
# ============================================================================

HEAD "Section 9: Log files"

LOG_FILE="$HOME/Library/Logs/ollama_worker.log"
ERR_LOG="$HOME/Library/Logs/ollama_worker_error.log"

if [[ -f "$LOG_FILE" ]]; then
  LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
  LAST_LINE=$(tail -1 "$LOG_FILE" 2>/dev/null || echo 'empty')
  PASS "Log file exists: $LOG_FILE ($LOG_SIZE)"
  INFO "  Last log entry: $LAST_LINE"
else
  FAIL "Log file not found: $LOG_FILE"
  INFO "  Expected after launchd starts the service"
fi

if [[ -f "$ERR_LOG" ]]; then
  ERR_SIZE=$(du -h "$ERR_LOG" | cut -f1)
  ERR_COUNT=$(wc -l < "$ERR_LOG" 2>/dev/null || echo '0')
  if [[ "$ERR_COUNT" -eq 0 ]]; then
    PASS "Error log: empty (good)"
  else
    PASS "Error log: $ERR_COUNT lines (check if errors are significant: tail -20 $ERR_LOG)"
  fi
else
  INFO "Error log not found (may not exist yet if no errors have occurred)"
fi

# ============================================================================
# SUMMARY
# ============================================================================

echo ""
echo -e "${BOLD}=== TEST SUMMARY ===${NC}"
echo -e "  ${GREEN}PASSED:  $TESTS_PASSED${NC}"
echo -e "  ${RED}FAILED:  $TESTS_FAILED${NC}"
echo -e "  ${YELLOW}SKIPPED: $TESTS_SKIPPED${NC}"
echo ""

if [[ "$TESTS_FAILED" -eq 0 ]]; then
  echo -e "${GREEN}${BOLD}All tests passed! Ollama Worker Node is healthy.${NC}"
  exit 0
else
  echo -e "${RED}${BOLD}$TESTS_FAILED test(s) failed. Review output above.${NC}"
  echo -e "For detailed help, see README.md"
  exit 1
fi
