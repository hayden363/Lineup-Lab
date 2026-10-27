"""
PLAYER VALUE FIELDS — three different numbers that must never share a column
==============================================================================
The app shows three numbers per player that look alike and mean different things:

  projected_ppg  expected fantasy points per game (board column PROJ). Example: ~17.5.
  vorp           projected_ppg minus the free-replacement level at his position (board column VOR).
                 Example: ~8.6. It is NOT points and NOT a trade value.
  pvs_score      the normalised 0-100 Player Value Score (engine/pvs.py), the number trades are built on.

They are returned as separate, explicitly named, strictly typed fields next to the legacy keys
(PROJ, VOR, PVS), so nothing downstream has to guess which of 8.9 / 18.8 / 72 is which. VALUE (the
board's older 0-100 rescaling of VORP) is deliberately not part of this schema.
"""

import math
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class PlayerValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    projected_ppg: Optional[float] = Field(None, description="expected fantasy points per game")
    vorp: Optional[float] = Field(None, description="projected_ppg minus the positional replacement level")
    pvs_score: Optional[float] = Field(None, ge=0, le=100, description="Player Value Score, 0-100")

    @model_validator(mode="after")
    def _vorp_is_points_above_a_non_negative_baseline(self):
        # replacement level is a points-per-game number >= 0, so VORP can never exceed the projection itself
        if self.projected_ppg is not None and self.vorp is not None and self.vorp > self.projected_ppg + 1e-6:
            raise ValueError(f"vorp ({self.vorp}) exceeds projected_ppg ({self.projected_ppg}): the two fields are mixed up")
        return self


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def value_fields(row: Mapping, proj_key="PROJ", vorp_key="VOR", pvs_key="PVS") -> dict:
    """{"projected_ppg", "vorp", "pvs_score"} from a board-style row, each None when the row lacks it.
    A row that breaks the schema (PVS outside 0-100, VORP above the projection) is logged and returned
    as all-None rather than failing the whole response: wrong data must be visible, not shown as fact."""
    raw = {"projected_ppg": _num(row.get(proj_key)), "vorp": _num(row.get(vorp_key)),
           "pvs_score": _num(row.get(pvs_key))}
    try:
        return PlayerValue(**raw).model_dump()
    except ValidationError as e:
        print(f"[schemas] dropped inconsistent value fields for {row.get('player_display_name')}: {e.errors()[0]['msg']}")
        return {"projected_ppg": None, "vorp": None, "pvs_score": None}


def with_value_fields(records, **keys):
    """Adds the three fields to each dict in `records` (in place) and returns it."""
    for r in records:
        r.update(value_fields(r, **keys))
    return records
