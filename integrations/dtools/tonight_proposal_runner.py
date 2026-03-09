#!/usr/bin/env python3
"""
Batch-import Symphony proposals into D-Tools with retries.
Primary intent: dependable tonight flow while API cutover finalizes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path.home() / "AI-Server"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "integrations" / "dtools"))

from proposal_workflow import import_proposal_api_first, prepare_proposal_for_dtools_import
from agents.dtools_browser_agent import DToolsBrowserAgent


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


async def _run_one_browser(agent: DToolsBrowserAgent, proposal_id: str) -> dict[str, Any]:
    prep = prepare_proposal_for_dtools_import(proposal_id)
    if not prep.get("ok"):
        return {"proposal_id": proposal_id, "ok": False, "mode": "prepare", "error": prep.get("error")}
    result = await agent.full_workflow(
        project_name=prep["project_name"],
        client_name=prep["client_name"],
        address=prep.get("address", ""),
        csv_path=prep["csv_path"],
    )
    return {
        "proposal_id": proposal_id,
        "ok": bool(result.get("success", False)),
        "mode": "browser",
        "project_name": prep["project_name"],
        "client_name": prep["client_name"],
        "item_count": prep.get("item_count", 0),
        "result": result,
    }


async def _run_batch(proposal_ids: list[str], retries: int, visible: bool, api_first: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "proposal_ids": proposal_ids,
        "retries": retries,
        "api_first": api_first,
        "results": [],
    }
    agent = DToolsBrowserAgent(headless=not visible)
    if not await agent.start():
        return {"ok": False, "error": "Browser start failed", **out}
    try:
        for pid in proposal_ids:
            best: dict[str, Any] = {"proposal_id": pid, "ok": False, "error": "not attempted"}
            if api_first:
                api_result = import_proposal_api_first(pid)
                if api_result.get("ok"):
                    out["results"].append(
                        {"proposal_id": pid, "ok": True, "mode": "api_first", "result": api_result}
                    )
                    continue
                best = {
                    "proposal_id": pid,
                    "ok": False,
                    "mode": "api_first_failed",
                    "error": api_result.get("error", "api-first failed"),
                    "details": api_result,
                }

            for attempt in range(1, retries + 2):
                run = await _run_one_browser(agent, pid)
                run["attempt"] = attempt
                if run.get("ok"):
                    best = run
                    break
                best = run
            out["results"].append(best)
    finally:
        await agent.stop()

    ok_count = sum(1 for r in out["results"] if r.get("ok"))
    out["ok"] = ok_count == len(out["results"])
    out["success_count"] = ok_count
    out["failed_count"] = len(out["results"]) - ok_count
    out["finished_at"] = datetime.now().isoformat()
    return out


def _write_report(report: dict[str, Any]) -> Path:
    reports_dir = BASE_DIR / "data" / "dtools" / "tonight_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"proposal_batch_{_stamp()}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def _summary(report: dict[str, Any]) -> str:
    lines = [
        "D-Tools Tonight Runner",
        f"success: {report.get('success_count', 0)}",
        f"failed: {report.get('failed_count', 0)}",
    ]
    for r in report.get("results", []):
        status = "OK" if r.get("ok") else "FAIL"
        lines.append(f"- [{status}] {r.get('proposal_id')} ({r.get('mode', 'browser')})")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch import proposals into D-Tools")
    parser.add_argument("proposal_ids", nargs="+", help="Proposal IDs, e.g. P-20260306-ABCD")
    parser.add_argument("--retries", type=int, default=1, help="Retries per proposal after first attempt")
    parser.add_argument("--visible", action="store_true", help="Run browser visibly")
    parser.add_argument("--api-first", action="store_true", help="Try API-first before browser fallback")
    args = parser.parse_args()

    report = asyncio.run(
        _run_batch(
            proposal_ids=[p.strip() for p in args.proposal_ids if p.strip()],
            retries=max(0, args.retries),
            visible=bool(args.visible),
            api_first=bool(args.api_first),
        )
    )
    report_path = _write_report(report)
    print(_summary(report))
    print(f"report: {report_path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
