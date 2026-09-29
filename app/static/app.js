/* 板材顺序锯切规划台 — 前端逻辑（原生 JS，无框架） */
"use strict";

const state = {
  boards: [],
  parts: [],
  result: null,
  lastRequest: null,
  step: 0,        // 已展示到第几刀（全局刀号）
  savedPlanId: null,
};

const MAX_BOARDS = 3;
const MAX_PARTS = 8;

// ---------- 工具 ----------
function $(sel) { return document.querySelector(sel); }
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}
function intVal(input, min) {
  const v = parseInt(input.value, 10);
  return Number.isFinite(v) && v >= min ? v : null;
}
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { t.hidden = true; }, 2600);
}

// ---------- 输入表单 ----------
function defaultBoard() {
  return { name: "", width: 1200, height: 800,
           defects: [] };
}
function defaultPart() {
  return { name: "", width: 400, height: 300, rotatable: false };
}

function renderInputs() {
  renderBoards();
  renderParts();
}

function renderBoards() {
  const wrap = $("#boardList");
  wrap.innerHTML = "";
  state.boards.forEach((b, bi) => {
    const card = el("div", { class: "card" });
    const head = el("div", { class: "card-head" },
      el("span", { class: "card-title" }, `板材 ${bi + 1}`),
      textInput(b.name, "名称（可空）", (v) => b.name = v, "name-input"),
      field("宽", b.width, (v) => b.width = v),
      field("高", b.height, (v) => b.height = v),
      el("button", {
        class: "secondary", onClick: () => {
          b.defects.push({ x: 0, y: 0, width: 100, height: 100 });
          renderBoards();
        }
      }, "＋ 缺陷"),
      state.boards.length > 1 && el("button", {
        class: "danger", onClick: () => {
          state.boards.splice(bi, 1); renderBoards();
        }
      }, "删除"),
    );
    card.appendChild(head);

    if (b.defects.length) {
      const dwrap = el("div", { class: "defects-wrap" });
      b.defects.forEach((d, di) => {
        const row = el("div", { class: "defect-row" },
          el("span", {}, `缺陷 ${di + 1}：`),
          miniField("左上x", d.x, (v) => d.x = v),
          miniField("左上y", d.y, (v) => d.y = v),
          miniField("宽", d.width, (v) => d.width = v),
          miniField("高", d.height, (v) => d.height = v),
          el("button", {
            class: "danger", onClick: () => {
              b.defects.splice(di, 1); renderBoards();
            }
          }, "移除"),
        );
        dwrap.appendChild(row);
      });
      card.appendChild(dwrap);
    }
    wrap.appendChild(card);
  });
  $("#addBoard").disabled = state.boards.length >= MAX_BOARDS;
}

function renderParts() {
  const wrap = $("#partList");
  wrap.innerHTML = "";
  state.parts.forEach((p, pi) => {
    const card = el("div", { class: "card" });
    card.appendChild(el("div", { class: "card-head" },
      el("span", { class: "card-title" }, `零件 ${pi + 1}`),
      textInput(p.name, "名称（可空）", (v) => p.name = v, "name-input"),
      field("宽", p.width, (v) => p.width = v),
      field("高", p.height, (v) => p.height = v),
      el("label", { class: "checkbox-label" },
        el("input", {
          type: "checkbox",
          ...(p.rotatable ? { checked: true } : {}),
          onChange: (e) => p.rotatable = e.target.checked,
        }), "可旋转 90°"),
      state.parts.length > 1 && el("button", {
        class: "danger", onClick: () => {
          state.parts.splice(pi, 1); renderParts();
        }
      }, "删除"),
    ));
    wrap.appendChild(card);
  });
  $("#addPart").disabled = state.parts.length >= MAX_PARTS;
}

