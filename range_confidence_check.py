#!/usr/bin/env python3
"""EV Range Confidence Checker — single-file Flow analysis example.

One engineering question:

    "For the planned trip, will the EV arrive with the required charge reserve
     still in the battery — accounting for cold weather and payload?"

Everything lives in this one file: the tunable parameters are constants at the
top, the model is below, and running it prints a summary plus writes a
machine-readable `range_report.json` for Flow's analysis agent to consume.

Turn the knob and the verdict flips:

    TARGET_TRIP_KM = 300  -> PASS (arrives with healthy reserve)
    TARGET_TRIP_KM = 480  -> FAIL (reserve exhausted before arrival)

Pure standard library — no pip install required.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

# =============================================================================
# PARAMETERS — this is what you edit
# =============================================================================

# ---- The knob to turn -------------------------------------------------------
TARGET_TRIP_KM = 480.0          # Planned trip distance (km)

# ---- Trip conditions --------------------------------------------------------
AMBIENT_TEMP_C = 20.0           # Outside air temperature (deg C). Cold cuts range.
PAYLOAD_KG = 150.0              # Passengers + cargo above curb weight (kg)
AVG_SPEED_KMH = 100.0           # Average cruising speed (km/h). Faster = more drag.

# ---- Vehicle characteristics ------------------------------------------------
BATTERY_CAPACITY_KWH = 75.0     # Usable pack energy when new & warm (kWh)
BASE_CONSUMPTION_WH_PER_KM = 160.0   # Reference efficiency at 20C, no payload, 100 km/h

# ---- Safety policy ----------------------------------------------------------
REQUIRED_RESERVE_FRACTION = 0.15  # Must still have >=15% charge on arrival

# =============================================================================
# MODEL
# =============================================================================

# Below this reference temperature the pack loses usable capacity and the
# cabin heater draws extra energy. Above it, no cold penalty is applied.
COLD_REFERENCE_TEMP_C = 20.0
# Fraction of usable capacity lost per degree C below the reference.
CAPACITY_LOSS_PER_DEG_C = 0.006      # ~0.6%/C -> ~18% lost at -10C
# Extra consumption from cabin heating per degree C below the reference.
HEATER_WH_PER_KM_PER_DEG_C = 1.6
# Extra consumption per kg of payload (heavier car works harder).
PAYLOAD_WH_PER_KM_PER_KG = 0.03
# Aerodynamic drag rises with the square of speed, referenced to 100 km/h.
REFERENCE_SPEED_KMH = 100.0
SPEED_DRAG_WH_PER_KM_AT_REF = 40.0   # portion of base consumption that is speed-sensitive


@dataclass
class RangeResult:
    """Structured outcome — serialised to JSON for the Flow agent."""

    target_trip_km: float
    ambient_temp_c: float
    usable_capacity_kwh: float
    consumption_wh_per_km: float
    estimated_range_km: float
    energy_needed_kwh: float
    arrival_charge_fraction: float
    required_reserve_fraction: float
    reserve_margin_km: float
    verdict: str  # "PASS" or "FAIL"


def evaluate() -> RangeResult:
    """Run the range/energy-budget model.

    Reasoning chain:
      1. Cold weather derates usable capacity below the reference temperature.
      2. Consumption is the base figure plus penalties for cold-weather cabin
         heating, payload, and cruising speed (drag ~ v^2).
      3. Estimated range = usable energy / consumption.
      4. The trip must finish with at least the required reserve fraction, so
         the usable range for planning excludes that reserve.
    """
    # How far below the reference temperature are we? (0 if warm.)
    degrees_below_ref = max(0.0, COLD_REFERENCE_TEMP_C - AMBIENT_TEMP_C)

    # 1. Cold-derated usable capacity (never below zero, capped derate at 100%).
    capacity_derate = min(1.0, CAPACITY_LOSS_PER_DEG_C * degrees_below_ref)
    usable_capacity_kwh = BATTERY_CAPACITY_KWH * (1.0 - capacity_derate)

    # 2. Effective consumption: base + heater + payload + speed-drag penalties.
    heater_penalty = HEATER_WH_PER_KM_PER_DEG_C * degrees_below_ref
    payload_penalty = PAYLOAD_WH_PER_KM_PER_KG * PAYLOAD_KG
    # Drag scales with the square of the speed ratio relative to the reference.
    speed_ratio = AVG_SPEED_KMH / REFERENCE_SPEED_KMH
    speed_penalty = SPEED_DRAG_WH_PER_KM_AT_REF * (speed_ratio**2 - 1.0)
    consumption_wh_per_km = (
        BASE_CONSUMPTION_WH_PER_KM + heater_penalty + payload_penalty + speed_penalty
    )

    # 3. Total range on a full usable pack.
    estimated_range_km = (usable_capacity_kwh * 1000.0) / consumption_wh_per_km

    # 4. Energy the trip consumes, and the charge left on arrival.
    energy_needed_kwh = consumption_wh_per_km * TARGET_TRIP_KM / 1000.0
    arrival_charge_fraction = 1.0 - (energy_needed_kwh / usable_capacity_kwh)

    # Distance we can travel while still preserving the required reserve.
    planning_range_km = estimated_range_km * (1.0 - REQUIRED_RESERVE_FRACTION)
    reserve_margin_km = planning_range_km - TARGET_TRIP_KM

    return RangeResult(
        target_trip_km=round(TARGET_TRIP_KM, 1),
        ambient_temp_c=round(AMBIENT_TEMP_C, 1),
        usable_capacity_kwh=round(usable_capacity_kwh, 2),
        consumption_wh_per_km=round(consumption_wh_per_km, 1),
        estimated_range_km=round(estimated_range_km, 1),
        energy_needed_kwh=round(energy_needed_kwh, 2),
        arrival_charge_fraction=round(arrival_charge_fraction, 3),
        required_reserve_fraction=REQUIRED_RESERVE_FRACTION,
        reserve_margin_km=round(reserve_margin_km, 1),
        # PASS only if we arrive with at least the required reserve intact.
        verdict="PASS" if reserve_margin_km >= 0 else "FAIL",
    )


def render_summary(r: RangeResult) -> str:
    """Human-readable summary for logs and the CI console."""
    return "\n".join(
        [
            "EV Range Confidence Check",
            "=" * 40,
            f"  Planned trip           : {r.target_trip_km} km",
            f"  Ambient temperature    : {r.ambient_temp_c} C",
            f"  Usable capacity        : {r.usable_capacity_kwh} kWh",
            f"  Consumption            : {r.consumption_wh_per_km} Wh/km",
            f"  Estimated total range  : {r.estimated_range_km} km",
            f"  Energy needed for trip : {r.energy_needed_kwh} kWh",
            f"  Charge left on arrival : {r.arrival_charge_fraction * 100:.1f} %",
            f"  Required reserve       : {r.required_reserve_fraction * 100:.0f} %",
            f"  Reserve margin         : {r.reserve_margin_km} km",
            "-" * 40,
            f"  VERDICT                : {r.verdict}",
        ]
    )


def main() -> int:
    result = evaluate()
    print(render_summary(result))

    # Machine-readable report next to this file for Flow's analysis agent.
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "range_report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(asdict(result), fh, indent=2)
        fh.write("\n")

    # Non-zero exit on FAIL so CI or any watcher can gate on the outcome.
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
