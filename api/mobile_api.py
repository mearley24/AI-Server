#!/usr/bin/env python3
"""
mobile_api.py - REST API for Symphony AI iOS App

Provides endpoints for:
- System status and health
- Quick actions (bids, proposals, invoices)
- Knowledge search
- Service status dashboard

Run: python3 mobile_api.py
Access: http://localhost:8420

For remote access via Tailscale:
  http://bob-mac-mini.tail1234.ts.net:8420
"""

import asyncio
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR / "api"))
try:
    from api.common_api_utils import run_command as shared_run_command, run_tool_script
except ModuleNotFoundError:
    from common_api_utils import run_command as shared_run_command, run_tool_script

# FastAPI with fallback to simple HTTP server
try:
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    print("FastAPI not installed. Run: pip install fastapi uvicorn")

sys.path.insert(0, str(BASE_DIR))

API_PORT = int(os.environ.get("MOBILE_API_PORT", "8420"))
DTOOLS_PRODUCT_AGENT_DIR = BASE_DIR / "data" / "dtools_product_agent"
DTOOLS_PRODUCT_AGENT_DIR.mkdir(parents=True, exist_ok=True)

if HAS_FASTAPI:
    app = FastAPI(
        title="Symphony AI Mobile API",
        description="REST API for Symphony Smart Homes AI Operations",
        version="1.0.0"
    )
    
    # Allow CORS for mobile app
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --- Helper Functions ---

def _extract_json_from_output(result: Dict, fallback_key: str = "output") -> Dict:
    """Parse JSON from run_command output; return clean result for API consumers."""
    output = result.get("output", "")
    if not output:
        return {"success": False, "error": result.get("error", "No output")}
    # Handle output that may have progress text before JSON (e.g. "Checking...\n{...}")
    try:
        data = json.loads(output)
        return data
    except json.JSONDecodeError:
        pass
    # Try to extract JSON object from output
    import re
    match = re.search(r'\{[\s\S]*\}', output)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"success": False, "error": "Could not parse output", fallback_key: output[:500]}


def run_command(cmd: List[str], timeout: int = 30) -> Dict:
    """Run a command and return result."""
    return shared_run_command(cmd, timeout=timeout, cwd=BASE_DIR)


def run_tool_endpoint(script: str, args: List[str], timeout: int = 60) -> Dict:
    """Run a tools/ script and return {success, output, error}."""
    return run_tool_script(BASE_DIR, script, args=args, timeout=timeout)