function field(labelText, value, onChange) {
  return el("label", {}, `${labelText} `,
    el("input", {
      type: "number", min: "1", step: "1", value: String(value),
      onChange: (e) => {
        const v = intVal(e.target, 1);
        if (v != null) onChange(v);
        else e.target.value = value;
      },
    }), " mm");
}
function miniField(labelText, value, onChange) {
  return el("label", {}, `${labelText} `,
    el("input", {
      type: "number", min: "0", step: "1", value: String(value),
      style: "width:70px",
      onChange: (e) => {
        const v = parseInt(e.target.value, 10);
        if (Number.isFinite(v) && v >= 0) onChange(v);
        else e.target.value = value;
      },
    }));
}
function textInput(value, placeholder, onChange, cls) {
  return el("input", {
    type: "text", class: cls || "name-input",
    value, placeholder,
    onChange: (e) => onChange(e.target.value),
  });
}

// ---------- 收集并校验 ----------
function collectRequest() {
  const kerf = intVal($("#kerf"), 0);
  const tlim = parseFloat($("#timeLimit").value);
  if (kerf == null) throw new Error("锯缝宽度须为非负整数");
  if (!(tlim >= 0.1 && tlim <= 120)) throw new Error("搜索时限须在 0.1~120 秒");
  if (!state.boards.length) throw new Error("至少录入一张板材");
  if (!state.parts.length) throw new Error("至少录入一件零件");

  for (let bi = 0; bi < state.boards.length; bi++) {
    const b = state.boards[bi];
    if (!(b.width >= 1 && b.height >= 1))
      throw new Error(`板材 ${bi + 1} 宽高须为正整数`);
    b.defects.forEach((d, di) => {
      if (!(d.x >= 0 && d.y >= 0 && d.width >= 1 && d.height >= 1))
        throw new Error(`板材 ${bi + 1} 缺陷 ${di + 1} 参数不合法`);
      if (d.x + d.width > b.width || d.y + d.height > b.height)
        throw new Error(`板材 ${bi + 1} 缺陷 ${di + 1} 超出板材范围`);
    });
  }
  state.parts.forEach((p, pi) => {
    if (!(p.width >= 1 && p.height >= 1))
      throw new Error(`零件 ${pi + 1} 宽高须为正整数`);
  });

  return {
    kerf,
    time_limit_seconds: tlim,
    boards: state.boards.map((b) => ({
      name: b.name, width: b.width, height: b.height,
      defects: b.defects.map((d) => ({ ...d })),
    })),
    parts: state.parts.map((p) => ({
      name: p.name, width: p.width, height: p.height,
      rotatable: p.rotatable,
    })),
  };
}

