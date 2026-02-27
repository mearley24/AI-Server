#!/usr/bin/env python3
"""
task_selector.py
================
Intelligent task selection strategy for Bob's ClawWork side hustle.

Ranks GDPVal tasks by expected ROI based on:
  - Sector tier assignment (Bob's domain expertise)
  - Historical performance per sector (adaptive weights)
  - Task value vs estimated difficulty ratio
  - Randomization factor for sector discovery
"""

import json
import logging
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz

log = logging.getLogger("clawwork.selector")
MST = pytz.timezone("America/Denver")

GDPVAL_SECTORS = {
    "Professional, Scientific, and Technical Services": {
        "Software Developers": {"bls_hourly": 64.26, "tier": 1},
        "Computer and Information Systems Managers": {"bls_hourly": 83.85, "tier": 1},
        "Project Management Specialists": {"bls_hourly": 49.14, "tier": 1},
        "Accountants and Auditors": {"bls_hourly": 40.13, "tier": 1},
        "Lawyers": {"bls_hourly": 73.60, "tier": 1},
    },
    "Information": {
        "Audio and Video Technicians": {"bls_hourly": 29.34, "tier": 1},
        "Producers and Directors": {"bls_hourly": 50.13, "tier": 1},
        "News Analysts, Reporters, and Journalists": {"bls_hourly": 31.65, "tier": 2},
        "Film and Video Editors": {"bls_hourly": 38.74, "tier": 2},
        "Editors": {"bls_hourly": 36.43, "tier": 2},
    },
    "Real Estate and Rental and Leasing": {
        "Property and Real Estate Managers": {"bls_hourly": 35.65, "tier": 1},
        "Real Estate Sales Agents": {"bls_hourly": 30.99, "tier": 1},
        "Real Estate Brokers": {"bls_hourly": 37.65, "tier": 1},
        "Counter and Rental Clerks": {"bls_hourly": 16.52, "tier": 2},
        "Concierges": {"bls_hourly": 17.94, "tier": 2},
    },
    "Finance and Insurance": {
        "Financial Managers": {"bls_hourly": 75.79, "tier": 1},
        "Financial and Investment Analysts": {"bls_hourly": 49.65, "tier": 1},
        "Personal Financial Advisors": {"bls_hourly": 51.61, "tier": 1},
        "Securities Sales Agents": {"bls_hourly": 45.36, "tier": 2},
        "Customer Service Representatives": {"bls_hourly": 20.51, "tier": 2},
    },
    "Manufacturing": {
        "Industrial Engineers": {"bls_hourly": 50.51, "tier": 2},
        "Mechanical Engineers": {"bls_hourly": 49.37, "tier": 2},
        "Buyers and Purchasing Agents": {"bls_hourly": 37.92, "tier": 2},
        "First-Line Supervisors of Production Workers": {"bls_hourly": 34.41, "tier": 2},
    },
    "Health Care and Social Assistance": {
        "Medical and Health Services Managers": {"bls_hourly": 59.87, "tier": 2},
        "First-Line Supervisors of Office and Administrative Support": {"bls_hourly": 30.06, "tier": 2},
        "Registered Nurses": {"bls_hourly": 43.22, "tier": 3},
    },
    "Retail Trade": {
        "General and Operations Managers": {"bls_hourly": 53.58, "tier": 2},
        "First-Line Supervisors of Retail Sales Workers": {"bls_hourly": 22.09, "tier": 2},
    },
    "Government": {
        "Compliance Officers": {"bls_hourly": 39.44, "tier": 3},
        "Administrative Services Managers": {"bls_hourly": 48.23, "tier": 3},
    },
    "Wholesale Trade": {
        "Sales Managers": {"bls_hourly": 71.06, "tier": 3},
        "Sales Representatives (Technical)": {"bls_hourly": 49.30, "tier": 3},
        "Sales Representatives (Non-Technical)": {"bls_hourly": 32.04, "tier": 3},
    },
}

TIER_WEIGHTS = {1: 3.0, 2: 1.5, 3: 0.7}


