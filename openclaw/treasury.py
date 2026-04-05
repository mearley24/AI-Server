"""Profit reinvestment loop: trading <-> reserve <-> business context."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("openclaw.treasury")

REDIS_URL = os.getenv("REDIS_URL", "redis://:d1fff1065992d132b000c01d6012fa52@redis:6379")
NOTIFY_ALERTS_CHANNEL = "notifications:alerts"
NOTIFY_TRADING_CHANNEL = "notifications:trading"

MONTHLY_EXPENSES = {
    "perplexity_pro": 200.00,
    "dtools": 99.00,
    "openai_target": 50.00,
    "mullvad_vpn": 5.00,
    "twilio": 20.00,
    "hosting_misc": 15.00,
}
MONTHLY_BURN_RATE = round(sum(MONTHLY_EXPENSES.values()), 2)
OPERATING_RESERVE_MINIMUM = 500.00
OPERATING_RESERVE_TARGET = round(MONTHLY_BURN_RATE * 2, 2)

REDIS_KEYS = {
    "balances": "treasury:balances",
    "monthly": "treasury:monthly:{YYYY-MM}",
    "expenses": "treasury:expenses",
    "revenue": "treasury:revenue:{YYYY-MM}",
    "bankroll_log": "treasury:bankroll:history",
    "alerts": "treasury:alerts",
    "scaling_log": "treasury:bankroll:scaling_log",
}


@dataclass
class TreasuryState:
    timestamp: float
    trading_usdc_balance: float
    trading_position_value: float
    trading_total: float
    operating_reserve: float
    monthly_burn_rate: float
    months_runway: float
    business_receivable: float
    business_deposited_mtd: float
    business_pipeline_value: float
    net_worth: float
    monthly_pnl: float


@dataclass
class ScalingDecision:
    action: str
    new_max_position_pct: float
    reason: str
    weekly_pnl: float
    trailing_pnl: float


class DToolsRevenueSource:
    """Stub for D-Tools revenue data. Manual values via Redis for now."""

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    async def get_mtd_revenue(self) -> float:
        raw = await self.redis.get("treasury:manual:revenue_mtd")
        return float(raw or 0.0)

    async def get_receivables(self) -> float:
        raw = await self.redis.get("treasury:manual:receivables")
        return float(raw or 0.0)

    async def get_pipeline_value(self) -> float:
        raw = await self.redis.get("treasury:manual:pipeline_value")
        if raw is None:
            raw = await self.redis.get("treasury:manual:receivables")
        return float(raw or 0.0)

    async def set_manual_revenue(self, amount: float) -> None:
        await self.redis.set("treasury:manual:revenue_mtd", float(amount))

    async def set_manual_receivables(self, amount: float) -> None:
        await self.redis.set("treasury:manual:receivables", float(amount))


class BankrollScaler:
    """Auto-scales max position pct based on trailing weekly performance."""

    SCALE_UP_THRESHOLD = 3
    SCALE_DOWN_THRESHOLD = 2
    SCALE_UP_PCT = 0.10
    SCALE_DOWN_PCT = 0.20
    REINVEST_PCT = float(os.getenv("TREASURY_REINVEST_PCT", "0.50"))

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    @staticmethod
    def _consecutive_tail(history: list[float], positive: bool) -> int:
        count = 0
        for x in reversed(history):
            if positive and x > 0:
                count += 1
            elif not positive and x < 0:
                count += 1
            else:
                break
        return count

    async def evaluate_weekly(self, weekly_pnl_history: list[float]) -> ScalingDecision:
        current = float(await self.redis.get("treasury:max_position_pct") or 0.10)
        if not weekly_pnl_history:
            return ScalingDecision("hold", current, "No weekly history", 0.0, 0.0)

        pos = self._consecutive_tail(weekly_pnl_history, positive=True)
        neg = self._consecutive_tail(weekly_pnl_history, positive=False)
        this_week = float(weekly_pnl_history[-1])
        trailing = float(sum(weekly_pnl_history[-3:]))

        if pos >= self.SCALE_UP_THRESHOLD:
            new_pct = min(0.25, current * (1 + self.SCALE_UP_PCT))
            return ScalingDecision(
                "scale_up",
                round(new_pct, 4),
                f"{pos} consecutive profitable weeks",
                this_week,
                trailing,
            )

        if neg >= self.SCALE_DOWN_THRESHOLD:
            new_pct = max(0.02, current * (1 - self.SCALE_DOWN_PCT))
            return ScalingDecision(
                "scale_down",
                round(new_pct, 4),
                f"{neg} consecutive losing weeks",
                this_week,
                trailing,
            )

        return ScalingDecision("hold", current, "No threshold hit", this_week, trailing)


class TreasuryManager:
    """Central financial tracking module."""

    def __init__(self, redis_url: str = REDIS_URL):
        self.redis = aioredis.from_url(redis_url, decode_responses=True)
        self.revenue = DToolsRevenueSource(self.redis)
        self.scaler = BankrollScaler(self.redis)
        self._last_alert_signatures: set[str] = set()
        self._last_weekly_key: str = ""

    @staticmethod
    def _month_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    async def close(self) -> None:
        try:
            await self.redis.aclose()
        except Exception:
            pass

    async def _get_monthly_hash(self, month: str | None = None) -> dict[str, float]:
        m = month or self._month_key()
        key = REDIS_KEYS["monthly"].replace("{YYYY-MM}", m)
        data = await self.redis.hgetall(key)
        defaults = {
            "trading_profit": 0.0,
            "trading_loss": 0.0,
            "trading_net": 0.0,
            "business_revenue": 0.0,
            "operating_expenses": MONTHLY_BURN_RATE,
            "net_profit": 0.0,
            "reinvested_to_bankroll": 0.0,
            "added_to_reserve": 0.0,
        }
        out = dict(defaults)
        for k, v in (data or {}).items():
            try:
                out[k] = float(v)
            except Exception:
                continue
        return self._recompute_monthly_totals(out)

    @staticmethod
    def _recompute_monthly_totals(values: dict[str, float]) -> dict[str, float]:
        values["operating_expenses"] = float(values.get("operating_expenses", MONTHLY_BURN_RATE))
        values["trading_net"] = float(values.get("trading_profit", 0.0)) - float(values.get("trading_loss", 0.0))
        values["net_profit"] = (
            float(values["trading_net"])
            + float(values.get("business_revenue", 0.0))
            - float(values["operating_expenses"])
        )
        return values

    async def _store_monthly_hash(self, values: dict[str, float], month: str | None = None) -> None:
        m = month or self._month_key()
        key = REDIS_KEYS["monthly"].replace("{YYYY-MM}", m)
        totals = self._recompute_monthly_totals(dict(values))
        mapping = {k: str(round(float(v), 4)) for k, v in totals.items()}
        await self.redis.hset(key, mapping=mapping)

    async def _get_trading_balances(self) -> tuple[float, float]:
        snapshot_json = await self.redis.get("portfolio:snapshot")
        if not snapshot_json:
            return 0.0, 0.0
        try:
            snap = json.loads(snapshot_json)
            usdc = float(snap.get("usdc_balance", 0.0) or 0.0)
            pos = float(snap.get("total_position_value", 0.0) or 0.0)
            return usdc, pos
        except Exception:
            return 0.0, 0.0

    async def _get_operating_reserve(self) -> float:
        raw = await self.redis.get("treasury:manual:operating_reserve")
        if raw is None:
            return 0.0
        return float(raw or 0.0)

    async def set_operating_reserve(self, amount: float) -> None:
        await self.redis.set("treasury:manual:operating_reserve", float(amount))

    async def allocate_profit(self, trading_profit: float) -> dict[str, float]:
        if trading_profit <= 0:
            return {"reinvest": 0.0, "to_reserve": 0.0}
        reinvest_pct = BankrollScaler.REINVEST_PCT
        reinvest = trading_profit * reinvest_pct
        to_reserve = trading_profit * (1 - reinvest_pct)
        current_reserve = await self._get_operating_reserve()
        if current_reserve >= OPERATING_RESERVE_TARGET:
            reinvest = trading_profit
            to_reserve = 0.0

        await self.set_operating_reserve(current_reserve + to_reserve)
        monthly = await self._get_monthly_hash()
        monthly["reinvested_to_bankroll"] = float(monthly.get("reinvested_to_bankroll", 0.0)) + reinvest
        monthly["added_to_reserve"] = float(monthly.get("added_to_reserve", 0.0)) + to_reserve
        await self._store_monthly_hash(monthly)
        logger.info(
            "treasury_profit_allocation",
            trading_profit=round(trading_profit, 2),
            reinvest=round(reinvest, 2),
            to_reserve=round(to_reserve, 2),
            reserve_after=round(current_reserve + to_reserve, 2),
        )
        return {"reinvest": round(reinvest, 2), "to_reserve": round(to_reserve, 2)}

    async def record_trading_pnl(self, pnl_delta: float) -> None:
        monthly = await self._get_monthly_hash()
        if pnl_delta >= 0:
            monthly["trading_profit"] = float(monthly.get("trading_profit", 0.0)) + pnl_delta
            await self._store_monthly_hash(monthly)
            await self.allocate_profit(pnl_delta)
            return
        else:
            monthly["trading_loss"] = float(monthly.get("trading_loss", 0.0)) + abs(pnl_delta)
        await self._store_monthly_hash(monthly)

    async def record_weekly_pnl(self, pnl_delta: float) -> None:
        """Append this week's realized P/L for bankroll scaling logic."""
        await self.redis.lpush("treasury:weekly_pnl", str(float(pnl_delta)))
        await self.redis.ltrim("treasury:weekly_pnl", 0, 51)

    async def update_state(self) -> TreasuryState:
        usdc, pos = await self._get_trading_balances()
        trading_total = usdc + pos
        reserve = await self._get_operating_reserve()
        receivable = await self.revenue.get_receivables()
        deposited = await self.revenue.get_mtd_revenue()
        pipeline = await self.revenue.get_pipeline_value()
        monthly = await self._get_monthly_hash()
        monthly["business_revenue"] = deposited
        await self._store_monthly_hash(monthly)
        monthly_pnl = float(monthly.get("net_profit", 0.0))
        runway = (reserve / MONTHLY_BURN_RATE) if MONTHLY_BURN_RATE > 0 else 0.0
        state = TreasuryState(
            timestamp=time.time(),
            trading_usdc_balance=round(usdc, 2),
            trading_position_value=round(pos, 2),
            trading_total=round(trading_total, 2),
            operating_reserve=round(reserve, 2),
            monthly_burn_rate=MONTHLY_BURN_RATE,
            months_runway=round(runway, 2),
            business_receivable=round(receivable, 2),
            business_deposited_mtd=round(deposited, 2),
            business_pipeline_value=round(pipeline, 2),
            net_worth=round(trading_total + reserve, 2),
            monthly_pnl=round(monthly_pnl, 2),
        )
        payload = json.dumps(asdict(state))
        await self.redis.set(REDIS_KEYS["balances"], payload)
        await self.redis.lpush(REDIS_KEYS["bankroll_log"], payload)
        await self.redis.ltrim(REDIS_KEYS["bankroll_log"], 0, 999)
        logger.info("[context-engine] treasury state updated trading_total=%.2f reserve=%.2f", state.trading_total, state.operating_reserve)
        return state

    async def get_current_state(self) -> TreasuryState:
        raw = await self.redis.get(REDIS_KEYS["balances"])
        if raw:
            try:
                data = json.loads(raw)
                return TreasuryState(**data)
            except Exception:
                pass
        return await self.update_state()

    async def get_period_summary(self, days: int = 30) -> dict[str, float]:
        state = await self.get_current_state()
        monthly = await self._get_monthly_hash()
        factor = days / 30.0
        return {
            "days": float(days),
            "estimated_trading_net": round(float(monthly.get("trading_net", 0.0)) * factor, 2),
            "estimated_business_revenue": round(float(monthly.get("business_revenue", 0.0)) * factor, 2),
            "estimated_expenses": round(MONTHLY_BURN_RATE * factor, 2),
            "estimated_net": round(state.monthly_pnl * factor, 2),
        }

    async def _publish_alert(self, message: str, severity: str, state: TreasuryState, rule_name: str) -> None:
        payload = {
            "title": "Treasury Alert",
            "body": message,
            "severity": severity,
            "rule": rule_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.publish(NOTIFY_ALERTS_CHANNEL, json.dumps(payload))
        await self.redis.lpush(REDIS_KEYS["alerts"], json.dumps(payload))
        await self.redis.ltrim(REDIS_KEYS["alerts"], 0, 199)
        if severity == "high":
            await self.redis.publish(NOTIFY_TRADING_CHANNEL, json.dumps({"title": "⚠️ Treasury", "body": message}))

    async def evaluate_alerts(self, state: TreasuryState | None = None) -> list[dict[str, str]]:
        s = state or await self.get_current_state()
        rules = [
            {
                "name": "low_reserve",
                "condition": s.operating_reserve < OPERATING_RESERVE_MINIMUM,
                "message": f"⚠️ Operating reserve below $500. Current: ${s.operating_reserve:.2f}. Monthly burn: ${s.monthly_burn_rate:.2f}/month.",
                "severity": "high",
            },
            {
                "name": "low_runway",
                "condition": s.months_runway < 2.0,
                "message": "⚠️ Less than 2 months operating runway. Reduce expenses or add to reserve.",
                "severity": "high",
            },
            {
                "name": "strong_flywheel",
                "condition": s.monthly_pnl > MONTHLY_BURN_RATE,
                "message": "🚀 Flywheel active: monthly profit exceeds burn rate. Bot is self-sustaining.",
                "severity": "info",
            },
            {
                "name": "bankroll_growth",
                "condition": s.trading_total > 2000.0,
                "message": "📈 Trading portfolio crossed $2,000. Consider increasing position limits.",
                "severity": "info",
            },
        ]
        fired: list[dict[str, str]] = []
        for rule in rules:
            if not rule["condition"]:
                continue
            sig = f"{rule['name']}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            if sig in self._last_alert_signatures:
                continue
            self._last_alert_signatures.add(sig)
            await self._publish_alert(rule["message"], rule["severity"], s, rule["name"])
            fired.append({"name": rule["name"], "severity": rule["severity"], "message": rule["message"]})
        return fired

    async def evaluate_bankroll_scaling(self) -> ScalingDecision:
        raw = await self.redis.lrange("treasury:weekly_pnl", 0, 7)
        history: list[float] = []
        for item in reversed(raw or []):
            try:
                history.append(float(item))
            except Exception:
                continue
        decision = await self.scaler.evaluate_weekly(history)
        if decision.action in {"scale_up", "scale_down"}:
            await self.redis.set("treasury:max_position_pct", decision.new_max_position_pct)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": decision.action,
                "new_max_position_pct": decision.new_max_position_pct,
                "reason": decision.reason,
                "weekly_pnl": decision.weekly_pnl,
                "trailing_pnl": decision.trailing_pnl,
            }
            await self.redis.lpush(REDIS_KEYS["scaling_log"], json.dumps(entry))
            await self.redis.ltrim(REDIS_KEYS["scaling_log"], 0, 199)
            arrow = "📈" if decision.action == "scale_up" else "📉"
            body = (
                f"{arrow} Bankroll scaled {'UP' if decision.action == 'scale_up' else 'DOWN'}: {decision.reason}\n"
                f"New max position size: {decision.new_max_position_pct * 100:.1f}%\n"
                f"This week's P/L: ${decision.weekly_pnl:+.2f} | 3-week P/L: ${decision.trailing_pnl:+.2f}"
            )
            await self.redis.publish(NOTIFY_TRADING_CHANNEL, json.dumps({"title": "Treasury Scaling", "body": body}))
        return decision

    async def maybe_publish_weekly_report(self) -> str | None:
        now = datetime.now(timezone.utc)
        if now.weekday() != 6 or now.hour != 8:
            return None
        key = now.strftime("%Y-%m-%d")
        if self._last_weekly_key == key:
            return None
        self._last_weekly_key = key
        s = await self.get_current_state()
        monthly = await self._get_monthly_hash()
        weekly_exp = MONTHLY_BURN_RATE / 4.0
        weekly_pnl = float(await self.redis.lindex("treasury:weekly_pnl", 0) or 0.0)
        run_rate = s.monthly_pnl * 12.0
        on_track = "✅" if run_rate >= 24000.0 else "❌"
        report = (
            f"📊 Weekly Financial Report — Week of {now.strftime('%b %d, %Y')}\n\n"
            f"Trading:\n"
            f"  This week: ${weekly_pnl:+.2f}\n"
            f"  MTD: ${float(monthly.get('trading_net', 0.0)):+.2f}\n"
            f"  Bankroll: ${s.trading_total:.2f} total (${s.trading_usdc_balance:.2f} liquid)\n\n"
            f"Business (Symphony):\n"
            f"  Revenue this month: ${s.business_deposited_mtd:.2f}\n"
            f"  Receivables: ${s.business_receivable:.2f}\n"
            f"  Pipeline: ${s.business_pipeline_value:.2f}\n\n"
            f"Operations:\n"
            f"  Weekly expenses: ~${weekly_exp:.2f}\n"
            f"  Net this week: ${weekly_pnl:+.2f} - ${weekly_exp:.2f} = ${(weekly_pnl - weekly_exp):+.2f}\n\n"
            f"Monthly Goal: $2,000 | Run Rate: ${run_rate:.0f}/year | On Track: {on_track}\n"
        )
        await self.redis.publish(NOTIFY_TRADING_CHANNEL, json.dumps({"title": "Weekly Financial Report", "body": report}))
        return report
