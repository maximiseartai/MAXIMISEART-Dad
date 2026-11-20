from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.domain import RunMode

StoredRunMode = Annotated[
    RunMode, BeforeValidator(RunMode.stored, json_schema_input_type=RunMode | Literal["zapis", "podgląd"])
]

StoredPageId = timing_contract.PageId | Literal["konfiguracja"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CentrumStarted(_Record):
    at: datetime
    action: Literal["start Centrum"]


class ViewOpened(_Record):
    at: datetime
    action: Literal["widok"]
    page: StoredPageId
    kind: timing_contract.ViewKind


class ButtonPressed(_Record):
    at: datetime
    action: Literal["przycisk"]
    operation: timing_contract.ApiOperation
    process: common_contract.ProcessKey | None = None
    mode: StoredRunMode | None = None


DadAction = Annotated[CentrumStarted | ViewOpened | ButtonPressed, Field(discriminator="action")]


class DadActions(_Record):
    entries: list[DadAction]
    omitted: int