def _to_money(value: Any) -> Optional[float]:
    """Coerce numeric-ish value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick_unit_cost(prices: List[float], dealer_tier: str) -> Optional[float]:
    """
    Price columns expected in many manufacturer sheets:
    MSRP, Standard, Silver, Gold, Dist/Fab
    """
    if len(prices) < 2:
        return None
    tier = (dealer_tier or "standard").strip().lower()
    if tier == "fabricator":
        idx = 4
    elif tier == "gold":
        idx = 3
    elif tier == "silver":
        idx = 2
    else:
        idx = 1
    if idx < len(prices):
        return prices[idx]
    return prices[-1]


def _looks_like_price_line(line: str) -> bool:
    nums = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})", line)
    return len(nums) >= 2


def _extract_part_number_from_line(line: str) -> Optional[str]:
    upper = line.upper().strip()
    # Prefer SKU-like tokens whose first segment is alpha-heavy.
    tokens = re.findall(r"[A-Z0-9#]+(?:-[A-Z0-9#]+)+", upper)
    if not tokens:
        return None
    candidates: List[str] = []
    for token in tokens:
        parts = token.split("-")
        first = parts[0]
        if first.isdigit():
            continue
        if len(first) < 3:
            continue
        if first.endswith("YR"):
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
            continue
        if token.startswith("Q") and token[1:].isdigit():
            continue
        if len(parts) == 2 and parts[1].isdigit() and first in {"POE", "DC"}:
            continue
        if "WARRANTY" in token:
            continue
        if not any(ch.isalpha() for ch in token):
            continue
        candidates.append(token)
    if not candidates:
        return None
    # Usually the SKU is the longest code in the row.
    return sorted(candidates, key=len, reverse=True)[0]


def _extract_text_from_pdf(path: Path) -> str:
    """Extract PDF text using pypdf, with pdftotext fallback."""
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        chunks: List[str] = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks)
    except Exception:
        try:
            # macOS/homebrew fallback.
            result = subprocess.run(
                ["pdftotext", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except Exception:
            pass
        raise RuntimeError(
            "Could not parse PDF text. Install pypdf (`pip3 install pypdf`) or ensure pdftotext is installed."
        )


def _parse_price_sheet_text(text: str, dealer_tier: str) -> List[Dict[str, Any]]:
    """
    Parse semi-structured price-book text into D-Tools product drafts.
    Works best for sheets with rows that include a SKU and nearby pricing line.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    products: List[Dict[str, Any]] = []

    def _is_noise_line(value: str) -> bool:
        up = value.upper()
        return (
            "PRICE BOOK" in up
            or "MODEL NAME" in up
            or "PART NUMBER" in up
            or "ALL BRAND NAMES" in up
            or "ARE THE PROPERTY" in up
            or "DEALER LEVEL" in up
            or "TERMS:" in up
            or up.startswith("-- ")
            or up.startswith("#")
        )

    # Pass 1: detect SKU anchors.
    sku_rows: List[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if _is_noise_line(line):
            continue
        part = _extract_part_number_from_line(line)
        if not part:
            continue
        words = line.split()
        if line.strip().upper() == part:
            sku_rows.append((idx, part))
            continue
        if line.strip().upper().endswith(part) and len(words) <= 6:
            sku_rows.append((idx, part))

    for row_idx, (start, part) in enumerate(sku_rows):
        end = sku_rows[row_idx + 1][0] if row_idx + 1 < len(sku_rows) else min(len(lines), start + 35)
        block = lines[start + 1:end]

        # Model: nearest previous human-readable line.
        model = ""
        j = start - 1
        while j >= 0:
            prev = lines[j].strip()
            if _is_noise_line(prev):
                j -= 1
                continue
            if "MADE IN USA" in prev.upper():
                j -= 1
                continue
            if _extract_part_number_from_line(prev):
                j -= 1
                continue
            prev_upper = prev.upper()
            if any(
                word in prev_upper
                for word in ["DEALER", "MSRP", "SKU", "DESCRIPTION", "WARRANTY", "NOW", "Q226", "Q326", "Q426"]
            ):
                j -= 1
                continue
            if re.search(r"[A-Za-z]", prev):
                model = prev
                break
            j -= 1
        if not model:
            model = part

        # Description: text lines before dense pricing starts.
        desc_parts: List[str] = []
        prices: List[float] = []
        for ln in block:
            nums = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})", ln)
            if nums:
                prices.extend([float(n.replace(",", "")) for n in nums])
                continue
            up = ln.upper()
            if (
                "$" in ln
                or up in {"NOW", "Q226", "Q326", "Q426"}
                or _extract_part_number_from_line(ln)
                or _is_noise_line(ln)
            ):
                continue
            if len(ln) <= 2:
                continue
            desc_parts.append(ln)

        prices = prices[:5]
        if not prices:
            # Some PDFs print price columns before SKU in reading order.
            nearby = lines[max(0, start - 20):end]
            backfill: List[float] = []
            for ln in nearby:
                nums = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})", ln)
                backfill.extend([float(n.replace(",", "")) for n in nums])
                if len(backfill) >= 5:
                    break
            prices = backfill[:5]
        msrp = prices[0] if prices else None
        unit_cost = _pick_unit_cost(prices, dealer_tier)
        unit_price = msrp
        short_desc = " ".join(desc_parts).strip()
        if len(short_desc) > 300:
            short_desc = short_desc[:297] + "..."
        if not short_desc:
            short_desc = f"{model} {part}".strip()

        up_model = model.upper()
        if "TERMS" in up_model or "DEALER LEVEL" in up_model:
            continue

        bad_model_tokens = ["DEALER", "WARRANTY", "AVAIL", "Q226", "Q326", "Q426"]
        if any(tok in up_model for tok in bad_model_tokens):
            model = part
        if model.startswith("10YR") or model.startswith("Q") or "/" in model:
            model = part

        keywords = ", ".join([kw for kw in ["Modern Atomics", model, part, "power", "pdu"] if kw])
        products.append(
            {
                "brand": "Modern Atomics",
                "model": model.replace("™", "").replace("®", "").strip(),
                "part_number": part.strip(),
                "category": "Power Management",
                "short_description": short_desc,
                "keywords": keywords[:280],
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "msrp": msrp,
                "supplier": "Modern Atomics",
            }
        )

    # Deduplicate by part number.
    dedup: Dict[str, Dict[str, Any]] = {}
    for p in products:
        key = (p.get("part_number") or "").upper()
        if key and key not in dedup:
            dedup[key] = p
    return list(dedup.values())


def _parse_sheet_file(path: Path, dealer_tier: str) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        parsed: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                model = (row.get("Model") or row.get("MODEL") or row.get("Name") or "").strip()
                part = (row.get("Part Number") or row.get("SKU") or row.get("Part") or "").strip()
                if not model and not part:
                    continue
                msrp = _to_money(row.get("MSRP"))
                unit_cost = _to_money(row.get("Dealer") or row.get("Cost"))
                parsed.append(
                    {
                        "brand": (row.get("Brand") or row.get("Manufacturer") or "Unknown").strip(),
                        "model": model or part,
                        "part_number": part,
                        "category": (row.get("Category") or "General").strip(),
                        "short_description": (row.get("Description") or "").strip()[:300],
                        "keywords": ", ".join(
                            [
                                k
                                for k in [
                                    row.get("Brand", ""),
                                    model,
                                    part,
                                ]
                                if k
                            ]
                        )[:280],
                        "unit_price": msrp,
                        "unit_cost": unit_cost,
                        "msrp": msrp,
                        "supplier": (row.get("Supplier") or row.get("Brand") or "").strip(),
                    }
                )
        return parsed

    if suffix == ".pdf":
        text = _extract_text_from_pdf(path)
        return _parse_price_sheet_text(text, dealer_tier)

    raise RuntimeError(f"Unsupported file type: {suffix}. Use PDF or CSV.")