@dataclass
class ClawWorkTask:
    task_id: str
    sector: str
    occupation: str
    bls_hourly: float
    estimated_hours: float
    estimated_value: float
    difficulty: float
    task_description: str = ""
    deliverable_type: str = "document"
    reference_files: list = field(default_factory=list)
    tier: int = 2

    @property
    def expected_payment(self):
        return 0.85 * self.estimated_value

    @property
    def roi_ratio(self):
        cost_proxy = self.estimated_hours * 0.50
        return self.expected_payment / cost_proxy if cost_proxy > 0 else self.expected_payment


class SectorPerformanceTracker:
    def __init__(self, history_path: Path):
        self.history_path = history_path
        self.data: dict = self._load()

    def _load(self):
        if self.history_path.exists():
            try:
                return json.loads(self.history_path.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(self.data, indent=2))

    def record(self, sector, quality_score, payment, cost):
        if sector not in self.data:
            self.data[sector] = {"tasks": 0, "total_quality": 0.0, "total_payment": 0.0,
                                  "total_cost": 0.0, "avg_quality": 0.0, "avg_net_profit": 0.0}
        d = self.data[sector]
        d["tasks"] += 1
        d["total_quality"] += quality_score
        d["total_payment"] += payment
        d["total_cost"] += cost
        d["avg_quality"] = d["total_quality"] / d["tasks"]
        d["avg_net_profit"] = (d["total_payment"] - d["total_cost"]) / d["tasks"]
        self._save()

    def get_multiplier(self, sector, min_samples=5):
        if sector not in self.data or self.data[sector]["tasks"] < min_samples:
            return 1.0
        quality = self.data[sector]["avg_quality"]
        if quality <= 0.50:
            return 0.3
        elif quality <= 0.75:
            return 0.3 + (quality - 0.50) / 0.25 * 0.7
        else:
            return 1.0 + (quality - 0.75) / 0.25 * 1.5

    def should_exclude(self, sector, threshold=0.50):
        if sector not in self.data or self.data[sector]["tasks"] < 5:
            return False
        return self.data[sector]["avg_quality"] < threshold


class GDPValTaskLoader:
    def __init__(self, dataset_path: Path):
        self.dataset_path = dataset_path

    def load_available_tasks(self, min_value=100.0):
        tasks = []
        if self.dataset_path.exists():
            for path in self.dataset_path.glob("**/*.json"):
                try:
                    data = json.loads(path.read_text())
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        task = self._parse_task(item)
                        if task and task.estimated_value >= min_value:
                            tasks.append(task)
                except Exception:
                    pass
        if not tasks:
            tasks = self._synthesize_tasks(min_value)
        return tasks

    def _parse_task(self, data):
        try:
            sector = data.get("sector", "Unknown")
            occupation = data.get("occupation", "Unknown")
            bls_info = GDPVAL_SECTORS.get(sector, {}).get(occupation, {})
            bls_hourly = bls_info.get("bls_hourly", 30.0)
            tier = bls_info.get("tier", 2)
            est_hours = float(data.get("estimated_hours", 1.0))
            return ClawWorkTask(
                task_id=data.get("task_id", f"task_{random.randint(10000,99999)}"),
                sector=sector, occupation=occupation, bls_hourly=bls_hourly,
                estimated_hours=est_hours, estimated_value=est_hours * bls_hourly,
                difficulty=float(data.get("difficulty", 0.5)),
                task_description=data.get("task", data.get("description", "")),
                deliverable_type=data.get("deliverable_type", "document"),
                reference_files=data.get("reference_files", []), tier=tier,
            )
        except Exception:
            return None

    def _synthesize_tasks(self, min_value):
        tasks = []
        counter = 1
        templates = {
            "Software Developers": [("design a RESTful API for smart home device management", 2.0, 0.6)],
            "Computer and Information Systems Managers": [("create a technology roadmap for an AV/IT company", 4.0, 0.7)],
            "Project Management Specialists": [("create a project plan for commercial AV installation", 2.0, 0.5)],
            "Financial Managers": [("create a 3-year financial forecast for a tech services company", 4.0, 0.7)],
            "Property and Real Estate Managers": [("develop a smart building technology ROI analysis", 3.0, 0.65)],
        }
        for sector, occupations in GDPVAL_SECTORS.items():
            for occupation, info in occupations.items():
                bls_hourly = info["bls_hourly"]
                tier = info["tier"]
                tmpl_list = templates.get(occupation, [(f"complete a professional task for {occupation}", 2.0, 0.55)])
                for desc, est_hours, difficulty in tmpl_list:
                    est_value = est_hours * bls_hourly
                    if est_value < min_value:
                        continue
                    tasks.append(ClawWorkTask(
                        task_id=f"gdpval_{re.sub(r'[^a-z0-9]', '_', occupation.lower())}_{counter:04d}",
                        sector=sector, occupation=occupation, bls_hourly=bls_hourly,
                        estimated_hours=est_hours, estimated_value=est_value,
                        difficulty=difficulty, task_description=desc,
                        deliverable_type="document", tier=tier,
                    ))
                    counter += 1
        return tasks


