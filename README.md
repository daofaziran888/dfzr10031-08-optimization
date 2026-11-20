# 数据分析实验与数据应用服务平台

面向指标口径管理、分析实验设计、OLAP查询、数据看板构建与数据API发布的数据应用平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metric_def` | 指标 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、维度类型 |
| 数据集管理 | `dataset` | 分析数据集 | 数据集编号、数据集名称、来源类型 |
| 分析实验 | `experiment` | 实验方案 | 方案编号、实验名称、分析数据集 |
| OLAP查询 | `query_builder` | 查询模板 | 模板编号、模板名称、查询语句 |
| 数据看板 | `dashboard` | 看板配置 | 看板编号、看板名称、包含图表 |
| 图表配置 | `chart` | 图表 | 图表编号、图表名称、图表类型 |
| 数据API发布 | `data_service` | 数据服务 | 服务编号、服务名称、输出数据集 |
| 智能告警 | `alert` | 告警规则 | 规则编号、告警名称、监控指标 |
| 分析用户组 | `user_group` | 用户组 | 组编号、组名称、组描述 |
| 数据快照 | `snapshot` | 快照记录 | 快照编号、数据集名称、快照时间 |
| 任务调度 | `scheduler` | 调度任务 | 任务编号、任务名称、调度类型 |
| 缓存管理 | `cache` | 缓存配置 | 缓存编号、缓存目标、缓存策略 |
| 分析管道 | `pipeline` | 分析节点 | 节点编号、输入数据集、分析算子 |
| 分析模型 | `model` | 模型配置 | 模型编号、模型名称、模型类型 |
| 数据集市 | `data_mart` | 集市表 | 表编号、表名称、主题域 |
| 同单连带分析 | `basket_analysis` | 购物篮/联购矩阵 | 订单编号、商品类目、订单行状态、实际件数、净件数、提升倍数 |
| 数据导出 | `export` | 导出任务 | 任务编号、导出对象、导出格式 |
| 数据审计 | `audit` | 审计记录 | 记录编号、操作类型、操作人 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 同单连带分析口径（`basket_analysis`）

面向类目经理的购物篮（market basket）同单连带分析，所有规则集中在
`backend/app/services/basket_analysis.py`，配套回归测试见
`backend/tests/test_basket_analysis.py`（`python3 tests/test_basket_analysis.py`）。

- **购物篮取数**：接口接收订单编号 + 订单行（商品类目、订单行状态、实际件数、来源类型）。
  业务键为「订单编号 + 订单行编号」，重复导入整行覆盖，不会增加含该类目的订单数。
- **净件数恢复**：退款关联原订单行，只有「已复核」退款参与扣减，
  `净件数 = 实际件数 − 已复核退款件数`；部分退款（净件数 > 0）保留在购物篮，
  净件数归零才把该行从该单移出；取消/关闭行整行无效。
- **同单去重与样本**：同一类目在同一订单多行只贡献一次；有效订单（至少剩一个有效类目）
  数为样本规模 N，矩阵同时给出各类目单独出现次数与两类目同单次数。
- **提升倍数**：`(同单次数/N) / (类目A单数/N × 类目B单数/N)`，即实际同单率相对
  独立假设期望同单率的倍数。
- **套装来源更正**：季节性套装同时写入套装类目与成分类目时，若两个成分在该单都仅由
  同一个套装展开产生，该单不计入它们的同单次数（逐格登记「剔除数」与订单明细），
  避免直接合计抬高成分之间的连带值；成分另有原始购买行时不剔除。
- **重算与回溯**：复核退款后可按更正口径重算，每次重算生成新分析版本（AFIN-xxxx），
  矩阵、单元格与有效购物篮按版本留存，可随时回溯。
- **图表与钻取**：图表配置 CHAR-0004「同单连带联购矩阵」数据来源为同单连带分析表；
  前端矩阵每格展示提升倍数、同单次数、剔除数与样本量，点击非对角格调用
  `GET /api/basket_analysis/pair` 返回联合订单及其逐类目来源，用于核对有效购物篮。
