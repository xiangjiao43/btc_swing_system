# BTC Strategy 前端(Sprint 2.1 骨架版)

**定位**:策略审计层,不是交易面板。建模 §9.1 要求的信息密度三档
(10 秒读结论 / 1 分钟读逻辑 / 10 分钟审证据)。

**技术栈**:HTML + Alpine.js(CDN)+ Tailwind CSS(CDN),不走 npm 构建。
对齐建模 §10.1。

## 目录

```
web/
├── index.html            单文件应用入口
├── assets/
│   ├── styles.css        自定义 CSS(Tailwind 不够的地方)
│   └── app.js            Alpine.js 组件逻辑 + BJT 时间 / 格式化工具
├── mock/
│   └── strategy_current.json   MOCK 数据(符合建模 §7 StrategyState 结构)
└── README.md             本文件
```

## 本地跑起来

```bash
uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开 <http://localhost:8000/>。

## 开发约定

* **不走 npm / bundler**:CDN 引入 Alpine / Tailwind,部署只需 FastAPI。
* **时间全部 BJT**:顶栏时钟、所有时间戳格式 `YYYY-MM-DD HH:mm (BJT)`。
  统一工具 `formatBJT(isoString)` 在 [app.js](assets/app.js)。
* **dark/light**:右上角按钮切换,默认跟随系统 `prefers-color-scheme`;
  手动选择后存 `localStorage["btc_strategy_theme"]`。
* **响应式**:`< 1024px` 单栏(手机 / 平板),`≥ 1024px` 三栏(PC)。
* **字段展示优先级**(§9.8):始终 / 默认展开 / 默认折叠 / 仅必要
  四级严格对齐建模。
* **§9.11 拉取策略**:Sprint 2.1 先读 `/mock/strategy_current.json`;
  Sprint 2.2 切到 `/api/strategy/current` + `/api/strategy/stream`(SSE)。

## Mock 数据

`mock/strategy_current.json` 是建模 §7 StrategyState 12 业务块的完整示例。
当前场景是 `FLAT + cold_start_warming_up`:

* BTC 价格 $84,312.50
* 状态 FLAT、机会 C / cautious_open
* 观察类别 `cold_start_warming_up`(冷启动第 7 / 42 轮)
* 五层证据全部产出,L4 硬失效位含 structural HL($81,200)+ ATR stop($79,800)
* 风险标签 `cold_start_warming_up` 活跃

下个 Sprint 加真实 API 后,这个文件还留着当 fixture。
