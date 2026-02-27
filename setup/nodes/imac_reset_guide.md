# iMac Reset Guide — Maestro & Stagehand

Quick reference for factory-resetting the two Intel iMacs and provisioning them as Symphony nodes.

---

## Why Reset First?

Both iMacs were used machines. A clean macOS install ensures:
- No software conflicts with Ollama or HARPA
- No stale SSH host keys that would confuse Bob
- No previous user accounts or network configurations
- Clean launchd state (no orphaned services)
- Known-good starting point for `provision_node.sh`

---

## Part 1: Erase All Content and Settings (macOS 13 Ventura / 14 Sonoma / 15 Sequoia)

> **This applies to macOS 13+.** For older macOS versions, see the section below.

### Step 1: Prepare
- Ensure the iMac has power and is connected to the Symphony LAN via Ethernet (faster and more reliable than WiFi for the initial setup)
- Back up anything you want to keep — this is irreversible
- Have Bob's IP address ready (run `ipconfig getifaddr en0` on Bob)

### Step 2: Erase via System Settings
1. Click the **Apple menu** () → **System Settings**
2. Click **General** in the left sidebar
3. Scroll down and click **Transfer or Reset**
4. Click **Erase All Content and Settings**
5. Enter your admin password when prompted
6. Follow the on-screen prompts — the Mac will restart and show the Setup Assistant

> **macOS 15.x note**: The path is the same. On Sequoia 15.7.4, you may see a brief "preparing erase" step that takes a few minutes before the restart.

### Step 3: Complete Minimal macOS Setup
When Setup Assistant appears after the erase:
1. **Language / Region**: English / United States
2. **Accessibility**: Skip
3. **WiFi**: Connect to the Symphony LAN (or skip if using Ethernet)
4. **Data & Privacy**: Continue
5. **Migration Assistant**: Click "Not Now" — do NOT migrate data
6. **Apple ID**: Click "Set Up Later" → Skip — **worker nodes should not be signed into an Apple ID**. This avoids iCloud sync complications and ensures the machine is purely a network worker.
7. **Terms & Conditions**: Agree
8. **Create a Computer Account**:
   - **Full name**: `symphony`
   - **Account name**: `symphony` (auto-filled)
   - **Password**: Use a strong shared password, store in your team password manager