// ---------- 求解 ----------
async function solve() {
  let req;
  try { req = collectRequest(); }
  catch (e) { toast(e.message, "error"); return; }

  const btn = $("#solveBtn");
  btn.disabled = true;
  $("#solveStatus").textContent = "求解中，请稍候…";
  $("#solveStatus").className = "status-line";
  state.result = null;
  state.savedPlanId = null;

  try {
    const resp = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!resp.ok) {
      const txt = await resp.text();
      let msg = txt;
      try { msg = JSON.parse(txt).detail; } catch (_) {}
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    const data = await resp.json();
    state.result = data;
    state.lastRequest = req;
    state.step = data.total_cuts;
    renderResult();
    $("#solveStatus").textContent = data.status_text;
    $("#solveStatus").className = "status-line status-" + data.status;
  } catch (e) {
    $("#resultPanel").hidden = true;
    $("#solveStatus").textContent = "求解失败：" + e.message;
    $("#solveStatus").className = "status-line status-infeasible";
    toast("求解失败：" + e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// ---------- 结果展示 ----------
function renderResult() {
  const r = state.result;
  $("#resultPanel").hidden = false;
  const hasPlan = r.status === "optimal" || r.status === "feasible";
  $("#saveBtn").disabled = !hasPlan;
  $("#downloadBtn").disabled = !hasPlan;
  $("#stepControls").hidden = !hasPlan || r.total_cuts === 0;

  const summary = $("#resultSummary");
  summary.innerHTML = "";
  const grid = el("div", { class: "summary-grid" });
  grid.appendChild(stat("求解状态", statusLabel(r.status), "status-" + r.status));
  grid.appendChild(stat("使用板材", hasPlan
    ? r.used_board_indices.map((i) => i + 1).join("、") || "—" : "—"));
  grid.appendChild(stat("用板总面积", hasPlan ? `${r.used_area.toLocaleString()} mm²` : "—"));
  grid.appendChild(stat("切割次数", hasPlan ? `${r.total_cuts} 刀` : "—"));
  grid.appendChild(stat("求解耗时", `${r.elapsed_seconds.toFixed(2)} s`));
  grid.appendChild(stat("锯缝宽度", `${r.kerf} mm`));
  summary.appendChild(grid);
  summary.appendChild(el("p", { class: "status-line status-" + r.status }, r.status_text));
  if (r.enum_complete === false && hasPlan)
    summary.appendChild(el("p", { class: "status-line" },
      "注：模式枚举在时限内未完成，当前方案可行但未证明最优。"));

  if (!hasPlan) {
    $("#boardsView").innerHTML = "";
    $("#cutTableWrap").innerHTML = "";
    $("#placementTableWrap").innerHTML = "";
    return;
  }
  renderStepControls();
  renderBoardsView();
  renderCutTable();
  renderPlacementTable();
}

function stat(k, v, cls) {
  return el("div", { class: "stat" },
    el("div", { class: "k" }, k),
    el("div", { class: "v " + (cls || "") }, String(v)));
}
function statusLabel(s) {
  return { optimal: "最优", feasible: "可行（未证最优）",
           unknown: "超时未得方案", infeasible: "无解" }[s] || s;
}

// ---------- 逐步切分可视化 ----------
function renderStepControls() {
  const total = state.result.total_cuts;
  $("#stepLabel").textContent = total === 0
    ? "无需切割（成品即板材）"
    : `第 ${Math.min(state.step, total)} / ${total} 刀`;
  $("#stepPrev").disabled = state.step <= 0;
  $("#stepNext").disabled = state.step >= total;
}

function boardLabel(b, i) {
  return (b.name && b.name.trim()) ? b.name : `板材 ${i + 1}`;
}
function partLabel(p, i) {
  return (p.name && p.name.trim()) ? p.name : `零件 ${i + 1}`;
}

function renderBoardsView() {
  const r = state.result;
  const wrap = $("#boardsView");
  wrap.innerHTML = "";
  const used = new Set(r.used_board_indices);
  const legend = el("div", { class: "legend" },
    el("span", {}, el("i", { style: "background:#d8b48c" }), "缺陷"),
    el("span", {}, el("i", { style: "background:#9fd49a" }), "成品"),
    el("span", {}, el("i", { style: "background:#dce8f5" }), "待切"),
    el("span", {}, el("i", { style: "background:#e6e8eb" }), "废料"),
    el("span", {}, el("i", { style: "background:#333;height:5px;margin-top:4px" }), "锯缝"),
  );
  wrap.appendChild(legend);

  r.boards.forEach((b, bi) => {
    const fig = el("div", { class: "board-figure" });
    const inUse = used.has(bi);
    fig.appendChild(el("h4", {},
      `${boardLabel(b, bi)}（${b.width}×${b.height} mm）` +
      (inUse ? "" : " — 未使用")));
    const svgWrap = el("div", { class: "viz-wrap" });
    svgWrap.appendChild(buildBoardSvg(b, bi, inUse));
    fig.appendChild(svgWrap);
    wrap.appendChild(fig);
  });
}

function buildBoardSvg(board, bi, inUse) {
  const r = state.result;
  const maxW = 1100;
  const scale = Math.min(2.2, maxW / board.width);
  const W = board.width * scale;
  const H = board.height * scale;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("width", Math.ceil(W) + 2);
  svg.setAttribute("height", Math.ceil(H) + 2);
  svg.setAttribute("viewBox", `0 0 ${board.width} ${board.height}`);
  svg.classList.add("viz-svg");

  function rect(x, y, w, h, fill, extra = {}) {
    const node = document.createElementNS(svgNS, "rect");
    node.setAttribute("x", x); node.setAttribute("y", y);
    node.setAttribute("width", Math.max(0, w));
    node.setAttribute("height", Math.max(0, h));
    node.setAttribute("fill", fill);
    node.setAttribute("stroke", extra.stroke || "#555");
    node.setAttribute("stroke-width", extra.sw ?? 1);
    if (extra.dash) node.setAttribute("stroke-dasharray", String(extra.dash));
    if (extra.opacity != null) node.setAttribute("opacity", String(extra.opacity));
    return node;
  }
  function text(x, y, s, size, anchor = "middle", fill = "#202830", weight = "") {
    const node = document.createElementNS(svgNS, "text");
    node.setAttribute("x", x); node.setAttribute("y", y);
    node.setAttribute("font-size", size);
    node.setAttribute("text-anchor", anchor);
    node.setAttribute("fill", fill);
    if (weight) node.setAttribute("font-weight", weight);
    node.textContent = s;
    return node;
  }

  // 板材底
  svg.appendChild(rect(0, 0, board.width, board.height,
    inUse ? "#fdfdfb" : "#f2f3f5", { stroke: "#333", sw: 2 }));

  // 缺陷
  for (const d of board.defects || []) {
    const g = document.createElementNS(svgNS, "g");
    g.appendChild(rect(d.x, d.y, d.width, d.height, "#d8b48c",
      { stroke: "#8a5a2b", sw: 1 }));
    const fs = Math.min(20, Math.min(board.width, board.height) * 0.045);
    g.appendChild(text(d.x + d.width / 2, d.y + d.height / 2 + fs * 0.35,
      "缺陷", fs, "middle", "#5c3b17"));
    svg.appendChild(g);
  }

  if (!inUse) {
    const fs = Math.min(34, Math.min(board.width, board.height) * 0.07);
    svg.appendChild(text(board.width / 2, board.height / 2,
      "本张板材未使用", fs));
    return svg;
  }

  const tree = r.trees[r.used_board_indices.indexOf(bi)];
  const showWaste = $("#showWaste").checked;
  const fs = Math.min(26, Math.min(board.width, board.height) * 0.05);
  drawTree(tree);
  drawCuts(tree);

  function drawPending(node) {
    // 尚未切到的子矩形：整体作为“待切料”淡蓝区域
    svg.appendChild(rect(node.x, node.y, node.width, node.height,
      "#dce8f5", { stroke: "#7f9bbc", sw: 1, dash: 6, opacity: 0.9 }));
    svg.appendChild(text(node.x + node.width / 2,
      node.y + node.height / 2 + fs * 0.3, "待切", fs * 0.8,
      "middle", "#5a7390"));
  }

  function drawTree(node) {
    if (node.kind === "cut") {
      if (node.cut_index > state.step) {
        drawPending(node);  // 这一刀还没下，整块显示待切
        return;
      }
      if (node.children) {
        drawTree(node.children[0]);
        drawTree(node.children[1]);
      }
      return;
    }
    if (node.kind === "product") {
      svg.appendChild(rect(node.x, node.y, node.width, node.height,
        "#9fd49a", { stroke: "#2e6b2a", sw: 1.5 }));
      const p = r.parts[node.part_index];
      const label = partLabel(p, node.part_index);
      const rot = node.part_rotated ? " (旋转)" : "";
      const size = Math.min(fs, node.width / (label.length + 2) * 1.9,
        node.height / 3.2);
      svg.appendChild(text(node.x + node.width / 2,
        node.y + node.height / 2 - size * 0.25,
        label, Math.max(8, size), "middle", "#1d4419", "bold"));
      svg.appendChild(text(node.x + node.width / 2,
        node.y + node.height / 2 + size * 0.95,
        `${node.width}×${node.height}${rot}`, Math.max(7, size * 0.72)));
    } else if (showWaste) {
      svg.appendChild(rect(node.x, node.y, node.width, node.height,
        "#e6e8eb", { stroke: "#aab0b8", sw: 1, dash: 5, opacity: 0.85 }));
      svg.appendChild(text(node.x + node.width / 2,
        node.y + node.height / 2 + fs * 0.3, "废料", fs * 0.7,
        "middle", "#8a9099"));
    }
  }

  function drawCuts(node) {
    if (node.kind !== "cut") return;
    if (node.cut_index > state.step) return;  // 未来的刀不画
    if (node.children) {
      drawCuts(node.children[0]);
      drawCuts(node.children[1]);
    }
    const current = node.cut_index === state.step;
    const k = Math.max(r.kerf, Math.min(board.width, board.height) * 0.004);
    let kr;
    if (node.direction === "V") {
      kr = rect(node.x + node.cut_position, node.y,
        k, node.height, current ? "#d23" : "#333",
        { stroke: current ? "#900" : "#111", sw: 0.5 });
    } else {
      kr = rect(node.x, node.y + node.cut_position,
        node.width, k, current ? "#d23" : "#333",
        { stroke: current ? "#900" : "#111", sw: 0.5 });
    }
    svg.appendChild(kr);
    // 刀号气泡
    const bx = node.direction === "V"
      ? node.x + node.cut_position
      : node.x + node.width * 0.5;
    const by = node.direction === "V"
      ? node.y + node.height * 0.12
      : node.y + node.cut_position;
    const cg = document.createElementNS(svgNS, "g");
    const cr = Math.max(10, fs * 0.7);
    const circle = document.createElementNS(svgNS, "circle");
    circle.setAttribute("cx", bx); circle.setAttribute("cy", by);
    circle.setAttribute("r", cr);
    circle.setAttribute("fill", current ? "#d23" : "#222");
    cg.appendChild(circle);
    cg.appendChild(text(bx, by + cr * 0.36, String(node.cut_index),
      cr * 1.15, "middle", "#fff", "bold"));
    svg.appendChild(cg);
  }

  return svg;
}

// ---------- 表格 ----------
function renderCutTable() {
  const r = state.result;
  const wrap = $("#cutTableWrap");
  wrap.innerHTML = "";
  if (!r.cut_sequence.length) {
    wrap.appendChild(el("p", { class: "status-line" },
      "本方案无需切割（每件成品恰好等于整张板材）。"));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    ["刀号", "板材", "方向", "当前子矩形 (x,y,w,h)", "切口位置(局部)",
     "锯缝起点 (x,y)", "源自刀号"]
      .map((h) => el("th", {}, h))))) ;
  const tb = el("tbody");
  r.cut_sequence.forEach((c) => {
    const r0 = c.rect, s = c.kerf_rect;
    const local = c.direction === "V" ? s.x - r0.x : s.y - r0.y;
    const tr = el("tr", {
      style: c.cut_no === state.step ? "background:#ffe9e9;font-weight:600" : "",
    },
      el("td", {}, String(c.cut_no)),
      el("td", {}, boardLabel(r.boards[c.board_index], c.board_index)),
      el("td", {}, c.direction === "V" ? "竖切 V" : "横切 H"),
      el("td", {}, `(${r0.x}, ${r0.y}, ${r0.width}, ${r0.height})`),
      el("td", {}, `${local} mm`),
      el("td", {}, `(${s.x}, ${s.y})`),
      el("td", {}, c.parent_cut_no == null ? "—（整板）" : `第 ${c.parent_cut_no} 刀`),
    );
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => {
      state.step = c.cut_no;
      renderStepControls();
      renderBoardsView();
      renderCutTable();
    });
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  wrap.appendChild(table);
}

function renderPlacementTable() {
  const r = state.result;
  const wrap = $("#placementTableWrap");
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {},
    ["零件编号", "名称", "规格(mm)", "板材", "位置(x,y)",
     "成品尺寸(mm)", "旋转"]
      .map((h) => el("th", {}, h))))) ;
  const tb = el("tbody");
  r.part_placements.forEach((pl) => {
    const p = r.parts[pl.part_index];
    tb.appendChild(el("tr", { class: "product-row" },
      el("td", {}, String(pl.part_no)),
      el("td", {}, partLabel(p, pl.part_index)),
      el("td", {}, `${p.width}×${p.height}`),
      el("td", {}, boardLabel(r.boards[pl.board_index], pl.board_index)),
      el("td", {}, `(${pl.x}, ${pl.y})`),
      el("td", {}, `${pl.width}×${pl.height}`),
      el("td", {}, pl.rotated ? "是 90°" : "否"),
    ));
  });
  table.appendChild(tb);
  wrap.innerHTML = "";
  wrap.appendChild(table);
}

