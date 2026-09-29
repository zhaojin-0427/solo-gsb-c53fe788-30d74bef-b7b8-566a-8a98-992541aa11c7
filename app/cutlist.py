"""锯切清单导出（CSV，编号与界面完全一致）。"""
from __future__ import annotations

import csv
import io


def build_cut_list_csv(payload: dict) -> str:
    boards = payload["boards"]
    parts = payload["parts"]
    used = set(payload["used_board_indices"])
    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow(["# 板材顺序锯切清单"])
    w.writerow(["状态", payload["status_text"]])
    w.writerow(["锯缝宽度(mm)", payload["kerf"]])
    w.writerow(["用板总面积(mm²)", payload["used_area"]])
    w.writerow(["总切割次数", payload["total_cuts"]])
    w.writerow([])

    w.writerow(["[板材]"])
    w.writerow(["板材编号", "名称", "宽(mm)", "高(mm)", "是否使用",
                "缺陷数", "缺陷坐标与尺寸(x,y,w,h)"])
    for bi, b in enumerate(boards):
        defects = "; ".join(
            f"({d['x']},{d['y']},{d['width']},{d['height']})"
            for d in b.get("defects", []))
        w.writerow([
            bi + 1, b.get("name", ""), b["width"], b["height"],
            "是" if bi in used else "否",
            len(b.get("defects", [])), defects,
        ])
    w.writerow([])

    w.writerow(["[零件]"])
    w.writerow(["零件编号", "名称", "宽(mm)", "高(mm)", "允许旋转"])
    for i, p in enumerate(parts):
        w.writerow([i + 1, p.get("name", ""), p["width"], p["height"],
                    "是" if p.get("rotatable") else "否"])
    w.writerow([])

    w.writerow(["[成品下料位置]"])
    w.writerow(["零件编号", "零件名称", "板材编号", "x(mm)", "y(mm)",
                "成品宽(mm)", "成品高(mm)", "是否旋转"])
    for pl in payload["part_placements"]:
        p = parts[pl["part_index"]]
        w.writerow([
            pl["part_no"], p.get("name", ""), pl["board_index"] + 1,
            pl["x"], pl["y"], pl["width"], pl["height"],
            "是" if pl["rotated"] else "否",
        ])
    w.writerow([])

    w.writerow(["[逐刀顺序] 坐标原点为板材左上角；方向 V=竖切，H=横切；"
                "锯缝从切口位置起占 kerf 毫米"])
    w.writerow(["刀号", "板材编号", "方向", "当前子矩形x", "当前子矩形y",
                "子矩形宽", "子矩形高", "切口位置(沿走刀起点)",
                "锯缝起点x", "锯缝起点y", "上一刀号"])
    for c in payload["cut_sequence"]:
        r = c["rect"]
        s = c["kerf_rect"]
        local_pos = (s["x"] - r["x"]) if c["direction"] == "V" \
            else (s["y"] - r["y"])
        w.writerow([
            c["cut_no"], c["board_index"] + 1, c["direction"],
            r["x"], r["y"], r["width"], r["height"], local_pos,
            s["x"], s["y"],
            c["parent_cut_no"] if c["parent_cut_no"] is not None else "-",
        ])
    return buf.getvalue()
