"""板材顺序锯切规划台 — 输入模型与校验。"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, model_validator


class DefectIn(BaseModel):
    x: int = Field(..., ge=0, description="缺陷左上角 x（毫米）")
    y: int = Field(..., ge=0, description="缺陷左上角 y（毫米）")
    width: int = Field(..., ge=1, description="缺陷宽度（正整数毫米）")
    height: int = Field(..., ge=1, description="缺陷高度（正整数毫米）")


class BoardIn(BaseModel):
    name: str = Field("", description="板材名称（可空）")
    width: int = Field(..., ge=1, description="板材宽度（正整数毫米）")
    height: int = Field(..., ge=1, description="板材高度（正整数毫米）")
    defects: List[DefectIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _defects_inside(self) -> "BoardIn":
        for i, d in enumerate(self.defects):
            if d.x + d.width > self.width or d.y + d.height > self.height:
                raise ValueError(f"缺陷 #{i + 1} 超出板材「{self.label()}」范围")
        return self

    def label(self) -> str:
        return self.name.strip() or f"{self.width}×{self.height}"


class PartIn(BaseModel):
    name: str = Field("", description="零件名称（可空）")
    width: int = Field(..., ge=1, description="零件宽度（正整数毫米）")
    height: int = Field(..., ge=1, description="零件高度（正整数毫米）")
    rotatable: bool = Field(False, description="是否允许旋转 90°")

    def label(self) -> str:
        return self.name.strip() or f"{self.width}×{self.height}"


class SolveRequest(BaseModel):
    boards: List[BoardIn] = Field(..., min_length=1, max_length=3)
    parts: List[PartIn] = Field(..., min_length=1, max_length=8)
    kerf: int = Field(0, ge=0, description="锯缝宽度（非负整数毫米）")
    time_limit_seconds: float = Field(10.0, ge=0.1, le=120.0)


# 求解结果以普通 dict（JSON）返回，结构见 assembler.build_response_payload：
#   status / status_text、used_board_indices、used_area、total_cuts、
#   trees（切割树，节点含绝对坐标 x/y/width/height、kind、direction、
#   cut_position、cut_index、children、part_index、part_rotated）、
#   part_placements（成品下料位置）、cut_sequence（逐刀顺序与锯缝矩形）。
STATUS_VALUES = ("optimal", "feasible", "unknown", "infeasible")
Status = Literal["optimal", "feasible", "unknown", "infeasible"]