def get_launchd_job_status(label: str) -> Dict:
    """Return launchd status details for a given label."""
    status = {
        "label": label,
        "loaded": False,
        "running": False,
        "pid": None,
        "last_exit_code": None,
        "plist_exists": False,
        "plist_path": None,
    }
    plist_candidates = [
        Path.home() / "Library" / "LaunchAgents" / f"{label}.plist",
        Path("/Library/LaunchAgents") / f"{label}.plist",
        Path("/Library/LaunchDaemons") / f"{label}.plist",
    ]
    for candidate in plist_candidates:
        if candidate.exists():
            status["plist_exists"] = True
            status["plist_path"] = str(candidate)
            break

    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            status["error"] = result.stderr.strip() or "launchctl list failed"
            return status

        for line in result.stdout.splitlines():
            if label not in line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            # launchctl list format: PID  LastExitStatus  Label
            pid_part = parts[0]
            exit_part = parts[1]
            job_label = parts[-1]
            if job_label != label:
                continue

            status["loaded"] = True
            if pid_part != "-":
                try:
                    status["pid"] = int(pid_part)
                    status["running"] = True
                except ValueError:
                    status["pid"] = None
            if exit_part != "-":
                try:
                    status["last_exit_code"] = int(exit_part)
                except ValueError:
                    status["last_exit_code"] = None
            return status
    except Exception as e:
        status["error"] = str(e)
    return status


def run_trading_api_watchdog() -> Dict:
    """Kill stale :8421 listeners and kickstart trading API launchd service."""
    label = "com.symphony.trading-api"
    user_id = str(os.getuid())
    steps: List[Dict] = []

    # Kill any direct python process for trading_api.py.
    pkill_result = run_command(["pkill", "-f", "api/trading_api.py"], timeout=10)
    steps.append({"step": "pkill trading_api.py", "result": pkill_result})

    # Kill stale listener on port 8421 if present.
    listener_pid: Optional[int] = None
    lsof_cmd = ["/usr/sbin/lsof", "-t", "-iTCP:8421", "-sTCP:LISTEN"]
    lsof_result = run_command(lsof_cmd, timeout=10)
    if (not lsof_result.get("success")) and "No such file or directory" in str(lsof_result.get("error", "")):
        lsof_result = run_command(["lsof", "-t", "-iTCP:8421", "-sTCP:LISTEN"], timeout=10)
    if lsof_result.get("success") and lsof_result.get("output"):
        raw_pid = (lsof_result.get("output", "").splitlines() or [""])[0].strip()
        try:
            listener_pid = int(raw_pid)
            kill_result = run_command(["kill", "-9", str(listener_pid)], timeout=10)
            steps.append({
                "step": "kill stale port 8421 listener",
                "pid": listener_pid,
                "result": kill_result,
            })
        except ValueError:
            steps.append({
                "step": "kill stale port 8421 listener",
                "result": {"success": False, "error": f"Unexpected PID output: {raw_pid}"},
            })
    else:
        steps.append({"step": "check stale port 8421 listener", "result": lsof_result})

    # Restart launchd service for trading API.
    kickstart_result = run_command(
        ["launchctl", "kickstart", "-k", f"gui/{user_id}/{label}"],
        timeout=15,
    )
    steps.append({"step": "launchctl kickstart trading-api", "result": kickstart_result})

    # Verify health endpoint.
    health_result = run_command(
        [
            "python3",
            "-c",
            (
                "import time, urllib.request\n"
                "ok=False\n"
                "last=''\n"
                "for _ in range(8):\n"
                "    try:\n"
                "        urllib.request.urlopen('http://127.0.0.1:8421/health', timeout=2)\n"
                "        ok=True\n"
                "        break\n"
                "    except Exception as e:\n"
                "        last=str(e)\n"
                "        time.sleep(1)\n"
                "print('healthy' if ok else last)\n"
                "raise SystemExit(0 if ok else 1)\n"
            ),
        ],
        timeout=20,
    )
    steps.append({"step": "verify trading api health", "result": health_result})

    job = get_launchd_job_status(label)
    return {
        "success": bool(health_result.get("success")),
        "timestamp": datetime.now().isoformat(),
        "label": label,
        "job": job,
        "stale_listener_pid": listener_pid,
        "steps": steps,
    }


def get_service_status() -> List[Dict]:
    """Get status of all Symphony services."""
    services = []
    
    # Check common ports
    port_services = [
        (3000, "Voice Receptionist", "voice"),
        (5678, "Bob Orchestrator", "orchestrator"),
        (8080, "Mission Control", "dashboard"),
        (8091, "Symphony Markup", "markup"),
        (11434, "Ollama", "ollama"),
        (8420, "Mobile API", "api"),
    ]
    
    import socket
    for port, name, key in port_services:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        services.append({
            "name": name,
            "key": key,
            "port": port,
            "status": "running" if result == 0 else "stopped",
            "url": f"http://localhost:{port}" if result == 0 else None
        })
    
    # Check launchd jobs
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5
        )
        running_jobs = result.stdout if result.returncode == 0 else ""
        
        symphony_jobs = [
            "com.symphony.morning-checklist",
            "com.symphony.daily-digest",
            "com.symphony.subscription-audit",
            "com.symphony.watcher",
            "com.symphony.memory-guard",
        ]
        
        for job in symphony_jobs:
            is_running = job in running_jobs
            services.append({
                "name": job.replace("com.symphony.", "").replace("-", " ").title(),
                "key": job,
                "type": "scheduled",
                "status": "loaded" if is_running else "unloaded"
            })
    except:
        pass
    
    return services


