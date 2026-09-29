"""板材顺序锯切规划台 — FastAPI 主程序。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from pathlib import Path

from .assembler import build_response_payload
from .cutlist import build_cut_list_csv
from .models import SolveRequest
from .solver import solve_plan
from . import storage

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="板材顺序锯切规划台", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"),
          name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/api/solve")
def solve(req: SolveRequest) -> dict:
    result = solve_plan(req.boards, req.parts, req.kerf,
                        req.time_limit_seconds)
    payload = build_response_payload(req, result)
    return payload


@app.get("/api/plans")
def plans_list() -> dict:
    return {"plans": storage.list_plans()}


@app.post("/api/plans")
async def plans_save(body: dict) -> dict:
    name = (body.get("name") or "").strip() or "未命名方案"
    request = body.get("request")
    response = body.get("response")
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise HTTPException(400, "缺少 request 或 response")
    if response.get("status") not in ("optimal", "feasible"):
        raise HTTPException(400, "只有已找到可行方案的结果才能保存")
    # 重新校验请求结构
    try:
        SolveRequest.model_validate(request)
    except ValidationError as exc:
        raise HTTPException(400, f"请求数据不合法：{exc.errors()}")
    plan_id = storage.save_plan(name, request, response)
    return {"id": plan_id}


@app.get("/api/plans/{plan_id}")
def plans_get(plan_id: int) -> dict:
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise HTTPException(404, "方案不存在")
    return plan


@app.delete("/api/plans/{plan_id}")
def plans_delete(plan_id: int) -> dict:
    if not storage.delete_plan(plan_id):
        raise HTTPException(404, "方案不存在")
    return {"deleted": plan_id}


@app.get("/api/plans/{plan_id}/cutlist.csv")
def plans_cutlist(plan_id: int):
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise HTTPException(404, "方案不存在")
    csv_text = build_cut_list_csv(plan["response"])
    # utf-8-sig：让 Excel 正确识别中文
    data = ("﻿" + csv_text).encode("utf-8")
    fname = f"cutlist-plan-{plan_id}.csv"
    return Response(
        content=data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{fname}"'})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
