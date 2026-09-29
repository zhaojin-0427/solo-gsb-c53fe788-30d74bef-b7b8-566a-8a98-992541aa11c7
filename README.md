# 板材顺序锯切规划台

一个本地运行的 Web 应用：录入最多 **3 张矩形板材**（含板内缺陷）和最多 **8 件待切零件**，
自动搜索**使用板材总面积最小、其次切割刀数最少**的 Guillotine（贯穿式）顺序锯切方案，
并在浏览器中逐刀可视化、可保存方案、下载编号一致的锯切清单。

- **后端**：Python + FastAPI + SQLite + [OR-Tools CP-SAT](https://developers.google.com/optimization)
- **前端**：原生 HTML / CSS / JavaScript（无框架、无构建步骤）
- **求解**：自实现的带记忆化 Guillotine 模式枚举 + OR-Tools CP-SAT 跨板集合划分

---

## 一、通过 Docker Compose 一键启动（推荐）

需要本机已安装 Docker 与 Docker Compose（`docker compose` 子命令）。

```bash
cd <本项目目录>
docker compose up --build
```

首次构建会安装 Python 依赖（含 OR-Tools），完成后在浏览器打开：

> **http://localhost:8000**

停止服务：

```bash
docker compose down
```

保存的方案通过命名卷 `saw-data` 持久化到容器内 `/srv/app/data/plans.db`，
即使删除并重建容器也不会丢失。如需更换端口，修改 `docker-compose.yml` 中的
`"8000:8000"`（前者是宿主机端口）。

---

## 二、本地直接运行（不使用 Docker）

要求 Python 3.11+。

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

然后访问 **http://localhost:8000** 。SQLite 数据库文件位于 `app/data/plans.db`，
首次保存方案时自动创建。

---

## 三、使用流程

1. **录入数据**（左上面板）
   - 锯缝宽度：非负整数毫米（锯缝会实际占用相应宽度）。
   - 板材（1～3 张）：正整数宽/高；可添加若干**缺陷**，每个缺陷录入
     左上角坐标 `(x, y)` 与宽/高，坐标原点为板材左上角，缺陷必须在板材范围内。
   - 零件（1～8 件）：正整数宽/高，勾选“可旋转 90°”表示允许横竖互换摆放。
   - 可点击“载入示例”快速体验。
2. **开始规划求解**：可设置搜索时限（0.1～120 秒，默认 10 秒）。
3. **查看结果**
   - 顶部给出求解状态、使用板材、用板总面积、切割次数与耗时。
   - SVG 图中绘制板材、缺陷（棕）、成品（绿）、待切区（蓝）、废料（灰）与锯缝（深色线，当前刀红色高亮）。
   - 用“◀ 上一刀 / 下一刀 ▶ / 显示全部”按顺序逐步查看每一刀；也可直接点击下方表格中的某行跳到该刀。
4. **保存 / 下载**
   - “保存此方案”把输入与结果写入 SQLite，之后可在底部“已保存方案”中重新载入或删除。
   - “下载锯切清单 (CSV)”导出 UTF-8（带 BOM，Excel 可直接打开）清单，
     内含板材、零件、成品下料位置和**逐刀顺序**，刀号与界面上的编号完全一致。
     未保存时也可即时下载当前方案；已保存的方案可随时在方案列表中再次下载同编号清单。

---

## 四、切割模型与求解结果状态

### 几何规则

- 每一刀只能**横向（H）或纵向（V）贯穿当前子矩形**，锯缝占用给定宽度。
- 成品叶区必须与某件零件的尺寸**完全一致**（若该零件允许旋转，可为旋转后的尺寸），
  且成品区域**不得覆盖任何缺陷**；缺陷只能留在废料叶区。
- 所有零件都必须恰好产出一次；可以使用一张或多张板材，剩余板材不使用。
- 优化目标按字典序：
  1. **所用板材的总面积最小**；
  2. 在该前提下**总切割刀数最少**。

### 求解状态（务必注意区分，系统不会把“没搜完”误报成“无解”）

| 状态 | 含义 |
| --- | --- |
| `optimal` 最优 | 枚举完整且 CP-SAT 已证明全局最优（面积最小、刀数最少）。 |
| `feasible` 可行（未证最优） | **已找到可行方案**，但在时限内未能证明它最优；可加长搜索时间后重试。 |
| `unknown` 超时未得方案 | 时限内**尚未找到**可行方案；这**不代表无解**，加长时间或调整板材后可能得到方案。 |
| `infeasible` 无解 | 已**证明**在给定板材、缺陷、零件与锯缝条件下不存在可行方案。 |

内部实现采用两阶段搜索：先快速枚举“整板装全部零件”的模式并运行一次 CP-SAT，
尽早得到一个可行方案；随后在剩余时间内补枚举跨板分切所需的零件子集模式，
用于证明最优。任何阶段超时都不会丢失已经找到的可行解。

---

## 五、HTTP 接口（便于二次集成）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/solve` | 提交 `boards / parts / kerf / time_limit_seconds`，返回方案（含切割树、成品位置、逐刀顺序）。 |
| `GET` | `/api/plans` | 已保存方案列表。 |
| `POST` | `/api/plans` | 保存一次求解的请求与响应（仅可保存可行/最优结果）。 |
| `GET` | `/api/plans/{id}` | 读取某方案完整内容。 |
| `DELETE` | `/api/plans/{id}` | 删除方案。 |
| `GET` | `/api/plans/{id}/cutlist.csv` | 下载该方案的锯切清单 CSV。 |
| `GET` | `/api/health` | 健康检查。 |

`POST /api/solve` 请求示例：

```json
{
  "kerf": 3,
  "time_limit_seconds": 10,
  "boards": [
    { "name": "大板", "width": 1200, "height": 800,
      "defects": [ { "x": 900, "y": 100, "width": 180, "height": 140 } ] }
  ],
  "parts": [
    { "name": "侧板", "width": 500, "height": 350, "rotatable": true }
  ]
}
```

---

## 六、项目结构

```
.
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── app/
    ├── main.py        # FastAPI 路由（求解 / 保存 / 下载 / 静态页面）
    ├── models.py      # Pydantic 输入输出模型与校验
    ├── solver.py      # Guillotine 模式枚举 + OR-Tools CP-SAT 选模
    ├── assembler.py   # 切割树 → 绝对坐标响应、逐刀编号、成品位置
    ├── cutlist.py     # 锯切清单 CSV 生成
    ├── storage.py     # SQLite 持久化
    ├── data/          # SQLite 数据库（运行时自动创建）
    └── static/
        ├── index.html
        ├── styles.css
        └── app.js     # 录入、逐步切分可视化、保存、清单下载
```

## 七、规模与性能说明

- 受题目约束，板材 ≤ 3 张、零件 ≤ 8 件，尺寸为正整数毫米。
- 常规布局通常在亚秒到数秒内证优；带缺陷的复杂布局在时限内可能先返回
  `feasible`（已找到方案）或 `unknown`（尚未找到），均属预期行为——
  可加大“搜索时限”获得更优/更确定的结论。
