#!/usr/bin/env python3
"""
pricing_calculator.py — Symphony Smart Homes Pricing Engine

Calculates complete project pricing including equipment aggregation,
labor rates, markup tiers, tax computation, and payment schedule generation.
All equipment unit prices must come from D-Tools Cloud — never hardcoded.

Usage:
    from pricing_calculator import PricingCalculator
    calc = PricingCalculator()
    summary = calc.calculate(equipment_list, labor_phases, tax_rate=0.0875)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class MarkupTier(str, Enum):
    RESIDENTIAL_STANDARD = "residential_standard"   # Good/Better
    RESIDENTIAL_PREMIUM  = "residential_premium"    # Best tier
    COMMERCIAL_STANDARD  = "commercial_standard"    # Commercial projects
    MAINTENANCE          = "maintenance"            # Service agreements


class LaborCategory(str, Enum):
    INSTALLATION   = "installation"
    PROGRAMMING    = "programming"
    COMMISSIONING  = "commissioning"
    PROJECT_MGMT   = "project_management"
    TRAVEL         = "travel"


# Markup rates by tier (equipment markup over dealer cost)
# These are applied to D-Tools dealer cost to arrive at client price
MARKUP_RATES: dict[str, float] = {
    MarkupTier.RESIDENTIAL_STANDARD: 1.40,   # 40% margin
    MarkupTier.RESIDENTIAL_PREMIUM:  1.50,   # 50% margin
    MarkupTier.COMMERCIAL_STANDARD:  1.35,   # 35% margin
    MarkupTier.MAINTENANCE:          1.20,   # 20% margin
}

# Labor rates per hour by category
LABOR_RATES: dict[str, float] = {
    LaborCategory.INSTALLATION:  115.00,   # $/hr field tech
    LaborCategory.PROGRAMMING:   150.00,   # $/hr control programmer
    LaborCategory.COMMISSIONING: 135.00,   # $/hr commissioning tech
    LaborCategory.PROJECT_MGMT:   95.00,   # $/hr project manager
    LaborCategory.TRAVEL:         75.00,   # $/hr billable travel
}

# Tax-exempt categories (labor is typically not taxed)
TAX_EXEMPT_CATEGORIES = {"Labor"}

# Payment schedule templates (percentage of total)
PAYMENT_SCHEDULES: dict[str, list[dict]] = {
    "standard_3_payment": [
        {"milestone": "Contract Execution",                       "pct": 0.33},
        {"milestone": "Equipment Delivery / Pre-Wire Complete",   "pct": 0.33},
        {"milestone": "System Commissioning & Client Acceptance", "pct": 0.34},
    ],
    "commercial_4_payment": [
        {"milestone": "Contract Execution",             "pct": 0.25},
        {"milestone": "Mobilization / Rough-In Complete", "pct": 0.25},
        {"milestone": "Equipment Delivery",             "pct": 0.25},
        {"milestone": "Final Acceptance",               "pct": 0.25},
    ],
    "maintenance_annual": [
        {"milestone": "Annual Service Agreement — Full Year", "pct": 1.00},
    ],
    "maintenance_quarterly": [
        {"milestone": "Q1 Service Agreement",  "pct": 0.25},
        {"milestone": "Q2 Service Agreement",  "pct": 0.25},
        {"milestone": "Q3 Service Agreement",  "pct": 0.25},
        {"milestone": "Q4 Service Agreement",  "pct": 0.25},
    ],
}

# Budget range labels for client communication
BUDGET_RANGES = [
    (0,      25_000,  "Entry-Level"),
    (25_000, 75_000,  "Mid-Range"),
    (75_000, 150_000, "Premium"),
    (150_000, 300_000, "Luxury"),
    (300_000, float("inf"), "Ultra-Premium"),
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class EquipmentLineItem:
    model: str
    manufacturer: str
    category: str
    quantity: int
    room: str
    dealer_cost: Optional[float] = None      # from D-Tools Cloud (None = TBD)
    unit_price: Optional[float] = None       # after markup (None = TBD)
    extended_price: Optional[float] = None   # unit_price * quantity
    notes: str = ""
    price_source: str = "dtools"             # always "dtools" per rules


@dataclass
class LaborLineItem:
    description: str
    category: LaborCategory
    hours: float
    rate: Optional[float] = None             # defaults from LABOR_RATES
    total: Optional[float] = None            # hours * rate
    notes: str = ""


@dataclass
class PricingSummary:
    # Equipment
    equipment_line_items: list[EquipmentLineItem] = field(default_factory=list)
    equipment_subtotal: Optional[float] = None   # sum of extended prices
    equipment_tbd_count: int = 0                 # items with no D-Tools price

    # Labor
    labor_line_items: list[LaborLineItem] = field(default_factory=list)
    labor_subtotal: Optional[float] = None
    programming_subtotal: Optional[float] = None

    # Tax
    taxable_amount: Optional[float] = None
    tax_rate: float = 0.0
    tax_total: Optional[float] = None

    # Totals
    project_subtotal: Optional[float] = None
    project_total: Optional[float] = None
    total_is_estimate: bool = True           # True until all D-Tools prices populated

    # Markup
    markup_tier: str = MarkupTier.RESIDENTIAL_STANDARD
    markup_rate: float = MARKUP_RATES[MarkupTier.RESIDENTIAL_STANDARD]

    # Budget analysis
    budget_low: Optional[float] = None
    budget_high: Optional[float] = None
    budget_status: str = "unknown"           # "under", "within", "over", "unknown"
    budget_range_label: str = ""

    # Payment schedule
    payment_schedule: list[dict] = field(default_factory=list)

    # Metadata
    notes: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class BudgetAnalysis:
    project_total: Optional[float]
    budget_low: Optional[float]
    budget_high: Optional[float]
    status: str                              # "under", "within", "over", "unknown"
    variance: Optional[float]               # project_total - budget_midpoint
    variance_pct: Optional[float]           # variance / budget_midpoint
    range_label: str                         # "Luxury", "Premium", etc.
    recommendation: str                      # narrative for proposal


# ---------------------------------------------------------------------------
# Pricing Calculator
# ---------------------------------------------------------------------------

class PricingCalculator:
    """
    Symphony Smart Homes pricing engine.

    Rules:
    - Equipment prices ALWAYS come from D-Tools Cloud (never hardcoded)
    - Labor rates are fixed per Symphony rate card
    - Markup applied to dealer cost per tier
    - Tax applied to equipment only (labor typically not taxed)
    - Budget analysis compares total to client budget range
    """

    def __init__(
        self,
        markup_tier: MarkupTier = MarkupTier.RESIDENTIAL_STANDARD,
        tax_rate: float = 0.0,
        payment_schedule_key: str = "standard_3_payment",
    ):
        self.markup_tier = markup_tier
        self.markup_rate = MARKUP_RATES[markup_tier]
        self.tax_rate = tax_rate
        self.payment_schedule_key = payment_schedule_key
        logger.info(
            "PricingCalculator initialized: tier=%s, markup=%.2fx, tax=%.4f",
            markup_tier, self.markup_rate, tax_rate
        )

    def calculate(
        self,
        equipment: list[dict],
        labor_phases: list[dict],
        tax_rate: Optional[float] = None,
        budget_low: Optional[float] = None,
        budget_high: Optional[float] = None,
    ) -> PricingSummary:
        """
        Calculate complete project pricing.

        Args:
            equipment: List of equipment dicts (from ProposalEngine or D-Tools)
            labor_phases: List of labor phase dicts
            tax_rate: Override tax rate (uses instance default if None)
            budget_low: Client budget lower bound
            budget_high: Client budget upper bound

        Returns:
            PricingSummary with all line items and totals
        """
        effective_tax_rate = tax_rate if tax_rate is not None else self.tax_rate

        # Step 1: Process equipment
        equipment_items, equipment_subtotal, tbd_count, warnings = self._process_equipment(equipment)

        # Step 2: Process labor
        labor_items, labor_subtotal, programming_subtotal = self._process_labor(labor_phases)

        # Step 3: Compute tax (equipment only)
        taxable = equipment_subtotal if equipment_subtotal is not None else None
        tax_total = round(taxable * effective_tax_rate, 2) if taxable is not None else None

        # Step 4: Project totals
        project_subtotal = None
        project_total = None
        total_is_estimate = tbd_count > 0

        if equipment_subtotal is not None and labor_subtotal is not None:
            labor_all = (labor_subtotal or 0) + (programming_subtotal or 0)
            project_subtotal = round(equipment_subtotal + labor_all, 2)
            project_total = round(project_subtotal + (tax_total or 0), 2)

        # Step 5: Budget analysis
        budget_status = "unknown"
        budget_range_label = ""
        if project_total is not None:
            budget_status = self._compute_budget_status(project_total, budget_low, budget_high)
            budget_range_label = self._budget_range_label(project_total)

        # Step 6: Warnings
        if tbd_count > 0:
            warnings.append(
                f"{tbd_count} equipment item(s) have no D-Tools price yet. "
                "Totals marked as estimates until D-Tools import is complete."
            )
        if total_is_estimate:
            warnings.append("ESTIMATE ONLY — finalize equipment pricing in D-Tools Cloud before delivering proposal.")

        # Step 7: Payment schedule
        payment_schedule = self._build_payment_schedule(project_total)

        summary = PricingSummary(
            equipment_line_items=equipment_items,
            equipment_subtotal=equipment_subtotal,
            equipment_tbd_count=tbd_count,
            labor_line_items=labor_items,
            labor_subtotal=labor_subtotal,
            programming_subtotal=programming_subtotal,
            taxable_amount=taxable,
            tax_rate=effective_tax_rate,
            tax_total=tax_total,
            project_subtotal=project_subtotal,
            project_total=project_total,
            total_is_estimate=total_is_estimate,
            markup_tier=self.markup_tier,
            markup_rate=self.markup_rate,
            budget_low=budget_low,
            budget_high=budget_high,
            budget_status=budget_status,
            budget_range_label=budget_range_label,
            payment_schedule=payment_schedule,
            notes="Equipment pricing from D-Tools Cloud catalog. Labor per Symphony Smart Homes rate card.",
            warnings=warnings,
        )

        logger.info(
            "Pricing calculated: equipment=%s, labor=%s, total=%s, tbd=%d items, estimate=%s",
            f"${equipment_subtotal:,.2f}" if equipment_subtotal else "TBD",
            f"${(labor_subtotal or 0) + (programming_subtotal or 0):,.2f}" if labor_subtotal else "TBD",
            f"${project_total:,.2f}" if project_total else "TBD",
            tbd_count,
            total_is_estimate,
        )
        return summary

    # ------------------------------------------------------------------
    # Private: Equipment Processing
    # ------------------------------------------------------------------

    def _process_equipment(
        self, equipment: list[dict]
    ) -> tuple[list[EquipmentLineItem], Optional[float], int, list[str]]:
        """
        Process equipment list, applying markup to dealer costs.

        Returns:
            (line_items, subtotal_or_None, tbd_count, warnings)
        """
        items: list[EquipmentLineItem] = []
        running_total: float = 0.0
        tbd_count: int = 0
        warnings: list[str] = []
        has_prices: bool = False

        for eq in equipment:
            category = eq.get("category", "")
            qty = int(eq.get("quantity", 1))
            dealer_cost = eq.get("dealer_cost") or eq.get("unit_price")  # accept either field
            price_source = eq.get("price_source", "dtools")

            # Apply markup to dealer cost
            if dealer_cost is not None and category not in TAX_EXEMPT_CATEGORIES:
                unit_price = round(float(dealer_cost) * self.markup_rate, 2)
                extended = round(unit_price * qty, 2)
                running_total += extended
                has_prices = True
            elif dealer_cost is not None and category in TAX_EXEMPT_CATEGORIES:
                # Labor — pass through at stated rate
                unit_price = float(dealer_cost)
                extended = round(unit_price * qty, 2)
                running_total += extended
                has_prices = True
            else:
                unit_price = None
                extended = None
                tbd_count += 1

            item = EquipmentLineItem(
                model=eq.get("model", ""),
                manufacturer=eq.get("manufacturer", ""),
                category=category,
                quantity=qty,
                room=eq.get("room", ""),
                dealer_cost=dealer_cost,
                unit_price=unit_price,
                extended_price=extended,
                notes=eq.get("notes", ""),
                price_source=price_source,
            )
            items.append(item)

        subtotal = round(running_total, 2) if has_prices else None
        return items, subtotal, tbd_count, warnings

    # ------------------------------------------------------------------
    # Private: Labor Processing
    # ------------------------------------------------------------------

    def _process_labor(
        self, labor_phases: list[dict]
    ) -> tuple[list[LaborLineItem], Optional[float], Optional[float]]:
        """
        Process labor phases into line items with costs.

        Returns:
            (labor_items, labor_subtotal, programming_subtotal)
        """
        items: list[LaborLineItem] = []
        labor_total: float = 0.0
        programming_total: float = 0.0
        has_hours: bool = False

        for phase in labor_phases:
            phase_name = phase.get("phase", "")
            description = phase.get("description", phase_name)
            hours = phase.get("labor_hours") or phase.get("hours") or 0.0

            if not hours:
                continue

            # Determine labor category
            phase_lower = phase_name.lower() + description.lower()
            if "program" in phase_lower:
                category = LaborCategory.PROGRAMMING
            elif "commission" in phase_lower:
                category = LaborCategory.COMMISSIONING
            elif "manage" in phase_lower or "pm" in phase_lower:
                category = LaborCategory.PROJECT_MGMT
            elif "travel" in phase_lower:
                category = LaborCategory.TRAVEL
            else:
                category = LaborCategory.INSTALLATION

            rate = LABOR_RATES[category]
            total = round(float(hours) * rate, 2)

            item = LaborLineItem(
                description=description,
                category=category,
                hours=float(hours),
                rate=rate,
                total=total,
                notes=phase.get("notes", ""),
            )
            items.append(item)
            has_hours = True

            if category == LaborCategory.PROGRAMMING:
                programming_total += total
            else:
                labor_total += total

        if not has_hours:
            return items, None, None

        return (
            items,
            round(labor_total, 2) if labor_total else None,
            round(programming_total, 2) if programming_total else None,
        )

    # ------------------------------------------------------------------
    # Private: Budget & Payment
    # ------------------------------------------------------------------

    def _compute_budget_status(
        self,
        project_total: float,
        budget_low: Optional[float],
        budget_high: Optional[float],
    ) -> str:
        """Determine if project is under, within, or over budget."""
        if budget_low is None and budget_high is None:
            return "unknown"
        low = budget_low or 0
        high = budget_high or float("inf")
        if project_total < low:
            return "under"
        if project_total > high:
            return "over"
        return "within"

    def _budget_range_label(self, total: float) -> str:
        """Get human-readable budget range label for the project total."""
        for low, high, label in BUDGET_RANGES:
            if low <= total < high:
                return label
        return "Ultra-Premium"

    def _build_payment_schedule(
        self, project_total: Optional[float]
    ) -> list[dict]:
        """Build payment schedule with dollar amounts."""
        template = PAYMENT_SCHEDULES.get(
            self.payment_schedule_key,
            PAYMENT_SCHEDULES["standard_3_payment"]
        )

        schedule = []
        for payment in template:
            amount = round(project_total * payment["pct"], 2) if project_total else None
            schedule.append({
                "milestone": payment["milestone"],
                "percentage": round(payment["pct"] * 100),
                "amount": amount,
                "amount_display": f"${amount:,.2f}" if amount else "TBD",
            })

        return schedule

    # ------------------------------------------------------------------
    # Public: Analysis & Formatting
    # ------------------------------------------------------------------

    def analyze_budget(
        self,
        summary: PricingSummary,
        budget_low: Optional[float] = None,
        budget_high: Optional[float] = None,
    ) -> BudgetAnalysis:
        """
        Produce a budget analysis narrative for the proposal.

        Args:
            summary: PricingSummary from calculate()
            budget_low: Client budget lower bound
            budget_high: Client budget upper bound

        Returns:
            BudgetAnalysis with status and recommendation text
        """
        total = summary.project_total
        low = budget_low or summary.budget_low
        high = budget_high or summary.budget_high

        status = self._compute_budget_status(total, low, high) if total else "unknown"
        range_label = self._budget_range_label(total) if total else ""

        # Variance
        variance = None
        variance_pct = None
        if total and low and high:
            midpoint = (low + high) / 2
            variance = round(total - midpoint, 2)
            variance_pct = round(variance / midpoint * 100, 1) if midpoint else None

        # Recommendation
        if status == "within":
            rec = (
                "The proposed system is within the client's stated budget range. "
                "Equipment pricing will be confirmed in D-Tools Cloud; "
                "final totals may shift slightly pending catalog pricing."
            )
        elif status == "over" and variance_pct:
            rec = (
                f"The proposed system is approximately {abs(variance_pct):.1f}% above the stated budget range. "
                "Consider: (1) reducing room count, (2) adjusting tier from Best to Better in secondary rooms, "
                "or (3) deferring optional upgrades to Phase 2."
            )
        elif status == "under" and variance_pct:
            rec = (
                f"The proposed system comes in approximately {abs(variance_pct):.1f}% below the stated budget. "
                "This may be an opportunity to present optional upgrades that deliver additional value "
                "within the client's stated range."
            )
        else:
            rec = (
                "Final pricing to be confirmed once D-Tools Cloud import is complete. "
                "Budget comparison will be updated at that time."
            )

        return BudgetAnalysis(
            project_total=total,
            budget_low=low,
            budget_high=high,
            status=status,
            variance=variance,
            variance_pct=variance_pct,
            range_label=range_label,
            recommendation=rec,
        )

    def format_summary_text(
        self,
        summary: PricingSummary,
        include_line_items: bool = False,
    ) -> str:
        """
        Format a human-readable pricing summary for proposal output.

        Args:
            summary: PricingSummary from calculate()
            include_line_items: Whether to include per-item detail

        Returns:
            Formatted text block
        """
        lines = []
        na = "TBD (pending D-Tools import)"

        def fmt(val: Optional[float]) -> str:
            return f"${val:>12,.2f}" if val is not None else f"{'TBD':>17}"

        lines.append("PRICING SUMMARY")
        lines.append("=" * 50)

        if include_line_items:
            lines.append("\nEquipment Line Items:")
            for item in summary.equipment_line_items:
                if item.category == "Labor":
                    continue
                price_str = fmt(item.extended_price) if item.extended_price else "          TBD"
                lines.append(f"  {item.room:<20} {item.model:<30} x{item.quantity:<3} {price_str}")

            lines.append("\nLabor Line Items:")
            for item in summary.labor_line_items:
                lines.append(f"  {item.description:<40} {item.hours:>5.1f}h  {fmt(item.total)}")

        lines.append("")
        lines.append(f"  Equipment Subtotal:          {fmt(summary.equipment_subtotal)}")
        if summary.equipment_tbd_count:
            lines.append(f"  * {summary.equipment_tbd_count} item(s) pending D-Tools pricing")
        lines.append(f"  Labor (Installation):        {fmt(summary.labor_subtotal)}")
        if summary.programming_subtotal:
            lines.append(f"  Labor (Programming):         {fmt(summary.programming_subtotal)}")
        if summary.tax_rate > 0:
            lines.append(f"  Tax ({summary.tax_rate*100:.2f}%):               {fmt(summary.tax_total)}")
        lines.append("-" * 50)
        lines.append(f"  PROJECT TOTAL:               {fmt(summary.project_total)}")
        if summary.total_is_estimate:
            lines.append("  *** ESTIMATE — pending D-Tools pricing ***")

        if summary.budget_low and summary.budget_high:
            lines.append("")
            lines.append(f"  Client Budget Range: ${summary.budget_low:,.0f} – ${summary.budget_high:,.0f}")
            lines.append(f"  Budget Status: {summary.budget_status.upper()}")

        if summary.payment_schedule:
            lines.append("\nPayment Schedule:")
            for p in summary.payment_schedule:
                lines.append(f"  {p['milestone']:<45} {p['percentage']:>3}%  {p['amount_display']:>15}")

        if summary.warnings:
            lines.append("\nWarnings:")
            for w in summary.warnings:
                lines.append(f"  ⚠️  {w}")

        return "\n".join(lines)

    def estimate_budget_from_scope(
        self,
        room_count: int,
        systems: list[str],
        tier: str = "better",
        sq_ft: int = 3000,
    ) -> dict:
        """
        Rough budget estimate from scope parameters — for pre-proposal conversations.
        Uses industry rule-of-thumb ranges, NOT D-Tools prices.

        Args:
            room_count: Total number of rooms
            systems: Systems in scope (e.g., ["audio_video", "networking"])
            tier: "good", "better", or "best"
            sq_ft: Total square footage

        Returns:
            Dict with low/high budget estimates and breakdown by category
        """
        # Base per-room costs by tier (rough industry benchmarks)
        PER_ROOM_BASE = {
            "good":   8_000,
            "better": 14_000,
            "best":   22_000,
        }
        SYSTEM_ADDERS = {
            "lighting_shades":       {"good": 3_000,  "better": 6_000,  "best": 12_000},
            "audio_video":           {"good": 2_000,  "better": 4_000,  "best": 8_000},
            "networking":            {"good": 4_000,  "better": 7_000,  "best": 12_000},
            "security_surveillance": {"good": 3_000,  "better": 5_000,  "best": 10_000},
            "control_automation":    {"good": 8_000,  "better": 15_000, "best": 25_000},
            "climate":               {"good": 1_500,  "better": 2_500,  "best": 4_000},
        }

        tier_key = tier.lower() if tier.lower() in ("good", "better", "best") else "better"
        base = PER_ROOM_BASE.get(tier_key, 14_000) * room_count

        system_total = sum(
            SYSTEM_ADDERS.get(s, {}).get(tier_key, 0)
            for s in systems
        )

        subtotal = base + system_total
        # Apply 15% buffer for unknowns
        low = round(subtotal * 0.90, -3)
        high = round(subtotal * 1.20, -3)

        return {
            "low": low,
            "high": high,
            "midpoint": round((low + high) / 2, -3),
            "range_label": self._budget_range_label((low + high) / 2),
            "basis": f"{room_count} rooms @ {tier_key} tier + system add-ons",
            "note": "Rule-of-thumb estimate only — not based on D-Tools pricing. Use for pre-proposal conversation only.",
            "breakdown": {
                "base_rooms": base,
                "systems": system_total,
                "subtotal": subtotal,
            }
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def get_calculator(
    markup_tier: str = "residential_standard",
    tax_rate: float = 0.0,
    payment_schedule: str = "standard_3_payment",
) -> PricingCalculator:
    """
    Create a PricingCalculator with standard configuration.

    Args:
        markup_tier: One of residential_standard, residential_premium, commercial_standard
        tax_rate: Equipment tax rate (e.g., 0.0875 for 8.75%)
        payment_schedule: Payment schedule key

    Returns:
        Configured PricingCalculator
    """
    tier = MarkupTier(markup_tier)
    return PricingCalculator(markup_tier=tier, tax_rate=tax_rate, payment_schedule_key=payment_schedule)


# ---------------------------------------------------------------------------
# CLI / Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    calc = PricingCalculator(
        markup_tier=MarkupTier.RESIDENTIAL_PREMIUM,
        tax_rate=0.0725,
        payment_schedule_key="standard_3_payment",
    )

    # Mock equipment — in real usage, prices come from D-Tools Cloud
    equipment = [
        {"model": "Araknis 310 Router",           "manufacturer": "Snap One",    "category": "Networking", "quantity": 1,  "room": "Mechanical Room", "dealer_cost": 850.00},
        {"model": "Araknis 310 24P Switch",        "manufacturer": "Snap One",    "category": "Networking", "quantity": 1,  "room": "Mechanical Room", "dealer_cost": 1200.00},
        {"model": "Araknis 810 WAP",               "manufacturer": "Snap One",    "category": "Networking", "quantity": 4,  "room": "Various",         "dealer_cost": 350.00},
        {"model": "CyberPower UPS 1500VA",         "manufacturer": "CyberPower",  "category": "Power",     "quantity": 1,  "room": "Mechanical Room", "dealer_cost": 280.00},
        {"model": "Control4 CORE 3",               "manufacturer": "Control4",    "category": "Control",   "quantity": 1,  "room": "Mechanical Room", "dealer_cost": 2200.00},
        {"model": "Control4 T4 7\" Touchscreen",   "manufacturer": "Control4",    "category": "Control",   "quantity": 5,  "room": "Various",         "dealer_cost": 850.00},
        {"model": "Lutron RadioRA 3 Processor",    "manufacturer": "Lutron",      "category": "Lighting",  "quantity": 1,  "room": "Mechanical Room", "dealer_cost": 1800.00},
        {"model": "Lutron RRD-6ND-WH Dimmer",      "manufacturer": "Lutron",      "category": "Lighting",  "quantity": 18, "room": "Various",         "dealer_cost": 95.00},
        {"model": "Polk 70-RT In-Ceiling Speaker", "manufacturer": "Polk Audio",  "category": "Audio",     "quantity": 12, "room": "Various",         "dealer_cost": 180.00},
        {"model": "Luma x20 4MP Dome Camera",      "manufacturer": "Luma",        "category": "Security",  "quantity": 6,  "room": "Exterior",         "dealer_cost": 220.00},
        {"model": "Luma NVR-16",                   "manufacturer": "Luma",        "category": "Security",  "quantity": 1,  "room": "Mechanical Room", "dealer_cost": 950.00},
        {"model": "Installation Labor",            "manufacturer": "Symphony",    "category": "Labor",     "quantity": 1,  "room": "All Rooms",       "dealer_cost": None},  # TBD
    ]

    labor_phases = [
        {"phase": "Installation",  "description": "Field installation all systems", "labor_hours": 80},
        {"phase": "Programming",   "description": "Control4 and Lutron programming",  "labor_hours": 24},
        {"phase": "Commissioning", "description": "System commissioning and walkthrough", "labor_hours": 8},
    ]

    summary = calc.calculate(
        equipment=equipment,
        labor_phases=labor_phases,
        tax_rate=0.0725,
        budget_low=80_000,
        budget_high=120_000,
    )

    print(calc.format_summary_text(summary, include_line_items=False))

    analysis = calc.analyze_budget(summary, 80_000, 120_000)
    print(f"\nBudget Analysis: {analysis.status.upper()} | {analysis.range_label}")
    print(f"Recommendation: {analysis.recommendation}")

    # Rough estimate for pre-proposal
    print("\nPre-proposal budget estimate:")
    budget = calc.estimate_budget_from_scope(
        room_count=8,
        tier="best",
        systems=["lighting_shades", "audio_video", "networking",
                 "security_surveillance", "control_automation"])
    for k, v in budget.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    _demo()
