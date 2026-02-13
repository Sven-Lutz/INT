from dataclasses import dataclass


@dataclass(frozen=True)
class FillingInputs:
    target_mbar: float
    ramp_s: float
    hold_s: float


@dataclass(frozen=True)
class FillingComputed:
    target_pct: float
    slope_mbar_per_s: float
    suggested_ramp_s: float


def mbar_to_percent(mbar: float, full_scale_mbar: float) -> float:
    if full_scale_mbar <= 0:
        raise ValueError("full_scale_mbar must be > 0")
    pct = (float(mbar) / float(full_scale_mbar)) * 100.0
    return max(0.0, min(100.0, pct))


def suggest_ramp_seconds(target_mbar: float) -> float:
    m = abs(float(target_mbar))
    return max(5.0, min(30.0, (m / 50.0) * 5.0))


def compute_filling(
    inputs: FillingInputs,
    *,
    full_scale_mbar: float,
) -> FillingComputed:
    target_pct = mbar_to_percent(inputs.target_mbar, full_scale_mbar)
    ramp_s = float(inputs.ramp_s)
    if ramp_s <= 0:
        ramp_s = suggest_ramp_seconds(inputs.target_mbar)
    slope = float(inputs.target_mbar) / ramp_s if ramp_s > 0 else 0.0
    return FillingComputed(
        target_pct=target_pct,
        slope_mbar_per_s=slope,
        suggested_ramp_s=ramp_s,
    )