def get_quick_stats() -> Dict:
    """Get quick stats for dashboard."""
    stats = {
        "timestamp": datetime.now().isoformat(),
        "bids": {"new": 0, "pending": 0},
        "proposals": {"draft": 0, "sent": 0, "accepted": 0},
        "invoices": {"pending": 0, "overdue": 0, "paid_this_month": 0},
        "cortex": {"articles": 0, "size_kb": 0},
        "subscriptions": {"monthly_total": 0, "count": 0}
    }
    
    # Count proposals
    proposals_dir = BASE_DIR / "knowledge" / "projects"
    if proposals_dir.exists():
        for proj in proposals_dir.iterdir():
            if proj.is_dir():
                pf = proj / "proposal.json"
                if pf.exists():
                    try:
                        data = json.loads(pf.read_text())
                        status = data.get("status", "draft")
                        if status == "draft":
                            stats["proposals"]["draft"] += 1
                        elif status == "sent":
                            stats["proposals"]["sent"] += 1
                        elif status == "accepted":
                            stats["proposals"]["accepted"] += 1
                    except:
                        pass
    
    # Count cortex articles
    cortex_dir = BASE_DIR / "knowledge" / "cortex"
    if cortex_dir.exists():
        total_size = 0
        for f in cortex_dir.rglob("*.json"):
            stats["cortex"]["articles"] += 1
            total_size += f.stat().st_size
        stats["cortex"]["size_kb"] = round(total_size / 1024, 1)
    
    # Subscriptions
    subs_file = BASE_DIR / "knowledge" / "subscriptions.json"
    if subs_file.exists():
        try:
            data = json.loads(subs_file.read_text())
            subs = data.get("subscriptions", [])
            stats["subscriptions"]["count"] = len(subs)
            monthly = 0
            for s in subs:
                cost = s.get("cost", 0)
                if s.get("billing_cycle") == "yearly":
                    cost = cost / 12
                monthly += cost
            stats["subscriptions"]["monthly_total"] = round(monthly, 2)
        except:
            pass
    
    return stats


