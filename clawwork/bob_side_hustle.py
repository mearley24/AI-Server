#!/usr/bin/env python3
"""
bob_side_hustle.py
==================
Main orchestration script for Bob the Conductor's ClawWork integration.

Bob's primary job is running Symphony Smart Homes operations. When idle
(no Symphony tasks queued, off-hours), this script activates ClawWork
tasks to earn money and cover Bob's API costs.

Usage:
    python bob_side_hustle.py --daemon          # Run as background daemon
    python bob_side_hustle.py --once            # Run one task cycle
    python bob_side_hustle.py --test            # Run a test task
    python bob_side_hustle.py --status          # Print current status
    python bob_side_hustle.py --report          # Print earnings report
    python bob_side_hustle.py --pause           # Pause ClawWork activity
    python bob_side_hustle.py --resume          # Resume ClawWork activity

Logs to: ~/.symphony/logs/clawwork.log
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# ── Local imports ──────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from earnings_tracker import EarningsTracker
from task_selector import TaskSelector, ClawWorkTask

# ── Constants ────────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "clawwork_config.json"
LOG_DIR = Path.home() / ".symphony" / "logs"
LOG_FILE = LOG_DIR / "clawwork.log"
DATA_DIR = Path.home() / ".symphony" / "data"
STATE_FILE = DATA_DIR / "clawwork_state.json"
CLAWWORK_DIR = Path.home() / ".symphony" / "clawwork"
MST = pytz.timezone("America/Denver")

# ── Logging setup ────────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
CLAWWORK_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("clawwork.main")


class ClawWorkState:
    """Persisted runtime state for the ClawWork daemon."""

    def __init__(self):
        self.paused: bool = False
        self.tasks_today: int = 0
        self.last_task_time: Optional[float] = None
        self.daily_spend: float = 0.0
        self.daily_earnings: float = 0.0
        self.current_balance: float = 10.00
        self.date_reset: str = datetime.now(MST).strftime("%Y-%m-%d")
        self._load()

    def _load(self):
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                today = datetime.now(MST).strftime("%Y-%m-%d")
                if data.get("date_reset") != today:
                    data["tasks_today"] = 0
                    data["daily_spend"] = 0.0
                    data["daily_earnings"] = 0.0
                    data["date_reset"] = today
                self.__dict__.update(data)
            except Exception as e:
                log.warning(f"Could not load state file: {e}")

    def save(self):
        STATE_FILE.write_text(json.dumps(self.__dict__, indent=2))

    def reset_daily(self):
        today = datetime.now(MST).strftime("%Y-%m-%d")
        if self.date_reset != today:
            self.tasks_today = 0
            self.daily_spend = 0.0
            self.daily_earnings = 0.0
            self.date_reset = today
            self.save()
            log.info(f"Daily counters reset for {today}")


class SymphonyQueueChecker:
    """Checks whether Bob has pending Symphony tasks in OpenClaw."""

    def __init__(self, config: dict):
        self.endpoint = config["schedule"]["symphony_queue_check"]["endpoint"]
        self.threshold = config["schedule"]["symphony_queue_check"]["empty_if_count_below"]
        self.enabled = config["schedule"]["symphony_queue_check"]["enabled"]

    async def is_idle(self) -> bool:
        if not self.enabled:
            return True
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self.endpoint)
                data = resp.json()
                queue_count = data.get("count", 0)
                is_empty = queue_count < self.threshold
                if not is_empty:
                    log.debug(f"Symphony queue has {queue_count} pending tasks — ClawWork paused")
                return is_empty
        except Exception as e:
            log.warning(f"Could not check Symphony queue ({e}) — assuming idle")
            return True


class ScheduleChecker:
    """Bob works 24/7. ClawWork runs whenever the Symphony queue is empty."""

    def __init__(self, config: dict):
        self.tz = pytz.timezone(config["schedule"]["timezone"])
        self.mode = config["schedule"].get("mode", "24/7")

    def is_clawwork_allowed(self) -> bool:
        return True

    def seconds_until_next_window(self) -> int:
        return 0

    def get_status(self) -> str:
        now = datetime.now(self.tz)
        return f"24/7 ACTIVE — {now.strftime('%A %I:%M %p %Z')}"


class SystemHealthChecker:
    def __init__(self, config: dict):
        self.health = config["system_health"]

    async def is_healthy(self) -> bool:
        try:
            endpoint = self.health["health_endpoint"]
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(endpoint)
                return resp.status_code == 200
        except Exception:
            return self._check_local_resources()

    def _check_local_resources(self) -> bool:
        try:
            import psutil
            cpu_free = 100 - psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            mem_free_mb = mem.available / (1024 * 1024)
            disk = psutil.disk_usage(Path.home())
            disk_free_gb = disk.free / (1024 ** 3)
            return (
                cpu_free >= self.health["min_cpu_free_percent"]
                and mem_free_mb >= self.health["min_memory_free_mb"]
                and disk_free_gb >= self.health["min_disk_free_gb"]
            )
        except ImportError:
            return True


class ClawWorkRunner:
    def __init__(self, config: dict, clawwork_dir: Path):
        self.config = config
        self.clawwork_dir = clawwork_dir
        self.deliverable_dir = Path(config["clawwork_tools"]["file_creation"]["output_dir"]).expanduser()
        self.deliverable_dir.mkdir(parents=True, exist_ok=True)

    async def execute_task(self, task: ClawWorkTask) -> dict:
        start_time = time.time()
        log.info(f"Starting ClawWork task: {task.task_id} ({task.sector})")
        try:
            cmd = [
                sys.executable,
                str(self.clawwork_dir / "main.py"),
                "--mode", "task",
                "--task-id", task.task_id,
                "--sector", task.sector,
                "--agent", "side-hustle",
                "--model", self.config["agent"]["base_model"],
                "--output-dir", str(self.deliverable_dir),
                "--max-tokens", str(50000),
                "--evaluator", self.config["economic"]["evaluation_model"]["model"],
                "--output-json",
            ]
            max_duration = self.config["schedule"]["max_task_duration_minutes"] * 60
            env = os.environ.copy()
            env.update({
                "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
                "OPENAI_API_KEY": os.environ.get("CLAWWORK_OPENAI_KEY", os.environ.get("OPENAI_API_KEY", "")),
                "E2B_API_KEY": os.environ.get("CLAWWORK_E2B_KEY", ""),
                "CLAWWORK_TASK_ID": task.task_id,
                "CLAWWORK_SECTOR": task.sector,
            })
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(self.clawwork_dir),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=max_duration)
            except asyncio.TimeoutError:
                proc.kill()
                raise TimeoutError(f"Task {task.task_id} exceeded {max_duration}s")

            output = stdout.decode().strip()
            lines = output.split("\n")
            result_json = None
            for line in reversed(lines):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        result_json = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            duration = int(time.time() - start_time)
            if result_json:
                return {
                    "task_id": task.task_id,
                    "sector": task.sector,
                    "quality_score": float(result_json.get("quality_score", 0)),
                    "gross_payment": float(result_json.get("payment", 0)),
                    "token_cost": float(result_json.get("token_cost", 0)),
                    "net_profit": float(result_json.get("payment", 0)) - float(result_json.get("token_cost", 0)),
                    "deliverable_path": result_json.get("deliverable_path"),
                    "duration_seconds": duration,
                    "success": True,
                    "error": None,
                }
            return {"task_id": task.task_id, "sector": task.sector, "quality_score": 0.0,
                    "gross_payment": 0.0, "token_cost": 0.0, "net_profit": 0.0,
                    "duration_seconds": duration, "success": False, "error": "No JSON output"}

        except Exception as e:
            duration = int(time.time() - start_time)
            log.error(f"Task {task.task_id} failed: {e}")
            return {"task_id": task.task_id, "sector": task.sector, "quality_score": 0.0,
                    "gross_payment": 0.0, "token_cost": 0.0, "net_profit": 0.0,
                    "duration_seconds": duration, "success": False, "error": str(e)}


class TelegramNotifier:
    def __init__(self):
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.bot_token and self.chat_id)

    async def send(self, message: str):
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"})
        except Exception as e:
            log.warning(f"Telegram notification failed: {e}")

    async def notify_task_complete(self, result: dict, daily_total: float):
        if result["gross_payment"] > 0:
            msg = (f"💰 *ClawWork Task Complete*\n"
                   f"Sector: {result['sector']}\nQuality: {result['quality_score']:.2f}/1.0\n"
                   f"Earned: ${result['gross_payment']:.2f}\nNet: ${result['net_profit']:.2f}\n"
                   f"Daily total: ${daily_total:.2f}")
            await self.send(msg)


class SideHustleOrchestrator:
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config = json.loads(config_path.read_text())
        self.state = ClawWorkState()
        self.earnings = EarningsTracker(self.config)
        self.selector = TaskSelector(self.config)
        self.queue_checker = SymphonyQueueChecker(self.config)
        self.schedule_checker = ScheduleChecker(self.config)
        self.health_checker = SystemHealthChecker(self.config)
        self.notifier = TelegramNotifier()
        self.clawwork_dir = Path.home() / ".symphony" / "clawwork" / "ClawWork"
        self.runner = ClawWorkRunner(self.config, self.clawwork_dir)
        log.info(f"SideHustleOrchestrator initialized | balance=${self.state.current_balance:.2f}")

    async def can_run_task(self) -> tuple[bool, str]:
        self.state.reset_daily()
        if self.state.paused:
            return False, "ClawWork is manually paused"
        if self.state.current_balance < self.config["economic"]["pause_threshold"]:
            return False, f"Balance ${self.state.current_balance:.2f} below pause threshold"
        if self.state.tasks_today >= self.config["schedule"]["daily_task_limit"]:
            return False, f"Daily task limit reached ({self.state.tasks_today})"
        if self.state.daily_spend >= self.config["economic"]["max_daily_spend"]:
            return False, f"Daily spend limit reached (${self.state.daily_spend:.2f})"
        is_idle = await self.queue_checker.is_idle()
        if not is_idle:
            return False, "Symphony task queue is not empty"
        if self.config["system_health"]["check_before_task"]:
            healthy = await self.health_checker.is_healthy()
            if not healthy:
                return False, "System health check failed"
        if self.state.last_task_time:
            elapsed = time.time() - self.state.last_task_time
            cooldown = self.config["schedule"]["cooldown_between_tasks_seconds"]
            if elapsed < cooldown:
                return False, f"Cooldown ({cooldown - elapsed:.0f}s remaining)"
        return True, "All checks passed"

    async def run_one_task(self) -> Optional[dict]:
        can_run, reason = await self.can_run_task()
        if not can_run:
            log.info(f"Skipping task cycle: {reason}")
            return None
        task = await self.selector.select_task()
        if task is None:
            log.warning("No suitable ClawWork task found")
            return None
        result = await self.runner.execute_task(task)
        self.state.tasks_today += 1
        self.state.last_task_time = time.time()
        self.state.daily_spend += result["token_cost"]
        self.state.daily_earnings += result["gross_payment"]
        self.state.current_balance += result["net_profit"]
        self.state.save()
        self.earnings.log_task(
            task_id=result["task_id"], sector=result["sector"],
            occupation=task.occupation, estimated_value=task.estimated_value,
            actual_payment=result["gross_payment"], quality_score=result["quality_score"],
            token_cost=result["token_cost"], net_profit=result["net_profit"],
            duration_seconds=result["duration_seconds"], deliverable_path=result.get("deliverable_path"),
        )
        self.selector.record_performance(sector=task.sector, quality_score=result["quality_score"],
                                         payment=result["gross_payment"], cost=result["token_cost"])
        await self.notifier.notify_task_complete(result, self.state.daily_earnings)
        return result

    async def run_daemon(self):
        log.info("Starting ClawWork daemon...")
        scheduler = AsyncIOScheduler(timezone=MST)
        poll_seconds = self.config["schedule"]["poll_interval_seconds"]
        scheduler.add_job(self.run_one_task, trigger=IntervalTrigger(seconds=poll_seconds),
                          id="clawwork_poll", name="ClawWork Task Poll", misfire_grace_time=60)
        scheduler.add_job(self._send_daily_report, trigger=CronTrigger(hour=6, minute=0, timezone=MST),
                          id="daily_report", name="Daily Earnings Report")
        scheduler.start()
        log.info(f"Daemon running. Poll interval: {poll_seconds}s | balance=${self.state.current_balance:.2f}")
        loop = asyncio.get_event_loop()

        def shutdown_handler():
            log.info("Shutdown signal received")
            scheduler.shutdown(wait=False)
            loop.stop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_handler)
        try:
            await asyncio.Event().wait()
        except (SystemExit, KeyboardInterrupt):
            scheduler.shutdown(wait=False)

    async def run_test(self):
        log.info("Running ClawWork test task...")
        task = await self.selector.select_task(force=True)
        if task is None:
            print("ERROR: No test task available.")
            return
        result = await self.runner.execute_task(task)
        print(f"Quality: {result['quality_score']:.3f}/1.0")
        print(f"Payment: ${result['gross_payment']:.2f}")
        print(f"Net:     ${result['net_profit']:.2f}")

    def print_status(self):
        self.state.reset_daily()
        print(f"Status: {'PAUSED' if self.state.paused else 'ACTIVE'}")
        print(f"Balance: ${self.state.current_balance:.2f}")
        print(f"Tasks today: {self.state.tasks_today}/{self.config['schedule']['daily_task_limit']}")
        print(f"Schedule: {self.schedule_checker.get_status()}")

    async def _send_daily_report(self):
        report = self.earnings.generate_telegram_daily()
        await self.notifier.send(report)

    def pause(self):
        self.state.paused = True
        self.state.save()
        print("ClawWork paused.")

    def resume(self):
        self.state.paused = False
        self.state.save()
        print("ClawWork resumed.")


def main():
    parser = argparse.ArgumentParser(description="Bob the Conductor's ClawWork Side Hustle")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    orchestrator = SideHustleOrchestrator()
    if args.status:
        orchestrator.print_status()
    elif args.pause:
        orchestrator.pause()
    elif args.resume:
        orchestrator.resume()
    elif args.report:
        print(json.dumps(orchestrator.earnings.get_weekly_report(), indent=2))
    elif args.test:
        asyncio.run(orchestrator.run_test())
    elif args.once:
        result = asyncio.run(orchestrator.run_one_task())
        if result:
            print(f"Task complete: ${result['net_profit']:.2f} net profit")
        else:
            print("No task run this cycle")
    elif args.daemon:
        asyncio.run(orchestrator.run_daemon())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
