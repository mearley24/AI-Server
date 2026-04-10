echo "=== Cline Setup for Bob ==="
echo ""

echo "Step 1: Checking VS Code..."
if command -v code &> /dev/null; then
    echo "  VS Code found: $(which code)"
else
    echo "  VS Code CLI not found."
    echo "  Open VS Code > Cmd+Shift+P > 'Shell Command: Install code command in PATH'"
    echo "  Then re-run this script."
    exit 1
fi

echo ""
echo "Step 2: Installing Cline extension..."
code --install-extension saoudrizwan.claude-dev 2>/dev/null && echo "  Cline installed" || echo "  Cline may already be installed"

echo ""
echo "Step 3: Checking Node.js (needed for MCP servers)..."
if command -v node &> /dev/null; then
    echo "  Node.js found: $(node --version)"
else
    echo "  Node.js not found. Install via: brew install node"
fi

echo ""
echo "Step 4: Checking yt-dlp (needed for X video transcription)..."
if command -v yt-dlp &> /dev/null; then
    echo "  yt-dlp found: $(yt-dlp --version)"
else
    echo "  Installing yt-dlp..."
    brew install yt-dlp 2>/dev/null || pip3 install --break-system-packages yt-dlp
fi

echo ""
echo "Step 5: Checking ffmpeg (needed for audio extraction)..."
if command -v ffmpeg &> /dev/null; then
    echo "  ffmpeg found"
else
    echo "  Installing ffmpeg..."
    brew install ffmpeg
fi

echo ""
echo "Step 6: Setting up Cline configuration..."

CLINE_SETTINGS_DIR="$HOME/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings"
mkdir -p "$CLINE_SETTINGS_DIR"

OPENAI_KEY=$(grep "^OPENAI_API_KEY=" ~/AI-Server/.env 2>/dev/null | head -1 | cut -d= -f2)

if [ -n "$OPENAI_KEY" ]; then
    echo "  OpenAI key found in .env"
    echo "  Configure in Cline:"
    echo "    1. Open VS Code > Click Cline icon (sidebar)"
    echo "    2. Click settings gear"
    echo "    3. Provider: OpenAI"
    echo "    4. API Key: (paste from .env)"
    echo "    5. Model: gpt-4o"
    echo ""
    echo "  Or for cheaper usage with OpenRouter:"
    echo "    1. Sign up at openrouter.ai"
    echo "    2. Provider: OpenRouter"
    echo "    3. Use Claude Sonnet or GPT-4o at lower rates"
else
    echo "  No OPENAI_API_KEY found in ~/AI-Server/.env"
    echo "  You will need to add it manually in Cline settings"
fi

echo ""
echo "Step 7: Verifying .clinerules..."
if [ -f ~/AI-Server/.clinerules ]; then
    echo "  .clinerules found ($(wc -l < ~/AI-Server/.clinerules) lines)"
    echo "  Cline will auto-load these rules when you open ~/AI-Server"
else
    echo "  WARNING: .clinerules not found in ~/AI-Server"
    echo "  Run: cd ~/AI-Server && bash scripts/pull.sh"
fi

echo ""
echo "Step 8: Listing available prompts..."
PROMPT_COUNT=$(ls ~/AI-Server/.cursor/prompts/*.md 2>/dev/null | wc -l | tr -d ' ')
echo "  $PROMPT_COUNT prompts available in .cursor/prompts/"
echo "  Cline can read these directly — just say:"
echo "    'Read .cursor/prompts/cortex-memory-system.md and build it'"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start:"
echo "  cd ~/AI-Server && code ."
echo ""
echo "Then click the Cline icon in the sidebar and start chatting."
echo "Cline reads .clinerules automatically for project context."
echo ""
echo "Quick test prompt:"
echo "  'Read .clinerules and tell me what you understand about this project'"
