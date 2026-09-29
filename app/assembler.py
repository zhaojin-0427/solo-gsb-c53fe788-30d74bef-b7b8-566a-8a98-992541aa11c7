"""把求解器切割树（局部坐标）组装为 API 响应结构（绝对坐标，JSON dict）。"""
from __future__ import annotations

from typing import List

from .solver import ChosenPattern, Node

STATUS_TEXT = {
    "optimal": "已求得最优方案：所用板材总面积最小，且在该前提下切割次数最少。",
    "feasible": "已找到可行方案，但搜索在限定时间内结束，未能证明其为最优。",
    "unknown": "在限定时间内尚未找到可行方案（这不等于无解；可加长搜索时间后重试）。",
    "infeasible": "已证实在给定板材、缺陷与零件条件下不存在可行切割方案。",
}


def _serialize(node: Node, ox: int, oy: int, board_index: int,
               state: dict, parent_cut, cut_seq: list,
               placements: list) -> dict:
    if node.kind == "cut":
        state["nid"] += 1
        nid = state["nid"]
        state["no"] += 1
        no = state["no"]
        k = state["kerf"]
        if node.direction == "V":
            kerf_rect = {"x": ox + node.pos, "y": oy,
                         "width": k, "height": node.h}
            c0_origin = (ox, oy)
            c1_origin = (ox + node.pos + k, oy)
        else:
            kerf_rect = {"x": ox, "y": oy + node.pos,
                         "width": node.w, "height": k}
            c0_origin = (ox, oy)
            c1_origin = (ox, oy + node.pos + k)

        cut_seq.append({
            "board_index": board_index,
            "cut_no": no,
            "direction": node.direction,
            "rect": {"x": ox, "y": oy,
                     "width": node.w, "height": node.h},
            "kerf_rect": kerf_rect,
            "parent_cut_no": parent_cut,
        })
        children = [
            _serialize(node.children[0], *c0_origin, board_index, state,
                       no, cut_seq, placements),
            _serialize(node.children[1], *c1_origin, board_index, state,
                       no, cut_seq, placements),
        ]
        return {
            "id": nid,
            "x": ox, "y": oy, "width": node.w, "height": node.h,
            "kind": "cut", "direction": node.direction,
            "cut_position": node.pos, "cut_index": no,
            "children": children,
            "part_index": None, "part_rotated": None,
        }

    state["nid"] += 1
    nid = state["nid"]
    if node.kind == "product":
        i = node.part_idx
        placements.append({
            "part_index": i,
            "part_no": i + 1,
            "board_index": board_index,
            "x": ox, "y": oy,
            "width": node.w, "height": node.h,
            "rotated": bool(node.rotated),
            "produced_by_cut_no": parent_cut,
        })
        return {
            "id": nid, "x": ox, "y": oy,
            "width": node.w, "height": node.h, "kind": "product",
            "direction": None, "cut_position": None, "cut_index": None,
            "children": None, "part_index": i,
            "part_rotated": bool(node.rotated),
        }

    return {
        "id": nid, "x": ox, "y": oy,
        "width": node.w, "height": node.h, "kind": "waste",
        "direction": None, "cut_position": None, "cut_index": None,
        "children": None, "part_index": None, "part_rotated": None,
    }


def build_response_payload(req, solve_result: dict) -> dict:
    chosen: List[ChosenPattern] = solve_result["chosen"]
    kerf = req.kerf
    cut_seq: list = []
    placements: list = []
    trees: list = []
    used_indices: list = []
    used_area = 0

    # 全局连续刀号：按板顺序，板内 DFS 前序
    state = {"no": 0, "nid": 0, "kerf": kerf}
    for ch in chosen:
        bi = ch.board
        used_indices.append(bi)
        used_area += req.boards[bi].width * req.boards[bi].height
        trees.append(_serialize(ch.root, 0, 0, bi, state, None,
                                cut_seq, placements))

    placements.sort(key=lambda d: d["part_index"])

    # 每块板内刀号从 1 起；cut_seq 已是各板 DFS 前序，直接给出全局编号
    total_cuts = len(cut_seq)
    return {
        "status": solve_result["status"],
        "status_text": STATUS_TEXT[solve_result["status"]],
        "used_board_indices": used_indices,
        "used_area": used_area,
        "total_cuts": total_cuts,
        "elapsed_seconds": round(solve_result["elapsed"], 4),
        "time_limit_seconds": req.time_limit_seconds,
        "objective": solve_result.get("objective"),
        "enum_complete": solve_result.get("enum_complete"),
        "pattern_count": solve_result.get("pattern_count"),
        "trees": trees,
        "part_placements": placements,
        "cut_sequence": cut_seq,
        "boards": [b.model_dump() for b in req.boards],
        "parts": [p.model_dump() for p in req.parts],
        "kerf": kerf,
    }