9. **Analytics**: Uncheck everything → Continue
10. **Screen Time**: Set Up Later
11. **Siri**: Disable Siri (saves CPU on worker nodes)
12. **Appearance**: Light or Auto (doesn't matter)
13. Click "Start Using Mac"

---

## Part 2: Reset — macOS 12 Monterey or Earlier (Fallback)

If an iMac can't run macOS 13, use Recovery Mode:

1. Restart the iMac and immediately hold **Cmd (⌘) + R** until you see the Apple logo
2. In the macOS Recovery menu, click **Disk Utility**
3. In Disk Utility, select **Macintosh HD** (the main system volume)
4. Click **Erase** → Format: **APFS** → Erase
5. Close Disk Utility
6. Click **Reinstall macOS** and follow prompts
7. Complete the minimal setup as described above

> Note: To update the iMac to macOS 13+ (required for `Erase All Content and Settings`), complete a basic macOS setup first, then update via System Settings → Software Update.

---

## Part 3: Set Hostname Post-Reset

`provision_node.sh` handles hostname setting automatically, but here's how to do it manually if needed. The hostname must be set before Bob can locate the node via mDNS.

### Option A: Via Terminal (Recommended)
```bash
# Open Terminal (Applications → Utilities → Terminal)

# For Maestro (Intel iMac 27-inch, 64GB):
sudo scutil --set ComputerName  "Maestro"
sudo scutil --set HostName      "maestro"
sudo scutil --set LocalHostName "maestro"
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

# For Stagehand (Intel iMac, 8GB):
sudo scutil --set ComputerName  "Stagehand"
sudo scutil --set HostName      "stagehand"
sudo scutil --set LocalHostName "stagehand"
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

### Option B: Via System Settings
1. System Settings → General → Sharing
2. Change "Computer Name" to `Maestro` or `Stagehand`
3. Click "Edit..." next to Local Hostname → set to `maestro` or `stagehand`

### Verify hostname is set
```bash
hostname         # Should return: maestro
scutil --get ComputerName   # Should return: Maestro
scutil --get LocalHostName  # Should return: maestro
```

---

## Part 4: Run provision_node.sh

Copy the provisioning script to the iMac and run it.

### Copy the scripts from Bob
```bash
# From Bob (or your laptop), copy the setup files to the newly reset iMac:
scp ~/path/to/setup/nodes/provision_node.sh symphony@maestro.local:~/provision_node.sh
# Repeat for Stagehand
scp ~/path/to/setup/nodes/provision_node.sh symphony@stagehand.local:~/provision_node.sh
```

### Run on Maestro (llm_worker — Ollama + HARPA)
```bash
# SSH into Maestro
ssh symphony@maestro.local

# Run provisioner
chmod +x provision_node.sh
./provision_node.sh \
  --hostname maestro \
  --role llm_worker \
  --bob-ip 192.168.1.10    # ← Replace with Bob's actual IP
```

**What this installs on Maestro:**
- Homebrew
- Ollama (configured with `OLLAMA_HOST=0.0.0.0` for remote access)
- Base models: `llama3.1:8b`, `mistral:7b`, `nomic-embed-text` (pulls ~8GB total)
- Optional larger pull: `ollama pull llama3.1:70b` (manually, ~40GB — plan for slow download)
- launchd auto-start plist for Ollama
- Heartbeat cron to Bob

**After script completes on Maestro:**
1. Install Chrome and HARPA manually (script installs Chrome, HARPA needs extension install in browser)
2. Log in to HARPA Grid to accept automation tasks
3. Log in to D-Tools Cloud in Chrome (persistent session for HARPA)

### Run on Stagehand (browser_node — HARPA only)
```bash
# SSH into Stagehand
ssh symphony@stagehand.local

chmod +x provision_node.sh
./provision_node.sh \
  --hostname stagehand \
  --role browser_node \
  --bob-ip 192.168.1.10    # ← Replace with Bob's actual IP
```

**What this installs on Stagehand:**
- Homebrew
- Google Chrome
- Setup guide at `~/.symphony/harpa_setup_instructions.txt`
- Heartbeat cron to Bob

> Stagehand does NOT get Ollama. With only 8GB RAM, any LLM inference would be slow and would consume the RAM Chrome needs for HARPA to run well.

---

## Part 5: Verify Connection from Bob

After both iMacs are provisioned, verify from Bob:

```bash
# On Bob — check both nodes appear and are reachable
python3 ~/.symphony/node_health_monitor.py

# Test SSH to Maestro (should be passwordless after key setup)
ssh maestro.local "hostname && ollama list"

# Test Ollama API on Maestro (replace with Maestro's real IP)
curl http://maestro.local:11434/api/tags | python3 -m json.tool

# Test a real inference request to Maestro
curl http://maestro.local:11434/api/generate \
  -d '{"model": "llama3.1:8b", "prompt": "Say: Maestro online.", "stream": false}'

# Verify Stagehand heartbeat is reaching Bob
tail -20 ~/.symphony/logs/heartbeat_received.log
```

---

## Part 6: Update nodes_registry.json with Real IPs

After provisioning, update the registry with actual IP addresses:

```bash
# Find Maestro's IP
ssh maestro.local "ipconfig getifaddr en0"

# Find Stagehand's IP  
ssh stagehand.local "ipconfig getifaddr en0"

# Edit the registry on Bob
nano ~/.symphony/registry/nodes_registry.json
# Update "ip" fields for maestro and stagehand entries
```

---

## Appendix: What provision_node.sh Does (Brief Summary)

| Step | What Happens |
|------|--------------|
| 1 | Sets hostname (ComputerName, HostName, LocalHostName) via `scutil` |
| 2 | Enables SSH via `systemsetup -setremotelogin on` |
| 3 | Installs Homebrew (if not present) |
| 4 | Installs role-specific software (Ollama, Docker, Chrome) |
| 5 | Configures Ollama for remote access (`OLLAMA_HOST=0.0.0.0`) |
| 6 | Creates Ollama launchd plist for auto-start on boot |
| 7 | Pulls base LLM models (slow step — depends on internet speed) |
| 8 | Sets up `~/.symphony/` directory structure |
| 9 | Configures heartbeat cron to ping Bob every 60 seconds |
| 10 | Attempts self-registration with Bob's registry API |
| 11 | Saves HARPA setup instructions to `~/.symphony/harpa_setup_instructions.txt` |