if HAS_FASTAPI:
    # --- API Endpoints ---
    
    @app.get("/")
    async def root():
        """API root - health check."""
        return {
            "name": "Symphony AI Mobile API",
            "version": "1.0.0",
            "status": "running",
            "timestamp": datetime.now().isoformat()
        }
    
    @app.get("/health")
    async def health():
        """Detailed health check."""
        return {
            "status": "healthy",
            "services": get_service_status(),
            "timestamp": datetime.now().isoformat()
        }
    
    @app.get("/dashboard")
    async def dashboard():
        """Main dashboard data."""
        return {
            "stats": get_quick_stats(),
            "services": get_service_status(),
            "timestamp": datetime.now().isoformat()
        }
    
    @app.get("/stats")
    async def stats():
        """Quick stats only."""
        return get_quick_stats()
    
    @app.get("/services")
    async def services():
        """Service status list."""
        return {"services": get_service_status()}
    
    # --- Bids ---
    
    @app.get("/bids")
    async def get_bids():
        """Get BuildingConnected bids."""
        result = run_command([
            "python3", str(BASE_DIR / "orchestrator" / "core" / "bob_orchestrator.py"),
            "bid_check"
        ])
        return result
    
    @app.get("/bids/list")
    async def list_bids():
        """List all bid invitations."""
        result = run_command([
            "python3", str(BASE_DIR / "orchestrator" / "core" / "bob_orchestrator.py"),
            "bid_list"
        ])
        return result
    
    # --- Proposals ---
    
    @app.get("/proposals")
    async def get_proposals():
        """List all proposals."""
        proposals = []
        proposals_dir = BASE_DIR / "knowledge" / "projects"
        if proposals_dir.exists():
            for proj in proposals_dir.iterdir():
                if proj.is_dir():
                    pf = proj / "proposal.json"
                    if pf.exists():
                        try:
                            data = json.loads(pf.read_text())
                            proposals.append({
                                "id": proj.name,
                                "client": data.get("client_name", "Unknown"),
                                "status": data.get("status", "draft"),
                                "total": data.get("total", 0),
                                "created": data.get("created", "")
                            })
                        except:
                            pass
        return {"proposals": proposals}
    
    class QuoteRequest(BaseModel):
        client: str
        description: str
    
    @app.post("/proposals/create")
    async def create_proposal(request: QuoteRequest):
        """Create a new proposal."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "smart_proposal.py"),
            "--client", request.client,
            "--description", request.description
        ], timeout=60)
        return result
    
    # --- Knowledge ---
    
    @app.get("/cortex/stats")
    async def cortex_stats():
        """Get cortex statistics."""
        result = run_command([
            "bash", str(BASE_DIR / "tools" / "cortex_status.sh")
        ])
        return result
    
    class ResearchRequest(BaseModel):
        query: str
    
    class FactsLearnRequest(BaseModel):
        text: str
        category: str = "general"
        learn_now: bool = False
        curate_now: bool = True

    class CuratorRunRequest(BaseModel):
        limit: int = 0
        force: bool = False
        contains: Optional[str] = None

    class CuratorFactStatusRequest(BaseModel):
        fact_ids: List[int]
        status: str
    
    @app.post("/facts/learn")
    async def facts_learn(request: FactsLearnRequest):
        """Ingest pasted facts (e.g. C4 driver info) into cortex for learning."""
        try:
            from tools.facts_ingest import ingest, CATEGORIES
            cat = request.category if request.category in CATEGORIES else "general"
            result = ingest(request.text.strip(), category=cat, learn_now=request.learn_now)

            # Keep curation loop tight: new facts should be scored immediately.
            if result.get("success") and request.curate_now:
                try:
                    from tools.cortex_curator import run_curator
                    curated = run_curator(limit=1, contains=result.get("path"), force=True)
                    result["curator"] = {
                        "indexed_files": curated.get("indexed_files", 0),
                        "new_facts": curated.get("new_facts", 0),
                        "updated_facts": curated.get("updated_facts", 0),
                    }
                except Exception as ce:
                    result["curator_warning"] = str(ce)

            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/facts/categories")
    async def facts_categories():
        """List available fact categories."""
        from tools.facts_ingest import CATEGORIES
        return {"categories": CATEGORIES}

    @app.post("/cortex/curator/run")
    async def run_cortex_curator(request: CuratorRunRequest):
        """Run Cortex Curator pipeline: dedupe, confidence scoring, contradiction checks."""
        try:
            from tools.cortex_curator import run_curator
            result = run_curator(
                limit=request.limit if request.limit > 0 else None,
                force=request.force,
                contains=request.contains,
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/cortex/curator/status")
    async def cortex_curator_status():
        """Get curator status, review queue, and trusted/review counts."""
        try:
            from tools.cortex_curator import get_curator_status
            return get_curator_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/cortex/curator/review")
    async def cortex_curator_review(
        status: str = "review",
        limit: int = 50,
        offset: int = 0,
        min_confidence: float = -1.0,
        min_professional: float = 0.25,
        subject: str = "",
    ):
        """List curation queue with smart-home reasoning/troubleshooting scores."""
        try:
            from tools.cortex_curator import list_review_facts
            status = status if status in {"review", "trusted"} else "review"
            return list_review_facts(
                status=status,
                limit=max(1, min(limit, 200)),
                offset=max(0, offset),
                min_confidence=(None if min_confidence < 0 else float(min_confidence)),
                min_professional_score=(None if min_professional < 0 else float(min_professional)),
                subject_contains=(subject or None),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/cortex/curator/facts/status")
    async def cortex_curator_set_status(request: CuratorFactStatusRequest):
        """Manually set fact status to trusted/review by IDs."""
        try:
            from tools.cortex_curator import set_fact_status
            desired = request.status.strip().lower()
            return set_fact_status(request.fact_ids, desired)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/cortex/curator/promote")
    async def cortex_curator_promote(request: CuratorFactStatusRequest):
        """Promote selected facts to trusted."""
        try:
            from tools.cortex_curator import set_fact_status
            return set_fact_status(request.fact_ids, "trusted")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/cortex/curator/demote")
    async def cortex_curator_demote(request: CuratorFactStatusRequest):
        """Demote selected facts to review."""
        try:
            from tools.cortex_curator import set_fact_status
            return set_fact_status(request.fact_ids, "review")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/memory_guard/status")
    async def memory_guard_status():
        """Get launchd status for smart memory guard."""
        try:
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "job": get_launchd_job_status("com.symphony.memory-guard"),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/trading/fix_api")
    async def trading_fix_api():
        """Run watchdog to clear stale :8421 listener and restart trading API."""
        try:
            status = run_trading_api_watchdog()
            return {
                "success": status.get("success", False),
                "output": json.dumps(status, indent=2),
                "error": None if status.get("success") else "Trading API watchdog failed",
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/research")
    async def research(request: ResearchRequest):
        """Search knowledge base."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "smart_research.py"),
            "--query", request.query
        ], timeout=60)
        return result
    
    # --- Website ---
    
    @app.get("/website/status")
    async def website_status():
        """Check website health."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "website_monitor.py"),
            "--json"
        ], timeout=60)
        return _extract_json_from_output(result, "website_status")
    
    # --- Subscriptions ---
    
    @app.get("/subscriptions")
    async def get_subscriptions():
        """Get all subscriptions."""
        subs_file = BASE_DIR / "knowledge" / "subscriptions.json"
        if subs_file.exists():
            return json.loads(subs_file.read_text())
        return {"subscriptions": []}
    
    # --- Morning Checklist ---
    
    @app.get("/morning")
    async def morning_checklist():
        """Run morning checklist."""
        result = run_command([
            "python3", str(BASE_DIR / "orchestrator" / "morning_checklist.py"),
            "--quick", "--dry"
        ], timeout=60)
        return result
    
    # --- Dealer Forms ---
    
    @app.get("/dealers")
    async def list_dealers():
        """List known dealer application forms."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "dealer_forms.py"),
            "--list"
        ])
        return result
    
    # --- Usage Monitor ---
    
    @app.get("/usage")
    async def get_usage():
        """Get usage across all metered services."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "usage_monitor.py"),
            "--json"
        ])
        if result.get("success") and result.get("output"):
            try:
                return json.loads(result["output"])
            except:
                pass
        return result
    
    @app.get("/usage/alerts")
    async def get_usage_alerts():
        """Get usage alerts only."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "usage_monitor.py"),
            "--json", "--alerts"
        ])
        if result.get("success") and result.get("output"):
            try:
                return json.loads(result["output"])
            except:
                pass
        return result
    
    class UsageUpdate(BaseModel):
        service: str
        auto_pct: Optional[float] = None
        api_pct: Optional[float] = None
        spent: Optional[float] = None
    
    @app.post("/usage/update")
    async def update_usage(request: UsageUpdate):
        """Update usage for a service manually."""
        if request.service == "cursor":
            cmd = [
                "python3", str(BASE_DIR / "tools" / "usage_monitor.py"),
                "--update-cursor", str(request.auto_pct or 0), str(request.api_pct or 0)
            ]
        elif request.service == "openai":
            cmd = [
                "python3", str(BASE_DIR / "tools" / "usage_monitor.py"),
                "--update-openai", str(request.spent or 0)
            ]
        else:
            return {"success": False, "error": "Unknown service"}
        return run_command(cmd)
    
    # --- AI Markup Tool ---
    
    class MarkupRequest(BaseModel):
        project_name: str
        description: str
        rooms: Optional[List[str]] = None

    @app.post("/dtools/products/import")
    async def dtools_products_import(
        file: UploadFile = File(...),
        create_in_dtools: bool = Form(False),
        max_products: int = Form(25),
        dealer_tier: str = Form("standard"),
        dry_run: bool = Form(True),
    ):
        """
        Upload a pricing/data sheet, parse products, and optionally create them in D-Tools Cloud.
        """
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            upload_name = file.filename or f"upload_{ts}.pdf"
            safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in upload_name)
            upload_path = DTOOLS_PRODUCT_AGENT_DIR / f"{ts}_{safe_name}"

            content = await file.read()
            upload_path.write_bytes(content)

            products = _parse_sheet_file(upload_path, dealer_tier=dealer_tier)
            if not products:
                return {
                    "success": False,
                    "error": "No products parsed from file.",
                    "file": str(upload_path),
                }

            limited = products[: max(1, min(max_products, 500))]
            results: List[Dict[str, Any]] = []
            created_count = 0

            if create_in_dtools and not dry_run:
                from agents.dtools_browser_agent import DToolsBrowserAgent

                agent = DToolsBrowserAgent(headless=True)
                if not await agent.start():
                    return {
                        "success": False,
                        "error": "Failed to start browser agent (Playwright not ready).",
                        "parsed_count": len(products),
                        "products": limited,
                    }
                try:
                    if not await agent.login():
                        return {
                            "success": False,
                            "error": "Failed to login to D-Tools Cloud. Check DTOOLS credentials.",
                            "parsed_count": len(products),
                            "products": limited,
                        }
                    for prod in limited:
                        out = await agent.create_product(prod)
                        results.append(out)
                        if out.get("success"):
                            created_count += 1
                finally:
                    await agent.stop()
            else:
                results = [{"success": True, "mode": "dry_run", "product": p} for p in limited]

            summary = {
                "success": True,
                "file": str(upload_path),
                "parsed_count": len(products),
                "attempted_count": len(limited),
                "created_count": created_count,
                "failed_count": max(0, len(limited) - created_count) if create_in_dtools and not dry_run else 0,
                "create_in_dtools": bool(create_in_dtools and not dry_run),
                "dealer_tier": dealer_tier,
                "results": results,
                "products": limited,
                "timestamp": datetime.now().isoformat(),
            }

            out_file = DTOOLS_PRODUCT_AGENT_DIR / f"product_import_{ts}.json"
            out_file.write_text(json.dumps(summary, indent=2))
            summary["output_file"] = str(out_file)
            return summary
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/markup/generate")
    async def generate_markup(request: MarkupRequest):
        """Generate AI-powered project markup/proposal."""
        result = run_command([
            "python3", str(BASE_DIR / "tools" / "smart_proposal.py"),
            "--client", request.project_name,
            "--description", request.description,
            "--ai-markup"
        ], timeout=120)
        return result
    
    @app.get("/markup/templates")
    async def get_markup_templates():
        """Get available markup templates."""
        templates = []
        template_dir = BASE_DIR / "knowledge" / "templates"
        if template_dir.exists():
            for f in template_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    templates.append({
                        "id": f.stem,
                        "name": data.get("name", f.stem),
                        "description": data.get("description", ""),
                        "rooms": data.get("rooms", [])
                    })
                except:
                    pass
        return {"templates": templates}
    
    @app.get("/markup/exports")
    async def get_markup_exports():
        """Get recent markup exports."""
        exports = []
        export_dir = BASE_DIR / "knowledge" / "markup_exports"
        if export_dir.exists():
            files = sorted(export_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]
            for f in files:
                try:
                    data = json.loads(f.read_text())
                    exports.append({
                        "id": f.stem,
                        "filename": f.name,
                        "project": data.get("project", f.stem),
                        "symbols_count": len(data.get("symbols", [])),
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                    })
                except:
                    pass
        return {"exports": exports}
    
    @app.get("/markup/url")
    async def get_markup_url():
        """Get URL for Symphony Markup app. Prefers HTTPS when MARKUP_HTTPS_URL is set."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = "localhost"
        https_url = os.environ.get("MARKUP_HTTPS_URL", "").strip()
        return {
            "url": https_url or f"http://{local_ip}:8091",
            "httpsUrl": https_url or None,
            "localhost": "http://localhost:8091",
            "status": "running" if is_port_open(8091) else "stopped"
        }


def is_port_open(port: int) -> bool:
    """Check if a port is open."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0


