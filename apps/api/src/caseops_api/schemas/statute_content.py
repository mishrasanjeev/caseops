"""Bounded, source-preserving statutory table content, never inferred cells."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StatuteTableFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, le=10000)
    bbox: tuple[float, float, float, float]
    cells: list[str] = Field(min_length=2, max_length=12)


class StatuteTableRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serial: str = Field(min_length=1, max_length=40)
    cells: list[str] = Field(min_length=2, max_length=12)
    fragments: list[StatuteTableFragment] = Field(min_length=1, max_length=20)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_cells(self):
        if any(len(cell) > 20000 for cell in self.cells):
            raise ValueError("Statutory table cell exceeds source bound")
        if (
            hashlib.sha256(json.dumps(self.cells, ensure_ascii=False).encode()).hexdigest()
            != self.sha256
        ):
            raise ValueError("Statutory table cell hash mismatch")
        rebuilt = list(self.fragments[0].cells)
        previous = 0
        for index, fragment in enumerate(self.fragments):
            if any(len(cell) > 20000 for cell in fragment.cells):
                raise ValueError("Statutory table source cell exceeds bound")
            left, top, right, bottom = fragment.bbox
            if not 0 <= left < right <= 10000 or not 0 <= top < bottom <= 10000:
                raise ValueError("Invalid statutory table source bounds")
            if fragment.page < previous or len(fragment.cells) != len(self.cells):
                raise ValueError("Invalid statutory table source fragment")
            previous = fragment.page
            if index:
                if fragment.cells[0]:
                    raise ValueError("Continuation cannot introduce another identity")
                for column, cell in enumerate(fragment.cells):
                    if cell:
                        rebuilt[column] += "\n" + cell
        if rebuilt != self.cells:
            raise ValueError("Statutory table fragments do not reconstruct cells")
        return self


class StatuteTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    columns: list[str] = Field(min_length=2, max_length=12)
    rows: list[StatuteTableRow] = Field(min_length=1, max_length=5000)
    physical_row_count: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def exact_inventory(self):
        if any(not column or len(column) > 1000 for column in self.columns):
            raise ValueError("Invalid statutory table column label")
        if sum(len(cell) for row in self.rows for cell in row.cells) > 2000000:
            raise ValueError("Statutory table exceeds total source bound")
        if len({row.serial for row in self.rows}) != len(self.rows):
            raise ValueError("Duplicate statutory table identity")
        if any(len(row.cells) != len(self.columns) for row in self.rows):
            raise ValueError("Statutory table column inventory mismatch")
        if sum(len(row.fragments) for row in self.rows) != self.physical_row_count:
            raise ValueError("Statutory table physical inventory mismatch")
        return self
