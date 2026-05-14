# 恢复 Layer B 波段策略前端布局

## 1. 任务目标

按用户要求，将网页中的「波段策略」模块恢复到截图中的完整卡片状态：

- 恢复波段策略内部小模块边框和原始布局；
- 恢复「挂单 / thesis」完整字段；
- 恢复待触发挂单完整表格列；
- 不修改任何 Layer A / Layer B 策略逻辑；
- 不运行 pipeline，不触碰真实交易。

## 2. 读取文件

- `AGENTS.md`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`

## 3. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/restore_layer_b_swing_frontend_layout.md`

## 4. 恢复内容

### 波段策略模块

- 恢复顶部 5 个摘要卡片：
  - 当前状态
  - 方向
  - 机会等级
  - 主裁动作
  - 置信度
- 恢复「账户与执行」小节标题和边框。
- 恢复虚拟账户、当前持仓、挂单 / thesis、thesis 历史时间线、交易员结论、L1-L5 + 主裁卡片边框。
- 未新增底色或额外装饰。

### 挂单 / thesis 卡片

恢复显示：

- `thesis_id`
- `阶段`
- `等待入场区`
- `失效条件`

### 待触发挂单表

恢复完整表格列：

- 类型
- 价格
- 仓位
- 距当前

并恢复 `distanceFromLive()` 前端 helper，仅用于计算页面展示里的挂单价相对现价距离。

## 5. 保持不变

- 没有修改 Layer A A1-A5 策略逻辑。
- 没有修改 Layer B L1-L5 / Master / Validator / thesis / 虚拟账户逻辑。
- 没有修改开仓、平仓、仓位、止损、止盈、反手规则。
- 没有修改真实交易接口。
- 没有运行 pipeline。

## 6. 测试命令和结果

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`133 passed`

后续还会执行：

```bash
git diff --check
```

结果：通过，无 whitespace / patch 格式问题。

## 7. 是否触碰高风险区域

否。

本轮只改网页展示和对应静态测试，没有触碰交易、AI、数据库、调度、虚拟账户或真实交易相关逻辑。

## 8. 删除清单 / 废弃清单

本轮无删除项。

原因：本轮是前端恢复操作，主要恢复此前被精简掉的展示字段和边框，没有引入替代实现。

## 9. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 10. 风险和未完成

- 本轮没有直接打开生产网页截图做像素级比对，只按用户描述和历史前端布局恢复字段、边框、表格列。
- 生产端需要用户执行 `git pull` 和服务重启后才会显示新页面。

## 11. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

然后刷新：

```text
http://124.222.89.86/
```
