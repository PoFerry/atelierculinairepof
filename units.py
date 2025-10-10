from __future__ import annotations
def to_base_units(quantity: float, unit: str, base_unit: str) -> float:
    unit = unit.lower()
    base_unit = base_unit.lower()
    weight = {"mg": 0.001, "g": 1.0, "kg": 1000.0}
    volume = {"ml": 1.0, "l": 1000.0}
    if base_unit == "unit":
        if unit not in ("unit","un","pcs","piece","pièce"):
            raise ValueError(f"Unsupported unit '{unit}' for base_unit 'unit'")
        return float(quantity)
    if base_unit == "g":
        if unit not in weight: raise ValueError(f"Unsupported unit '{unit}' for base_unit 'g'")
        return float(quantity) * weight[unit]
    if base_unit == "ml":
        if unit not in volume: raise ValueError(f"Unsupported unit '{unit}' for base_unit 'ml'")
        return float(quantity) * volume[unit]
    raise ValueError(f"Unsupported base_unit '{base_unit}'")
def normalize_unit(u: str) -> str:
    u = u.lower()
    return {"l":"l","ml":"ml","g":"g","kg":"kg","mg":"mg","unit":"unit","un":"unit","pcs":"unit"}.get(u,u)
