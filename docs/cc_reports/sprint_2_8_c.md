# Sprint 2.8-C — 修复 pytest 全量挂死(layer5_macro + state_builder)

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,全量 pytest 637 passed / 1 skipped / 4.2s,跑两次稳定

---

## 一、症状

`pytest tests/` 全量跑挂死在 `test_layer5_macro::test_clear_risk_on_tailwind`(60% 处);
单独跑该测试 0.5s 通过。Sprint 2.8-B 之前已存在(`git stash` 验证),与 2.8-B 无关。

---

## 二、二分定位过程

```
全量 pytest hang at test_layer5_macro 60%
 ├─ 单独跑 test_layer5_macro:PASS(0.6s)
 ├─ 切前 18 文件 + layer5:HANG → 污染源在前 18
 ├─ 切前 9 文件 + layer5:HANG → 在前 9
 ├─ 切前 5 文件 + layer5:HANG → 在前 5
 ├─ 切前 3 文件 + layer5:HANG → 在前 3
 └─ 单独 test_ai_summary_smoke + layer5:**HANG** ← 污染源 #1
```

---

## 三、根因(两处独立的 bug)

### Bug #1:layer5_macro hang

**链条**:
1. `tests/test_ai_summary_smoke.py:19` 在模块顶层 `from src import _env_loader`
2. `_env_loader` 在 import 时调 `load_dotenv()`,把真 `OPENAI_API_KEY` 灌进 `os.environ`
3. 即便 `pytest.mark.skipif(not RUN_AI_SMOKE)` 跳过测试本身,**模块 import 已经发生**
4. 整个 pytest session 持续看到 OPENAI_API_KEY 已设置
5. 后续 `Layer5Macro.compute()` 在 data_completeness ≥ 50% 时调 `_try_call_l5_ai`
6. `build_anthropic_client(timeout=45)` 看到 key → 真 HTTP 请求 → 受限网络挂死(45s × retries)

**深一层根因**:`src/data/collectors/__init__.py:16` 也有 `from src import _env_loader`。
任何 import 自 `src.data.collectors` 的测试(13 个文件)同样触发 env 污染。

### Bug #2:test_state_builder hang(同会话发现的另一个 latent bug)

**链条**:
1. Sprint 2.7-C 加了 Stage 0 pre-flight 数据就绪检查
2. 数据缺失 → `_run_pre_flight_freshness_check` 调 `time.sleep(retry_after_sec=300)` 重试一次
3. `tests/test_state_builder.py` 多个用例只 seed klines,不 seed derivatives/onchain/macro
4. → pre-flight 失败 → 真 sleep 5 分钟 → pytest 假死
5. Sprint 2.7-C 当时为 `_run_pre_flight_freshness_check` 加了 `sleep_fn` / `retry_after_sec`
   注入点,但 `StrategyStateBuilder.__init__` 没把这两个 kwarg 透出来,
   测试无法绕开 sleep

---

## 四、修复(两处都"修源头",非 monkey-patch)

### Fix #1.a — `tests/test_ai_summary_smoke.py`
把 `from src import _env_loader` 与 `from src.ai.summary import call_ai_summary`
**移到 test body 内**,只在 `RUN_AI_SMOKE=1` 真跑 smoke 时才加载 env。
模块 import 不再有副作用。

### Fix #1.b — `src/data/collectors/__init__.py`
**删除** 包级 `from src import _env_loader`。
- 生产 OK:`scripts/run_api.py:19` 与 `scripts/run_scheduler.py:20` 顶层已显式
  `from src import _env_loader`,collector 实例化前 env 已加载
- 测试 OK:导入 collector 不再副作用 load_dotenv,unit 测试不污染 env

### Fix #2 — Pre-flight retry sleep 注入

`src/pipeline/state_builder.py`:
- `StrategyStateBuilder.__init__` 加两个 kwarg:
  - `preflight_retry_after_sec: float = 300.0`(生产值不变)
  - `preflight_sleep_fn: Callable[[float], None] = time.sleep`(生产用真 sleep)
