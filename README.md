# EV Fast-Charge Thermal Margin Checker

A tiny, self-contained example for driving a **Flow analysis agent** off a
GitHub repo. It models one real EV engineering question:

> At the configured fast-charge rate, does every battery cell stay below its
> safe temperature limit?

Change **one value** in [`config.yaml`](config.yaml), commit, and the outcome
flips between **PASS** and **FAIL**. Flow watches the repo, and when it changes
the analysis re-runs and an analysis agent reviews the result.

## The knob

Open [`config.yaml`](config.yaml) and edit `charge_c_rate`:

| `charge_c_rate` | Peak cell temp | Verdict |
| --------------- | -------------- | ------- |
| `1.0`           | ~28.6 °C       | ✅ PASS |
| `1.5` (default) | ~33.1 °C       | ✅ PASS |
| `2.0`           | ~39.5 °C       | ✅ PASS |
| `2.5`           | ~47.6 °C       | ✅ PASS |
| `3.0`           | ~57.5 °C       | ❌ FAIL (over 55 °C limit) |

The safe limit is `max_safe_cell_temp_c` (default 55 °C). You can also turn the
secondary knobs — `coolant_flow_lpm`, `ambient_temp_c`, or the pack
architecture — and watch the margin move.

## How it works

`analysis/fast_charge_thermal_check.py` runs a simplified lumped steady-state
thermal model:

1. Per-cell capacity from the pack energy and series/parallel array.
2. Per-cell charge current = C-rate × per-cell capacity.
3. Ohmic self-heating per cell, `Q = I²R`.
4. Cooling capability that scales with coolant flow.
5. Steady-state temperature rise = heat ÷ cooling.
6. Peak cell temp = ambient + rise, compared against the safety limit.

It prints a summary and writes a machine-readable
[`analysis_report.json`](analysis_report.json) that the Flow agent consumes.
The script exits non-zero on **FAIL**, so any watcher (CI or Flow) can gate on
the outcome.

## Run it locally

```bash
pip install -r requirements.txt
python analysis/fast_charge_thermal_check.py
```

## The Flow loop

1. Flow is configured to watch this repo.
2. You edit `charge_c_rate` (or any parameter) and push.
3. The change triggers Flow, which runs the analysis agent against the repo.
4. The agent reads the code, `config.yaml`, and `analysis_report.json`, then
   reports whether the design is thermally safe and why.

A GitHub Actions workflow ([`.github/workflows/flow-analysis.yml`](.github/workflows/flow-analysis.yml))
mirrors this on every push so the check and its report are always current.

> ⚠️ **Demo model.** The cooling constants are calibrated so the C-rate knob
> straddles the PASS/FAIL boundary for demonstration — this is not a
> production BMS thermal simulator.