# ============================================================================
# Leads Endpoints
# ============================================================================

def run_lead_tool(args: list, timeout: int = 90) -> dict:
    """Run lead_finder or outreach tool."""
    try:
        result = subprocess.run(
            ["python3", str(BASE_DIR / "tools" / "lead_finder.py")] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout or result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Scan timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_outreach_tool(args: list, timeout: int = 60) -> dict:
    """Run outreach automation tool."""
    try:
        result = subprocess.run(
            ["python3", str(BASE_DIR / "tools" / "outreach_automation.py")] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout or result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Operation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if HAS_FASTAPI:
    @app.get("/leads/builders")
    async def scan_builders():
        """Scan for custom home builders."""
        return run_lead_tool(["--builders"])
    
    @app.get("/leads/realtors")
    async def scan_realtors():
        """Scan for luxury realtors."""
        return run_lead_tool(["--realtors"])
    
    @app.get("/leads/listings")
    async def scan_listings():
        """Scan for luxury listings."""
        return run_lead_tool(["--listings"])
    
    @app.get("/leads/property")
    async def scan_property_managers():
        """Scan for property management companies."""
        return run_lead_tool(["--property-managers"])
    
    @app.get("/leads/recent")
    async def get_recent_leads():
        """Get recently scanned leads."""
        return run_lead_tool(["--recent"])
    
    @app.get("/leads/outreach/queue")
    async def get_outreach_queue():
        """Get current outreach queue."""
        return run_outreach_tool(["--queue"])
    
    @app.get("/leads/outreach/generate")
    async def generate_outreach():
        """Generate outreach drafts from leads."""
        return run_outreach_tool(["--run"])
    
    # ========================================================================
    # AI Chat Endpoints
    # ========================================================================
    
    @app.get("/ai/status")
    async def ai_status():
        """Which AI backends are available (cortex, ollama, lm_studio, openai, perplexity)."""
        try:
            import sys
            sys.path.insert(0, str(BASE_DIR / "tools"))
            from ai_router import get_backend_status
            return get_backend_status()
        except Exception as e:
            return {"error": str(e)}

    @app.get("/ai/verify/ollama")
    async def ai_verify_ollama():
        """Verify Ollama (Betty) is reachable. Returns ok + message."""
        try:
            import sys
            sys.path.insert(0, str(BASE_DIR / "tools"))
            from ai_router import verify_backend, OLLAMA_URL
            ok, msg = verify_backend(OLLAMA_URL, "/api/tags", "Ollama (Betty)")
            return {"ok": ok, "message": msg}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @app.get("/ai/verify/lm_studio")
    async def ai_verify_lm_studio():
        """Verify LM Studio is reachable. Returns ok + message."""
        try:
            import sys
            sys.path.insert(0, str(BASE_DIR / "tools"))
            from ai_router import verify_backend, LM_STUDIO_URL
            ok, msg = verify_backend(LM_STUDIO_URL, "/v1/models", "LM Studio")
            return {"ok": ok, "message": msg}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    class ChatRequest(BaseModel):
        question: str
        source: Optional[str] = "auto"

    @app.post("/ai/chat")
    async def ai_chat(body: ChatRequest):
        """
        Smart AI routing. Optional "source" to force: auto, cortex, ollama, lm_studio,
        gpt-4o-mini, perplexity.
        """
        try:
            question = body.question or ""
            source = body.source or "auto"

            if not question:
                return {"success": False, "error": "No question provided"}
            
            import sys
            sys.path.insert(0, str(BASE_DIR / "tools"))
            from ai_router import ask, classify_question
            
            complexity = classify_question(question)
            answer, used_source, cost = ask(question, source=source)
            
            return {
                "success": True,
                "output": answer,
                "source": used_source,
                "complexity": complexity,
                "cost_usd": cost
            }
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e), "trace": traceback.format_exc()}
    
    @app.get("/ai/costs")
    async def get_ai_costs():
        """Get AI usage cost summary."""
        try:
            import sys
            sys.path.insert(0, str(BASE_DIR / "tools"))
            from ai_router import get_cost_summary
            return get_cost_summary()
        except Exception as e:
            return {"error": str(e)}
    
    @app.post("/ai/log")
    async def log_ai_query(request: Request):
        """Log AI queries for knowledge building."""
        try:
            body = await request.json()
            question = body.get("question", "")
            source = body.get("source", "unknown")
            
            log_file = BASE_DIR / "data" / "ai_query_log.jsonl"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            import json
            with open(log_file, "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "question": question,
                    "source": source
                }) + "\n")
            
            return {"success": True, "logged": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────
    # Claude Approval (Bridge: Task Board → Email → iOS Approve → Bob)
    # ─────────────────────────────────────────────────────────────
    
    class AddTaskRequest(BaseModel):
        title: str
        description: Optional[str] = ""
        task_type: Optional[str] = "research"
        priority: Optional[str] = "medium"
    
    @app.post("/tasks")
    async def add_task(request: AddTaskRequest):
        """Add a task to the board. Use task_type='claude' for approval workflow."""
        try:
            sys.path.insert(0, str(BASE_DIR))
            from orchestrator.task_board import add_task as tb_add_task
            task_id = tb_add_task(
                title=request.title,
                description=request.description or "",
                task_type=request.task_type or "research",
                priority=request.priority or "medium",
            )
            return {"success": True, "task_id": task_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @app.get("/tasks/claude_pending")
    async def get_claude_pending():
        """Get Claude tasks awaiting approval (type=claude, status=pending)."""
        try:
            sys.path.insert(0, str(BASE_DIR))
            from orchestrator.task_board import get_claude_pending_tasks
            tasks = get_claude_pending_tasks()
            return {
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "description": t.description or "",
                        "priority": t.priority,
                        "created_at": t.created_at,
                    }
                    for t in tasks
                ]
            }
        except Exception as e:
            return {"tasks": [], "error": str(e)}
    
    @app.post("/tasks/{task_id}/approve_claude")
    async def approve_claude(task_id: int):
        """Approve a Claude task: Bob sends command to Claude Code via terminal."""
        try:
            sys.path.insert(0, str(BASE_DIR))
            from orchestrator.task_board import approve_claude_task
            success, message = approve_claude_task(task_id)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @app.get("/claude/workflows")
    async def get_claude_workflows():
        """Get Claude Code workflow prompts for copy/paste."""
        try:
            path = BASE_DIR / "setup" / "claude_code" / "workflow_prompts.json"
            if not path.exists():
                return {"workflows": []}
            data = json.loads(path.read_text())
            return {"workflows": data}
        except Exception as e:
            return {"workflows": [], "error": str(e)}

    # ─────────────────────────────────────────────────────────────
    # Social / X (Twitter) — same as Telegram SEO menu
    # ─────────────────────────────────────────────────────────────
    
    @app.get("/social/story")
    async def social_story():
        """Generate project story tweet and queue it."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "social_content.py"), "--story", "--queue"],
            timeout=45
        )
    
    @app.get("/social/tip")
    async def social_tip():
        """Generate daily tip tweet and queue it."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "social_content.py"), "--tip", "--queue"],
            timeout=45
        )
    
    @app.get("/social/video")
    async def social_video():
        """Generate video prompt + tweet and queue it."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "social_content.py"), "--video-prompt", "--queue"],
            timeout=45
        )
    
    @app.get("/social/week")
    async def social_week():
        """Generate full week of content (takes ~60 sec)."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "social_content.py"), "--series", "--queue"],
            timeout=120
        )
    
    @app.get("/social/x-queue")
    async def social_x_queue():
        """Show X post queue."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "x_poster.py"), "--queue"],
            timeout=15
        )
    
    @app.get("/social/x-post")
    async def social_x_post():
        """Post next tweet from queue to @symphonysmart."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "x_poster.py"), "--auto"],
            timeout=30
        )
    
    @app.get("/social/x-usage")
    async def social_x_usage():
        """Show X API usage this month."""
        return run_command(
            ["python3", str(BASE_DIR / "tools" / "x_poster.py"), "--usage"],
            timeout=15
        )
    
    # ─────────────────────────────────────────────────────────────
    # SEO Endpoints
    # ─────────────────────────────────────────────────────────────
    
    @app.get("/seo/keywords")
    async def seo_keywords():
        """Research SEO keywords for Vail Valley."""
        return run_tool_endpoint("seo_manager.py", ["--keywords"])
    
    @app.get("/seo/content")
    async def seo_content_ideas():
        """Get content/blog ideas."""
        return run_tool_endpoint("seo_manager.py", ["--content"])
    
    @app.get("/seo/local")
    async def seo_local_audit():
        """Run local SEO audit."""
        return run_tool_endpoint("seo_manager.py", ["--local"])
    
    @app.get("/seo/backlinks")
    async def seo_backlinks():
        """Find backlink opportunities."""
        return run_tool_endpoint("seo_manager.py", ["--backlinks"])
    
    @app.get("/seo/meta")
    async def seo_meta_tags():
        """Generate optimized meta tags."""
        return run_tool_endpoint("seo_manager.py", ["--meta"])
    
    @app.post("/seo/generate")
    async def seo_generate_post():
        """Generate a new blog post draft."""
        result = subprocess.run(
            ["python3", str(BASE_DIR / "orchestrator" / "seo_content_generator.py"), "--generate"],
            capture_output=True, text=True, timeout=120
        )
        return {"success": result.returncode == 0, "output": result.stdout or result.stderr}
    
    @app.get("/seo/drafts")
    async def seo_list_drafts():
        """List all SEO content drafts."""
        drafts_dir = BASE_DIR / "knowledge" / "seo" / "drafts"
        if not drafts_dir.exists():
            return {"success": True, "drafts": []}
        
        drafts = []
        for f in sorted(drafts_dir.glob("*.json"), reverse=True)[:10]:
            try:
                import json
                data = json.loads(f.read_text())
                drafts.append({
                    "file": f.name,
                    "title": data.get("title"),
                    "keyword": data.get("keyword"),
                    "status": data.get("status", "draft"),
                    "generated": data.get("generated")
                })
            except:
                pass
        
        return {"success": True, "drafts": drafts}


def main():
    if not HAS_FASTAPI:
        print("Install FastAPI: pip install fastapi uvicorn")
        return
    
    print(f"""
╔══════════════════════════════════════════════════╗
║     Symphony AI Mobile API                       ║
║     http://localhost:{API_PORT}                         ║
╠══════════════════════════════════════════════════╣
║  Endpoints:                                      ║
║    GET  /              - Health check            ║
║    GET  /dashboard     - Main dashboard          ║
║    GET  /services      - Service status          ║
║    GET  /bids          - Check bids              ║
║    GET  /proposals     - List proposals          ║
║    POST /research      - Search knowledge        ║
║    POST /cortex/curator/run - Curate cortex      ║
║    GET  /cortex/curator/status - Curator stats   ║
║    GET  /cortex/curator/review - Review queue    ║
║    GET  /website/status - Website health         ║
║    GET  /subscriptions - List subscriptions      ║
║    GET  /morning       - Morning checklist       ║
╚══════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)


if __name__ == "__main__":
    main()