- 在调 `_run_pre_flight_freshness_check` 时透传这两个值
  (Sprint 2.7-C 早就给函数签名加了这两个参数,只是没在 builder 层暴露)

`tests/test_state_builder.py`:
- 加 `_sb(conn, **kwargs)` 工厂(行 ~38),默认注入 `preflight_sleep_fn=lambda s: None`
  + `preflight_retry_after_sec=0.0`
- 6 个 `StrategyStateBuilder(conn, ai_caller=...)` 改为 `_sb(conn, ai_caller=...)`
- 与 `ai_caller=_ai_ok()` 同范式(显式注入,非 monkey-patch)

---

## 五、修后结果

| 验证 | 结果 |
|---|---|
| `pytest tests/` 全量(第一次) | 637 passed, 1 skipped, **4.20s** |
| `pytest tests/` 全量(第二次) | 637 passed, 1 skipped, **4.44s** |
| `pytest tests/test_layer5_macro.py` 单独 | 12 passed, 0.50s |
| `pytest tests/test_state_builder.py` 单独 | 15 passed, 1.02s |
| `pytest tests/test_ai_summary_smoke + test_layer5_macro` | 12 passed, 1 skipped, 0.62s |

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `tests/test_ai_summary_smoke.py` | `_env_loader` import 移进 test body |
| `src/data/collectors/__init__.py` | 删除包级 `from src import _env_loader` |
| `src/pipeline/state_builder.py` | builder 加 `preflight_retry_after_sec` / `preflight_sleep_fn` kwargs,透传到 pre-flight |
| `tests/test_state_builder.py` | 加 `_sb` 工厂,6 个用例改用 |

---

## 七、防止类似问题再出现

### Pattern A:模块顶层 `_env_loader` import 是"隐性副作用"
- ✅ 正确做法:`_env_loader` 只在生产 entry point(`run_api.py` / `run_scheduler.py`)顶层 import
- ❌ 错误做法:在 `__init__.py` 或 test 模块顶层 import → 污染 pytest session
- 一句话规则:**"包级 import 不应该有 wall-clock / env 副作用"**

### Pattern B:生产代码里的 `time.sleep(N)` 必须有 sleep_fn 注入点
- Sprint 2.7-C 已经做对了 `_run_pre_flight_freshness_check(sleep_fn=time.sleep)`
- 但 `StrategyStateBuilder` 没把它暴露出来,导致下游测试只能 hang
- 一句话规则:**"任何 sleep_fn 注入点都必须一路透传到顶层 builder/runner"**

### 后续可加的 lint
- pre-commit / CI 加一条 `grep`:扫 `__init__.py` 和 `tests/*.py` 顶层是否有
  `_env_loader` import,违例报错(本 sprint 不实施,YAGNI)

---

## 八、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- 删了 `src/data/collectors/__init__.py:16` 的 `from src import _env_loader` —
  确认生产入口已加载 env,这个旧路径冗余
- 没有引入新的 sleep / mock 抽象,沿用 Sprint 2.7-C 已有的 `sleep_fn` 注入点

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 全量 pytest 跑两次都过 + 4.2-4.4s 区间(没有任何 hidden hang)
- 单独跑 layer5_macro / state_builder / ai_summary_smoke 都过
- "polluter + victim" 组合 `test_ai_summary_smoke + test_layer5_macro` 同会话过

### 同类风险扫描
1. **fred.py 仍读 os.getenv("FRED_API_KEY")** — 生产 OK(env 已加载);
   单测如要测真实 FRED 调用,需自己 monkeypatch.setenv,符合显式胜过隐式
2. **CoinglassCollector / GlassnodeCollector** — 用 cfg dict 取 api_key,本来就不读 env,
   不影响
3. **scripts/run_kpi_once.py / run_pipeline_once.py** — 如果它们也跳过了 `_env_loader` import,
   生产可能拿不到 key。已 grep 确认,这些工具脚本若需 env 应自行 import
4. **未来若有人重新加 `_env_loader` 到 collectors/__init__.py** — 没有 lint 兜底,
   只有 "Pattern A 规则"做文档引导;若再现可考虑加 pre-commit grep
