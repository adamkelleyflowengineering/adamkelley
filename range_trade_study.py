#!/usr/bin/env python3
"""EV Range Trade Study — single-file Flow / GitHub analysis example.

A trade study asks: "If I change one top-level requirement, what does it cost
me everywhere else?" Here the requirement is the vehicle's **design range**.
Push the range up and you need a bigger battery, which adds mass, adds cost,
lengthens charge time, and slows acceleration. Each of those has a budget, and
the study reports whether the design still closes.

Everything is in this one file. The knob is `TARGET_RANGE_KM` at the top.

    TARGET_RANGE_KM = 250  -> all budgets met            -> PASS
    TARGET_RANGE_KM = 300  -> mass & cost budgets broken  -> FAIL

Running it prints a trade-study table, writes `trade_study_report.json`
(machine-readable, for an analysis agent), and exits non-zero if any budget is
exceeded so a CI check / PR gate can flag it. Pure standard library.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

# =============================================================================
# DESIGN INPUT — this is what you change in the PR
# =============================================================================

TARGET_RANGE_KM = 250.0          # Vehicle design range requirement (km)

# =============================================================================
# FIXED ASSUMPTIONS (the rest of the vehicle definition)
# =============================================================================

CONSUMPTION_WH_PER_KM = 160.0        # Energy use at reference conditions (Wh/km)
PACK_ENERGY_DENSITY_WH_PER_KG = 160.0  # Pack-level gravimetric energy density
BATTERY_COST_PER_KWH = 130.0         # Cell + pack cost ($/kWh)
GLIDER_MASS_KG = 1500.0              # Vehicle mass WITHOUT the battery (kg)
CHARGER_POWER_KW = 150.0             # DC fast-charge power (kW)
CHARGE_WINDOW_FRACTION = 0.70        # Fraction of pack added in a 10->80% charge
# Reference point used to scale 0-100 km/h time with vehicle mass. A heavier
# car accelerates slower for the same powertrain.
REFERENCE_MASS_KG = 1750.0
REFERENCE_0_100_S = 6.5

# ---- Budgets the design must stay within (the trade-study constraints) ------
MASS_BUDGET_KG = 1780.0          # Max curb mass
COST_BUDGET_USD = 6000.0         # Max battery cost
CHARGE_TIME_BUDGET_MIN = 20.0    # Max 10->80% fast-charge time
ACCEL_BUDGET_S = 7.0             # Max 0-100 km/h time


@dataclass
class Metric:
    """One computed line of the trade study, with its budget check."""

    name: str
    value: float
    unit: str
    budget: float
    within_budget: bool


@dataclass
class TradeStudyResult:
    target_range_km: float
    battery_capacity_kwh: float
    metrics: list
    verdict: str  # "PASS" if every metric is within budget, else "FAIL"


def evaluate() -> TradeStudyResult:
    """Compute the battery sizing and every downstream trade-off.

    Reasoning chain (this is the whole point of a trade study):
      1. Range x consumption sets the required usable battery capacity.
      2. Capacity drives battery MASS (via energy density) and COST (via $/kWh).
      3. Battery mass adds to the glider to give curb mass, which slows 0-100.
      4. Capacity and charger power set the fast-charge TIME.
    Each result is checked against its budget; the design closes only if all do.
    """
    # 1. Battery capacity needed to hit the range requirement.
    battery_capacity_kwh = TARGET_RANGE_KM * CONSUMPTION_WH_PER_KM / 1000.0

    # 2. Mass and cost follow directly from capacity.
    battery_mass_kg = battery_capacity_kwh * 1000.0 / PACK_ENERGY_DENSITY_WH_PER_KG
    battery_cost_usd = battery_capacity_kwh * BATTERY_COST_PER_KWH

    # 3. Curb mass and its effect on acceleration (linear scaling with mass).
    curb_mass_kg = GLIDER_MASS_KG + battery_mass_kg
    accel_0_100_s = REFERENCE_0_100_S * (curb_mass_kg / REFERENCE_MASS_KG)

    # 4. Fast-charge time for the 10->80% window at the rated charger power.
    charge_time_min = (CHARGE_WINDOW_FRACTION * battery_capacity_kwh) / CHARGER_POWER_KW * 60.0

    # Build each trade-study line with its budget verdict. "within budget" means
    # the metric does not exceed its ceiling (all four are max-limits here).
    metrics = [
        Metric("Curb mass", round(curb_mass_kg, 1), "kg", MASS_BUDGET_KG, curb_mass_kg <= MASS_BUDGET_KG),
        Metric("Battery cost", round(battery_cost_usd, 0), "USD", COST_BUDGET_USD, battery_cost_usd <= COST_BUDGET_USD),
        Metric("Fast-charge 10-80%", round(charge_time_min, 1), "min", CHARGE_TIME_BUDGET_MIN, charge_time_min <= CHARGE_TIME_BUDGET_MIN),
        Metric("0-100 km/h", round(accel_0_100_s, 2), "s", ACCEL_BUDGET_S, accel_0_100_s <= ACCEL_BUDGET_S),
    ]

    # The design closes only when every budget is satisfied.
    verdict = "PASS" if all(m.within_budget for m in metrics) else "FAIL"

    return TradeStudyResult(
        target_range_km=round(TARGET_RANGE_KM, 1),
        battery_capacity_kwh=round(battery_capacity_kwh, 2),
        metrics=[asdict(m) for m in metrics],
        verdict=verdict,
    )


def render_table(result: TradeStudyResult) -> str:
    """Human-readable trade-study table for logs and the CI console."""
    header = (
        f"EV Range Trade Study  —  design range = {result.target_range_km} km\n"
        f"Required battery capacity: {result.battery_capacity_kwh} kWh\n"
        + "=" * 60
    )
    rows = [f"{'Metric':<20}{'Value':>12}{'Budget':>12}   Status"]
    rows.append("-" * 60)
    for m in result.metrics:
        status = "OK" if m["within_budget"] else "OVER"
        rows.append(
            f"{m['name']:<20}{m['value']:>10} {m['unit']:<1}"
            f"{m['budget']:>10} {m['unit']:<1}   {status}"
        )
    footer = "-" * 60 + f"\nVERDICT: {result.verdict}"
    return "\n".join([header, *rows, footer])


def main() -> int:
    result = evaluate()
    print(render_table(result))

    # Machine-readable report next to this file for the analysis agent / CI.
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_study_report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(asdict(result), fh, indent=2)
        fh.write("\n")

    # Non-zero exit on FAIL so a PR check turns red when the design won't close.
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
