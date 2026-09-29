"""锯切规划求解器。

两阶段：
1. 模式枚举（带记忆的穷举 DFS）：对每块板材与每个零件子集，枚举所有可行的
   Guillotine 切割树（每刀横/竖贯穿当前子矩形，锯缝占宽），保留刀数最少的一棵。
   成品叶区必须与零件尺寸完全一致且不覆盖缺陷；其余叶区均为废料（缺陷可留在废料中）。
2. OR-Tools CP-SAT 集合划分：在各板的可行模式中挑选模式组合，使零件各产出一次，
   目标 = ARENA * 所用板材总面积 + 总刀数（字典序：先面积，后刀数）。

坐标全部使用“相对当前子矩形”的局部坐标；缺陷在递归切分时换算到子矩形坐标系。
不与任何缺陷相交的子矩形只与 (宽, 高, 零件子集) 有关，可跨位置共享记忆化结果。

超时语义（关键，不能把“没搜完”误报成无解）：
- 枚举完整且 CP-SAT 证明最优   -> optimal
- 找到方案但未证最优           -> feasible
- 未找到方案：仅当枚举完整且模型被证不可行 -> infeasible，否则一律 unknown
即使枚举超时，也会用已收集到的（部分）模式运行 CP-SAT；只要找到方案就报 feasible。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from .models import BoardIn, PartIn

ARENA = 1000  # 面积权重；刀数上限 < 3*(2*8-1)=45，故字典序严格

# 局部坐标下的缺陷矩形：(x, y, width, height)
Defects = Tuple[Tuple[int, int, int, int], ...]


@dataclass
class Node:
    """切割树节点；坐标均为相对本节点子矩形原点的局部坐标。

    任何节点的根都恰好填满其所在子矩形（w × h）。
    """
    w: int
    h: int
    kind: str  # 'cut' | 'product' | 'waste'
    direction: Optional[str] = None      # 'V' 竖切（沿 y 轴方向走刀）| 'H' 横切
    pos: Optional[int] = None            # 锯缝起点（局部坐标）
    children: Optional[Tuple["Node", "Node"]] = None
    part_idx: Optional[int] = None
    rotated: Optional[bool] = None
    cuts: int = 0


@dataclass
class ChosenPattern:
    board: int
    mask: int
    root: Node


def _intersects(defects: Defects, x: int, y: int, w: int, h: int) -> bool:
    for dx, dy, dw, dh in defects:
        if x < dx + dw and x + w > dx and y < dy + dh and y + h > dy:
            return True
    return False


def _shift(defects: Defects, ox: int, oy: int,
           w: int, h: int) -> Defects:
    """取与子矩形 (ox,oy,w,h) 相交的缺陷，裁剪并换算到局部坐标。"""
    if not defects:
        return ()
    out = []
    x2, y2 = ox + w, oy + h
    for dx, dy, dw, dh in defects:
        ix0 = dx if dx > ox else ox
        iy0 = dy if dy > oy else oy
        ix1 = dx + dw
        if ix1 > x2:
            ix1 = x2
        iy1 = dy + dh
        if iy1 > y2:
            iy1 = y2
        if ix0 < ix1 and iy0 < iy1:
            out.append((ix0 - ox, iy0 - oy, ix1 - ix0, iy1 - iy0))
    return tuple(out)


class _Enumerator:
    def __init__(self, boards: List[BoardIn], parts: List[PartIn],
                 kerf: int, deadline: float):
        self.boards = boards
        self.parts = parts
        self.kerf = kerf
        self.deadline = deadline
        self.aborted = False
        self.calls = 0

        n = len(parts)
        self.n = n
        self.full = (1 << n) - 1
        self.area_sum = [0] * (1 << n)
        for m in range(1, 1 << n):
            lsb = m & -m
            i = lsb.bit_length() - 1
            self.area_sum[m] = self.area_sum[m ^ lsb] + parts[i].width * parts[i].height

        # 同规格零件分组：子集划分时取前缀，消除排列对称
        sig: Dict[tuple, List[int]] = {}
        for i, p in enumerate(parts):
            sig.setdefault((p.width, p.height, p.rotatable), []).append(i)
        self.dup_groups = [v for v in sig.values() if len(v) > 1]

        self.max_dim = max(
            [bd.width for bd in boards] + [bd.height for bd in boards])
        self.L_set, self.L_sorted = self._build_length_set()

        # (mask,w,h) 是否在尺寸上可容纳（不考虑缺陷）——预计算查找表
        self._contain_ok: Dict[Tuple[int, int, int], bool] = {}

        # (board, w, h, mask, defects) -> Node | None
        self.memo: Dict[tuple, Optional[Node]] = {}

    def _build_length_set(self) -> Tuple[set, List[int]]:
        """含零件子矩形在切分轴上的可能边长集合（必要条件）。

        由零件宽/高出发，按 a + kerf + b 闭包（大整数位集合加速）。
        """
        sides = {p.width for p in self.parts} | {p.height for p in self.parts}
        bits = 0
        for s in sides:
            if s <= self.max_dim:
                bits |= 1 << s
        k = self.kerf
        cap = (1 << (self.max_dim + 1)) - 1
        for _ in range(len(self.parts) + 1):
            cur = bits
            added = 0
            while cur:
                a = (cur & -cur).bit_length() - 1
                cur &= cur - 1
                added |= (bits << (a + k)) & cap
            added &= ~bits
            if not added:
                break
            bits |= added
        vals = sorted(i for i in range(1, self.max_dim + 1)
                      if bits & (1 << i))
        return set(vals), vals

    # ---------- 预筛 ----------

    def _can_contain(self, mask: int, w: int, h: int) -> bool:
        key = (mask, w, h)
        cached = self._contain_ok.get(key)
        if cached is not None:
            return cached
        m = mask
        ok = True
        while m:
            i = (m & -m).bit_length() - 1
            m &= m - 1
            p = self.parts[i]
            good = w >= p.width and h >= p.height
            if not good and p.rotatable:
                good = w >= p.height and h >= p.width
            if not good:
                ok = False
                break
        self._contain_ok[key] = ok
        return ok

    def _canonical_subset(self, mask: int, sub: int) -> bool:
        """同规格零件在划分中必须取组内前缀，消除对称解。sub ⊆ mask。"""
        for group in self.dup_groups:
            seen_gap = False
            for i in group:
                if not (mask & (1 << i)):
                    continue
                if sub & (1 << i):
                    if seen_gap:
                        return False
                else:
                    seen_gap = True
        return True

    def _tick(self) -> None:
        self.calls += 1
        if (self.calls & 4095) == 0 and time.perf_counter() > self.deadline:
            self.aborted = True

    # ---------- 核心递归 ----------

    def solve(self, b: int, w: int, h: int, mask: int,
              defects: Defects) -> Optional[Node]:
        """在 w×h（局部坐标）子矩形内产出 mask 零件，返回刀数最少的切割树。"""
        if self.aborted:
            return None  # 超时结果不入缓存
        if mask == 0:
            return Node(w, h, "waste")  # 纯废料：无需记忆化

        if self.area_sum[mask] > w * h or not self._can_contain(mask, w, h):
            return None

        self._tick()

        if mask & (mask - 1) == 0:
            # 单零件：四个角直接判定，开销极小，不记忆化（避免不同缺陷
            # 坐标组合产生海量缓存键；多零件递归的父状态才是缓存重点）
            if not defects:
                key = (b, w, h, mask, ())
                if key in self.memo:
                    return self.memo[key]
                r0 = self._isolate_single(w, h, mask, defects)
                self.memo[key] = r0
                return r0
            return self._isolate_single(w, h, mask, defects)

        # 无缺陷矩形与位置无关：缺陷元组用 () 统一，可跨位置共享
        key = (b, w, h, mask, defects if defects else ())
        if key in self.memo:
            return self.memo[key]

        result = self._best_split(b, w, h, mask, defects)
        self.memo[key] = result
        return result

    def _isolate_single(self, w: int, h: int, mask: int,
                        defects: Defects) -> Optional[Node]:
        """孤件成品必落在子矩形某一角；用 0~2 刀剥离废料条得到它。

        规范顺序：先竖切（贯穿整块高度）再在条带内横切；每刀都贯穿当时子矩形。
        """
        k = self.kerf
        i = mask.bit_length() - 1
        p = self.parts[i]
        orientations = [(p.width, p.height, False)]
        if p.rotatable and (p.height, p.width) != (p.width, p.height):
            orientations.append((p.height, p.width, True))

        best: Optional[Node] = None
        for pw, ph, rotated in orientations:
            if pw > w or ph > h:
                continue
            gapx, gapy = w - pw, h - ph
            if not (gapx == 0 or gapx >= k) or not (gapy == 0 or gapy >= k):
                continue
            for side_x in ("L", "R"):
                for side_y in ("T", "B"):
                    px = 0 if side_x == "L" else gapx
                    py = 0 if side_y == "T" else gapy
                    if _intersects(defects, px, py, pw, ph):
                        continue  # 成品不得覆盖缺陷
                    leaf = Node(pw, ph, "product", part_idx=i,
                                rotated=rotated)
                    node = leaf
                    # 内刀：横切（仅在成品所在竖条带内）
                    if gapy:
                        if side_y == "T":
                            waste = Node(pw, gapy - k, "waste")
                            node = Node(pw, h, "cut", direction="H",
                                        pos=ph, children=(node, waste),
                                        cuts=1)
                        else:
                            waste = Node(pw, gapy - k, "waste")
                            node = Node(pw, h, "cut", direction="H",
                                        pos=gapy - k,
                                        children=(waste, node), cuts=1)
                    # 外刀：竖切（贯穿整块高度）
                    if gapx:
                        if side_x == "L":
                            waste = Node(gapx - k, h, "waste")
                            node = Node(w, h, "cut", direction="V",
                                        pos=pw, children=(node, waste),
                                        cuts=node.cuts + 1)
                        else:
                            waste = Node(gapx - k, h, "waste")
                            node = Node(w, h, "cut", direction="V",
                                        pos=gapx - k,
                                        children=(waste, node),
                                        cuts=node.cuts + 1)
                    if best is None or node.cuts < best.cuts:
                        best = node
        return best

    def _best_split(self, b: int, w: int, h: int, mask: int,
                    defects: Defects) -> Optional[Node]:
        """枚举贯穿切分，取刀数最少者。

        两类切分（位置均为锯缝起点 p）：
        - 内容切分：两侧都含零件，两侧边长都 ∈ L；
        - 剥离切分：一侧纯废料（直接成叶），另一侧含全部零件且边长 ∈ L。
          内容侧无缺陷时左右镜像等价，只取规范朝向；内容侧含缺陷时
          反向朝向几何不同，需补枚举。
        """
        k = self.kerf
        best: Optional[Node] = None

        def try_split(direction: str, p: int, sub: int) -> None:
            nonlocal best
            other = mask if sub == 0 else mask & ~sub
            if direction == "V":
                w0, h0 = p, h
                w1, h1 = w - p - k, h
                d0 = _shift(defects, 0, 0, w0, h0)
                d1 = _shift(defects, p + k, 0, w1, h1)
            else:
                w0, h0 = w, p
                w1, h1 = w, h - p - k
                d0 = _shift(defects, 0, 0, w0, h0)
                d1 = _shift(defects, 0, p + k, w1, h1)
            if (self.area_sum[sub] > w0 * h0
                    or self.area_sum[other] > w1 * h1):
                return
            if (not self._can_contain(sub, w0, h0)
                    or not self._can_contain(other, w1, h1)):
                return
            n0 = Node(w0, h0, "waste") if sub == 0 \
                else self.solve(b, w0, h0, sub, d0)
            if self.aborted or n0 is None:
                return
            n1 = Node(w1, h1, "waste") if other == 0 \
                else self.solve(b, w1, h1, other, d1)
            if self.aborted or n1 is None:
                return
            cuts = 1 + n0.cuts + n1.cuts
            if best is None or cuts < best.cuts:
                best = Node(w, h, "cut", direction=direction, pos=p,
                            children=(n0, n1), cuts=cuts)

        def axis_loop(total, extent, direction, axis) -> None:
            """沿 x（竖切）/ y（横切）轴枚举一刀。total=被切边长。"""
            if total - k < 2:
                return

            # 内容切分位置：两侧边长都 ∈ L
            content_pos = [p for p in self.L_sorted
                           if 1 <= p <= total - k - 1
                           and (total - k - p) in self.L_set]

            # 剥离切分：内容侧（含全部零件）边长必须 ∈ L。
            for v in self.L_sorted:
                if not (1 <= v <= total - k - 1):
                    continue
                if self.aborted:
                    return
                # 正向：内容在左/上
                try_split(direction, v, mask)
                # 反向：内容在右/下。仅当正向内容侧含缺陷时，
                # 反向才不被无缺陷镜像支配。
                d_left = (_shift(defects, 0, 0, v, extent) if axis == "x"
                          else _shift(defects, 0, 0, extent, v))
                if d_left:
                    try_split(direction, total - k - v, 0)

            # 内容切分：按子集划分
            sub = (mask - 1) & mask
            while sub:
                if self.aborted:
                    return
                if self._canonical_subset(mask, sub):
                    aa = self.area_sum[sub]
                    ab = self.area_sum[mask & ~sub]
                    lo = max(1, math.ceil(aa / extent))
                    hi = total - k - math.ceil(ab / extent)
                    for p in content_pos:
                        if lo <= p <= hi:
                            try_split(direction, p, sub)
                            if self.aborted:
                                return
                sub = (sub - 1) & mask

        axis_loop(w, h, "V", "x")
        if not self.aborted:
            axis_loop(h, w, "H", "y")
        return best

    # ---------- 模式枚举入口 ----------

    def _try_mask(self, patterns: Dict[Tuple[int, int], Node],
                  bi: int, board: BoardIn, mask: int,
                  root_defects: Defects) -> None:
        if (bi, mask) in patterns or self.aborted:
            return
        if self.area_sum[mask] > board.width * board.height:
            return
        if not self._can_contain(mask, board.width, board.height):
            return
        node = self.solve(bi, board.width, board.height, mask, root_defects)
        if node is not None:
            patterns[(bi, mask)] = node

    def enumerate_full_only(self) -> Tuple[Dict[Tuple[int, int], Node], bool]:
        """阶段 1：只枚举各板全掩码模式，尽快找到整板可行方案。"""
        patterns: Dict[Tuple[int, int], Node] = {}
        for bi, board in enumerate(self.boards):
            if self.aborted:
                return patterns, False
            root_defects = tuple((d.x, d.y, d.width, d.height)
                                 for d in board.defects)
            self._try_mask(patterns, bi, board, self.full, root_defects)
        return patterns, not self.aborted

    def enumerate_remaining(self) -> Tuple[Dict[Tuple[int, int], Node], bool]:
        """阶段 2：补枚举所有非全掩码子集（复用阶段 1 的 memo）。"""
        patterns: Dict[Tuple[int, int], Node] = {}
        masks_by_pop = sorted(range(1, self.full),
                              key=lambda m: (-m.bit_count(), -m))
        for bi, board in enumerate(self.boards):
            if self.aborted:
                return patterns, False
            root_defects = tuple((d.x, d.y, d.width, d.height)
                                 for d in board.defects)
            for mask in masks_by_pop:
                if self.aborted:
                    return patterns, False
                self._try_mask(patterns, bi, board, mask, root_defects)
        return patterns, not self.aborted


# ---------- CP-SAT：跨板选模式 ----------

def solve_plan(boards: List[BoardIn], parts: List[PartIn], kerf: int,
               time_limit: float) -> dict:
    start = time.perf_counter()

    def run_cpsat(patterns: dict, complete: bool, budget: float) -> dict:
        """在给定（可能不完整的）模式集合上跑一次 CP-SAT。"""
        model = cp_model.CpModel()
        use_var: Dict[Tuple[int, int], cp_model.IntVar] = {}
        for (bi, mask) in patterns:
            use_var[(bi, mask)] = model.NewBoolVar(f"use_b{bi}_m{mask}")

        for bi in range(len(boards)):
            model.Add(sum(v for (bb, _m), v in use_var.items()
                          if bb == bi) <= 1)
        for i in range(len(parts)):
            model.Add(sum(v for (_b, mask), v in use_var.items()
                          if mask & (1 << i)) == 1)

        result = {
            "chosen": [],
            "elapsed": time.perf_counter() - start,
            "enum_complete": complete,
            "objective": None,
            "pattern_count": len(use_var),
        }
        if not use_var:
            result["status"] = "infeasible" if complete else "unknown"
            return result

        model.Minimize(sum(
            v * (boards[b].width * boards[b].height * ARENA
                 + patterns[(b, mask)].cuts)
            for (b, mask), v in use_var.items()
        ))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.05, budget)
        solver.parameters.num_search_workers = 2
        st = solver.Solve(model)

        has_solution = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        if has_solution:
            for (bi, mask), v in use_var.items():
                if solver.Value(v) == 1:
                    result["chosen"].append(
                        ChosenPattern(bi, mask, patterns[(bi, mask)]))
            result["chosen"].sort(key=lambda c: c.board)
            result["objective"] = int(round(solver.ObjectiveValue()))
            result["status"] = ("optimal" if complete
                                and st == cp_model.OPTIMAL else "feasible")
            result["cp_optimal"] = st == cp_model.OPTIMAL
        elif st == cp_model.INFEASIBLE:
            result["status"] = "infeasible" if complete else "unknown"
            result["cp_optimal"] = False
        else:
            result["status"] = "unknown"
            result["cp_optimal"] = False
        return result

    # 阶段 1：只枚举整板全掩码，尽快拿到可行解（给最多 60% 时限）
    phase1_budget = time_limit * 0.6
    enumerator = _Enumerator(boards, parts, kerf, start + phase1_budget)
    patterns1, complete1 = enumerator.enumerate_full_only()

    result = run_cpsat(patterns1, complete1,
                       max(0.2, time_limit - (time.perf_counter() - start)))

    # 单件零件时不存在非全掩码子集，阶段 1 的模式集合即完备
    # （CP-SAT 仍可在多块板的全掩码模式间选板）。
    early_done = result["status"] in ("optimal", "infeasible") \
        and enumerator.n == 1
    remaining_time = time_limit - (time.perf_counter() - start)
    if early_done or remaining_time < 0.5:
        result["elapsed"] = time.perf_counter() - start
        return result

    # 阶段 2：在已积累 memo 基础上补枚举其余子集
    enumerator.deadline = start + max(
        phase1_budget, time_limit - 0.6)
    patterns2, complete2 = enumerator.enumerate_remaining()
    patterns_all = {**patterns1, **patterns2}
    complete = complete1 and complete2

    result2 = run_cpsat(
        patterns_all, complete,
        max(0.2, time_limit - (time.perf_counter() - start)))

    # 状态合并：阶段 2 结论优先；若阶段 2 未得解而阶段 1 有可行解，
    # 保留阶段 1 的可行方案（绝不能因阶段 2 超时而误报无解）。
    if result2["chosen"] or result2["status"] == "infeasible":
        final = result2
    else:
        final = result
    final["enum_complete"] = complete
    final["elapsed"] = time.perf_counter() - start
    return final
