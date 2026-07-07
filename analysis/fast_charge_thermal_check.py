#!/usr/bin/env python3
"""EV Fast-Charge Thermal Margin Checker.

A small, self-contained analysis that answers one engineering question:

    "At the configured charge rate, does every cell stay below its safe
     temperature limit?"

It reads design parameters from ``config.yaml``, runs a simplified lumped
steady-state thermal model, and emits both a human-readable summary and a
machine-readable ``analysis_report.json``. Flow's analysis agent picks up that
report (and the code + config) whenever the repo changes and reasons about it.

The model is intentionally simple but self-consistent: the point of this repo
is to demonstrate a Flow analysis loop where changing a single value in
``config.yaml`` flips the outcome — not to be a production BMS simulator.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

import yaml

# Directory of this file, so the script works regardless of CWD (CI vs local).
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(REPO_ROOT, "config.yaml")
REPORT_PATH = os.path.join(REPO_ROOT, "analysis_report.json")

# --- Cooling model constants -------------------------------------------------
# Effective per-cell heat-transfer coefficient is modelled as a baseline
# (natural convection / conduction to the cold plate) plus a term that scales
# with coolant flow. Units: watts removed per degree C of cell-over-ambient
# rise, per cell. These representative demo constants are calibrated so that a
# ~1.5C charge sits comfortably within limit while a ~3C charge overheats —
# i.e. the C-rate knob in config.yaml straddles the PASS/FAIL boundary.
BASE_HEAT_TRANSFER_W_PER_C = 0.003          # still-air / structural baseline
FLOW_HEAT_TRANSFER_W_PER_C_PER_LPM = 0.0005  # gain per litre/min of coolant


@dataclass
class ThermalResult:
    """Structured outcome of the thermal check — serialised to JSON."""

    charge_c_rate: float
    charge_current_per_cell_a: float
    heat_per_cell_w: float
    cooling_coefficient_w_per_c: float
    temp_rise_c: float
    peak_cell_temp_c: float
    max_safe_cell_temp_c: float
    thermal_margin_c: float
    verdict: str  # "PASS" or "FAIL"


def load_config(path: str = CONFIG_PATH) -> dict:
    """Load the design parameters the engineer edits."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def evaluate(cfg: dict) -> ThermalResult:
    """Run the lumped steady-state thermal model.

    Chain of reasoning:
      1. Per-cell capacity comes from splitting pack energy across the
         series/parallel array at the nominal cell voltage.
      2. Charge current per cell = C-rate x per-cell capacity.
      3. Heat generated in each cell is ohmic: Q = I^2 * R.
      4. Cooling capability grows with coolant flow.
      5. Steady-state temperature rise = generated heat / cooling coefficient.
      6. Peak cell temp = ambient + rise; compare against the safety limit.
    """
    # 1. Per-cell usable capacity (amp-hours).
    total_cells = cfg["num_cells_series"] * cfg["num_cells_parallel"]
    pack_wh = cfg["pack_capacity_kwh"] * 1000.0
    # Energy per cell / nominal voltage = amp-hours per cell.
    cell_capacity_ah = pack_wh / (total_cells * cfg["cell_nominal_voltage"])

    # 2. Charge current drawn by each cell at the configured C-rate.
    charge_current_per_cell_a = cfg["charge_c_rate"] * cell_capacity_ah

    # 3. Ohmic heat per cell. Convert milliohms -> ohms.
    resistance_ohm = cfg["cell_internal_resistance_mohm"] / 1000.0
    heat_per_cell_w = charge_current_per_cell_a**2 * resistance_ohm

    # 4. Effective cooling coefficient scales with coolant flow.
    cooling_coefficient = (
        BASE_HEAT_TRANSFER_W_PER_C
        + FLOW_HEAT_TRANSFER_W_PER_C_PER_LPM * cfg["coolant_flow_lpm"]
    )

    # 5. Steady-state temperature rise above ambient.
    temp_rise_c = heat_per_cell_w / cooling_coefficient

    # 6. Peak temperature and margin against the safety limit.
    peak_cell_temp_c = cfg["ambient_temp_c"] + temp_rise_c
    max_safe = cfg["max_safe_cell_temp_c"]
    thermal_margin_c = max_safe - peak_cell_temp_c

    return ThermalResult(
        charge_c_rate=round(cfg["charge_c_rate"], 3),
        charge_current_per_cell_a=round(charge_current_per_cell_a, 2),
        heat_per_cell_w=round(heat_per_cell_w, 3),
        cooling_coefficient_w_per_c=round(cooling_coefficient, 3),
        temp_rise_c=round(temp_rise_c, 2),
        peak_cell_temp_c=round(peak_cell_temp_c, 2),
        max_safe_cell_temp_c=round(max_safe, 2),
        thermal_margin_c=round(thermal_margin_c, 2),
        # A non-negative margin means every cell stays within limit.
        verdict="PASS" if thermal_margin_c >= 0 else "FAIL",
    )


def render_summary(result: ThermalResult) -> str:
    """Format a readable summary for logs and the CI console."""
    lines = [
        "EV Fast-Charge Thermal Margin Check",
        "=" * 40,
        f"  Charge rate            : {result.charge_c_rate} C",
        f"  Current per cell       : {result.charge_current_per_cell_a} A",
        f"  Heat per cell          : {result.heat_per_cell_w} W",
        f"  Cooling coefficient    : {result.cooling_coefficient_w_per_c} W/C",
        f"  Temperature rise       : {result.temp_rise_c} C",
        f"  Peak cell temperature  : {result.peak_cell_temp_c} C",
        f"  Safe limit             : {result.max_safe_cell_temp_c} C",
        f"  Thermal margin         : {result.thermal_margin_c} C",
        "-" * 40,
        f"  VERDICT                : {result.verdict}",
    ]
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    result = evaluate(cfg)

    # Human-readable summary to stdout.
    print(render_summary(result))

    # Machine-readable report for Flow's analysis agent to consume.
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(asdict(result), fh, indent=2)
        fh.write("\n")

    # Exit non-zero on FAIL so CI / any watcher can gate on it.
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
