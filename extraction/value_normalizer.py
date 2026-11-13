# -*- coding: utf-8 -*-
"""Normalize geological table values and units while preserving raw values for provenance."""

import re
from typing import Any, Dict


UNIT_ALIASES = {
    "m3": "m³", "m2": "m²", "cm3": "cm³",
    "g/cm3": "g/cm³", "kn/m3": "kN/m³",
    "mpa": "MPa", "kpa": "kPa", "gpa": "GPa",
}


def _canonical_unit(unit: str) -> str:
    compact = unit.strip().replace(" ", "")
    return UNIT_ALIASES.get(compact.lower(), compact)


def _header_unit(header: str) -> str:
    match = re.search(r"[\(（]\s*([^\)）]+)\s*[\)）]", header)
    return _canonical_unit(match.group(1)) if match else ""


def normalize_measurement(raw_value: Any, header: str = "") -> Dict[str, Any]:
    """Parse scalar values, ranges and ten-thousand/scientific multipliers; return normalized and raw values."""
    raw = "" if raw_value is None else str(raw_value).strip()
    result: Dict[str, Any] = {
        "raw": raw,
        "value": raw,
        "unit": _header_unit(header),
        "is_numeric": False,
        "is_range": False,
    }
    if not raw:
        return result

    text = (
        raw.replace("－", "-").replace("—", "-")
        .replace("～", "~").replace("至", "~")
        .replace("×10^4", "×10⁴").replace("x10^4", "×10⁴")
    )
    unit_match = re.search(
        r"(kN/m³|g/cm³|g/cm3|kg/m³|m³/s|m³|m²|mm/d|mm/月|cm/d|m/s|"
        r"MPa|kPa|GPa|mm|cm|km|m|°|%|人|户|元)$",
        text, re.I,
    )
    numeric_text = text
    if unit_match:
        result["unit"] = _canonical_unit(unit_match.group(1))
        numeric_text = text[:unit_match.start()].strip()

    multiplier = 1.0
    if "×10⁴" in numeric_text:
        multiplier = 10000.0
        numeric_text = numeric_text.replace("×10⁴", "")
    elif numeric_text.endswith("万"):
        multiplier = 10000.0
        numeric_text = numeric_text[:-1]

    number = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
    range_match = re.fullmatch(fr"\s*({number})\s*[-~]\s*({number})\s*", numeric_text)
    single_match = re.fullmatch(fr"\s*({number})\s*", numeric_text)
    if range_match:
        low = float(range_match.group(1)) * multiplier
        high = float(range_match.group(2)) * multiplier
        result.update({
            "value": [low, high], "min": min(low, high), "max": max(low, high),
            "is_numeric": True, "is_range": True, "multiplier": multiplier,
        })
    elif single_match:
        result.update({
            "value": float(single_match.group(1)) * multiplier,
            "is_numeric": True, "multiplier": multiplier,
        })
    return result