// ---------- 保存 / 下载 ----------
async function savePlan() {
  if (!state.result) return;
  const name = prompt("为该方案命名：",
    `方案 ${new Date().toLocaleString("zh-CN")}`);
  if (name == null) return;
  try {
    const resp = await fetch("/api/plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.trim() || "未命名方案",
        request: state.lastRequest,
        response: state.result,
      }),
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      throw new Error(d.detail || "保存失败");
    }
    const data = await resp.json();
    state.savedPlanId = data.id;
    toast(`方案 #${data.id} 已保存`, "ok");
    loadPlans();
  } catch (e) {
    toast(e.message, "error");
  }
}

function downloadCurrent() {
  if (state.savedPlanId) {
    window.location.href = `/api/plans/${state.savedPlanId}/cutlist.csv`;
  } else {
    // 未保存时本地即时生成下载（编号与界面一致）
    const csv = buildCsv(state.result);
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const a = el("a", { href: URL.createObjectURL(blob),
      download: "cutlist-current.csv" });
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}

function buildCsv(r) {
  const rows = [];
  rows.push(["# 板材顺序锯切清单"]);
  rows.push(["状态", r.status_text]);
  rows.push(["锯缝宽度(mm)", r.kerf]);
  rows.push(["用板总面积(mm2)", r.used_area]);
  rows.push(["总切割次数", r.total_cuts]);
  rows.push([]);
  rows.push(["[板材]"]);
  rows.push(["板材编号", "名称", "宽(mm)", "高(mm)", "是否使用", "缺陷"]);
  r.boards.forEach((b, bi) => {
    rows.push([bi + 1, b.name || "", b.width, b.height,
      r.used_board_indices.includes(bi) ? "是" : "否",
      (b.defects || []).map((d) =>
        `(${d.x},${d.y},${d.width},${d.height})`).join(";")]);
  });
  rows.push([]);
  rows.push(["[零件]"]);
  rows.push(["零件编号", "名称", "宽(mm)", "高(mm)", "允许旋转"]);
  r.parts.forEach((p, i) =>
    rows.push([i + 1, p.name || "", p.width, p.height, p.rotatable ? "是" : "否"]));
  rows.push([]);
  rows.push(["[成品下料位置]"]);
  rows.push(["零件编号", "零件名称", "板材编号", "x", "y",
    "成品宽", "成品高", "是否旋转"]);
  r.part_placements.forEach((pl) =>
    rows.push([pl.part_no, r.parts[pl.part_index].name || "",
      pl.board_index + 1, pl.x, pl.y, pl.width, pl.height,
      pl.rotated ? "是" : "否"]));
  rows.push([]);
  rows.push(["[逐刀顺序] V=竖切 H=横切"]);
  rows.push(["刀号", "板材编号", "方向", "子矩形x", "子矩形y",
    "子矩形宽", "子矩形高", "切口位置(局部)", "锯缝起点x", "锯缝起点y",
    "源自刀号"]);
  r.cut_sequence.forEach((c) => {
    const r0 = c.rect, s = c.kerf_rect;
    const local = c.direction === "V" ? s.x - r0.x : s.y - r0.y;
    rows.push([c.cut_no, c.board_index + 1, c.direction,
      r0.x, r0.y, r0.width, r0.height, local, s.x, s.y,
      c.parent_cut_no == null ? "-" : c.parent_cut_no]);
  });
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}
function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// ---------- 已保存方案 ----------
async function loadPlans() {
  const wrap = $("#plansList");
  wrap.innerHTML = "";
  try {
    const resp = await fetch("/api/plans");
    const data = await resp.json();
    if (!data.plans.length) {
      wrap.appendChild(el("p", { class: "status-line" }, "暂无已保存方案。"));
      return;
    }
    data.plans.forEach((p) => {
      wrap.appendChild(el("div", { class: "plan-item" },
        el("span", { class: "pname" }, `#${p.id} ${p.name}`),
        el("span", { class: "status-line status-" + p.status },
          statusLabel(p.status)),
        el("span", {}, `用板 ${p.used_area.toLocaleString()} mm²`),
        el("span", {}, `${p.total_cuts} 刀`),
        el("span", { style: "color:#888" }, p.created_at),
        el("button", {
          class: "secondary", onClick: () => openPlan(p.id),
        }, "载入查看"),
        el("button", {
          class: "secondary", onClick: () => {
            window.location.href = `/api/plans/${p.id}/cutlist.csv`;
          }
        }, "下载清单"),
        el("button", {
          class: "danger", onClick: () => removePlan(p.id),
        }, "删除"),
      ));
    });
  } catch (e) {
    wrap.appendChild(el("p", { class: "status-line status-infeasible" },
      "加载失败：" + e.message));
  }
}

async function openPlan(id) {
  try {
    const resp = await fetch(`/api/plans/${id}`);
    if (!resp.ok) throw new Error("方案不存在或已删除");
    const data = await resp.json();
    const req = data.request;
    state.boards = req.boards.map((b) => ({
      name: b.name || "", width: b.width, height: b.height,
      defects: (b.defects || []).map((d) => ({ ...d })),
    }));
    state.parts = req.parts.map((p) => ({ ...p }));
    $("#kerf").value = req.kerf;
    $("#timeLimit").value = req.time_limit_seconds;
    renderInputs();
    state.result = data.response;
    state.lastRequest = req;
    state.savedPlanId = id;
    state.step = data.response.total_cuts;
    renderResult();
    $("#solveStatus").textContent = `已载入保存方案 #${id}`;
    $("#solveStatus").className = "status-line status-" + data.response.status;
    window.scrollTo({ top: $("#resultPanel").offsetTop - 10,
      behavior: "smooth" });
  } catch (e) {
    toast(e.message, "error");
  }
}

async function removePlan(id) {
  if (!confirm(`确认删除方案 #${id}？`)) return;
  const resp = await fetch(`/api/plans/${id}`, { method: "DELETE" });
  if (resp.ok) { toast("已删除", "ok"); loadPlans(); }
  else toast("删除失败", "error");
}

// ---------- 示例 ----------
function loadSample() {
  state.boards = [{
    name: "大板 A", width: 1200, height: 800,
    defects: [{ x: 900, y: 100, width: 180, height: 140 }],
  }, {
    name: "备用板 B", width: 900, height: 600, defects: [],
  }];
  state.parts = [
    { name: "侧板左", width: 500, height: 350, rotatable: true },
    { name: "侧板右", width: 500, height: 350, rotatable: true },
    { name: "背板", width: 600, height: 400, rotatable: false },
    { name: "抽屉面", width: 400, height: 200, rotatable: true },
  ];
  $("#kerf").value = 3;
  $("#timeLimit").value = 10;
  renderInputs();
  toast("已载入示例数据");
}

// ---------- 初始化 ----------
$("#addBoard").addEventListener("click", () => {
  if (state.boards.length < MAX_BOARDS) {
    state.boards.push(defaultBoard());
    renderBoards();
  }
});
$("#addPart").addEventListener("click", () => {
  if (state.parts.length < MAX_PARTS) {
    state.parts.push(defaultPart());
    renderParts();
  }
});
$("#solveBtn").addEventListener("click", solve);
$("#saveBtn").addEventListener("click", savePlan);
$("#downloadBtn").addEventListener("click", downloadCurrent);
$("#sampleBtn").addEventListener("click", loadSample);
$("#stepPrev").addEventListener("click", () => {
  if (state.step > 0) state.step--;
  renderStepControls(); renderBoardsView(); renderCutTable();
});
$("#stepNext").addEventListener("click", () => {
  if (state.step < state.result.total_cuts) state.step++;
  renderStepControls(); renderBoardsView(); renderCutTable();
});
$("#stepAll").addEventListener("click", () => {
  state.step = state.result.total_cuts;
  renderStepControls(); renderBoardsView(); renderCutTable();
});
$("#showWaste").addEventListener("change", renderBoardsView);

// 初始数据
state.boards.push(defaultBoard());
state.parts.push(defaultPart());
renderInputs();
loadPlans();