class TaskSelector:
    def __init__(self, config: dict):
        self.config = config
        dataset_path = Path(config["gdpval"]["dataset_path"]).expanduser()
        self.loader = GDPValTaskLoader(dataset_path)
        history_path = Path.home() / ".symphony" / "data" / "sector_performance.json"
        self.history = SectorPerformanceTracker(history_path)
        self.session_completed: set = set()
        self._task_cache = None
        self._cache_time = None
        self._cache_ttl = 3600

    def _get_tasks(self):
        import time
        if self._task_cache is None or time.time() - (self._cache_time or 0) > self._cache_ttl:
            min_val = self.config["task_selection"]["exclusions"]["min_task_value"]
            self._task_cache = self.loader.load_available_tasks(min_value=min_val)
            self._cache_time = time.time()
        return self._task_cache

    def _score_task(self, task):
        tier_weight = TIER_WEIGHTS.get(task.tier, 0.7)
        perf_mult = self.history.get_multiplier(task.sector)
        value_factor = math.log1p(task.estimated_value) / math.log1p(1000)
        difficulty_discount = 1.0 - (task.difficulty * 0.2)
        score = tier_weight * perf_mult * value_factor * difficulty_discount
        for sc in self.config["task_selection"]["preferred_sectors"]:
            if sc["id"] in task.sector.lower():
                score *= sc["base_weight"] * 10
                break
        return score

    async def select_task(self, force=False):
        tasks = self._get_tasks()
        if not tasks:
            return None
        randomization = self.config["task_selection"]["sector_priorities"]["randomization_factor"]
        exclusion_threshold = self.config["task_selection"]["adaptive_learning"]["auto_exclude_threshold"]
        candidates = [
            t for t in tasks
            if (force or t.task_id not in self.session_completed)
            and t.sector not in self.config["task_selection"]["exclusions"]["sectors"]
            and (force or not self.history.should_exclude(t.sector, threshold=exclusion_threshold))
        ]
        if not candidates:
            self.session_completed.clear()
            candidates = tasks
        scored = [(t, self._score_task(t) * (1 + random.uniform(-randomization, randomization)))
                  for t in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        if random.random() < randomization and len(scored) >= 10:
            selected = random.choice(scored[:10])[0]
        else:
            selected = scored[0][0]
        self.session_completed.add(selected.task_id)
        log.info(f"Selected: {selected.task_id} ({selected.sector}, ${selected.estimated_value:.2f})")
        return selected

    def record_performance(self, sector, quality_score, payment, cost):
        self.history.record(sector, quality_score, payment, cost)

    def get_sector_rankings(self):
        rankings = []
        for sector, occupations in GDPVAL_SECTORS.items():
            tier = min(info["tier"] for info in occupations.values())
            rankings.append({
                "sector": sector, "tier": tier,
                "performance_multiplier": self.history.get_multiplier(sector),
                "excluded": self.history.should_exclude(sector),
                "history": self.history.data.get(sector, {}),
            })
        rankings.sort(key=lambda r: TIER_WEIGHTS.get(r["tier"], 0.7) * r["performance_multiplier"], reverse=True)
        return rankings
