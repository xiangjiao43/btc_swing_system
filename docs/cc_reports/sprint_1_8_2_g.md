# Sprint 1.8.2-G:删 onchain_asopr 重复因子(单一任务,极简)

## Triggers

- 1.8.2-F 调研报告确认 `onchain_asopr` 与 `onchain_asopr_primary` 都渲染同名"aSOPR"卡(同底层数据 `sopr_adjusted`),前者为 1.5 前的 legacy reference tier,后者为 1.6 升级的 primary
- 严格按用户审定的 5 行删除范围(line 1227-1231)执行
- **未 push**:遵守"PUSH 前等用户 SSH 实证才推"

## 段 1:做了什么

### 改动 1 个文件,5 行删除

| 文件 | 删除行号 | 删除内容 |
|---|---|---|
| `src/strategy/factor_card_emitter.py` | 原 1227-1231 | 1 行注释 + 4 行元组(`_ref_specs` 列表里的 onchain_asopr 项) |

具体被删的 5 行:
```python
        # Sprint 1.7:SOPR 卡已删除(噪音因子;aSOPR 已替代它在 1.6 升级 primary)。
        ("sopr_adjusted", "onchain_asopr", "aSOPR",
         "Adjusted SOPR",
         "📍 调整后的 SOPR,排除 1 小时内的交易(去噪声)。比 SOPR 更稳定。",
         "🔍 > 1 = 盈利卖出主导;= 1 = 关键支撑/阻力位;< 1 = 投降"),
```

### 自检 grep

```
$ grep -rn "onchain_asopr\b" src/ web/ tests/ config/
tests/test_sprint_1_7_factor_deletions.py:131:                and "onchain_asopr" not in line:
tests/test_sprint_1_7_factor_deletions.py:144:    assert "onchain_asopr" in src
```

**两处测试 hit 仍能通过**:
- line 131:filter 逻辑 `"onchain_asopr" not in line`(Sprint 1.7 测试用来排除 aSOPR 卡的 SOPR 卡检查)— 不依赖 onchain_asopr 实际存在,只是过滤条件,改动后仍 OK
- line 144:`assert "onchain_asopr" in src` — 字符串子串匹配:`onchain_asopr` 是 `onchain_asopr_primary` 的子串,assert 仍通过 ✅
- 整套 pytest:**980 passed, 1 skipped**

`onchain_asopr_primary` primary emitter 完整保留:
```
src/strategy/factor_card_emitter.py:1845:    val, ts = _latest(onchain.get("sopr_adjusted"))
src/strategy/factor_card_emitter.py:1847:        card_id=f"onchain_asopr_primary_{today}",
```

## 段 2:用户 SSH 验证脚本

```bash
ssh user@124.222.89.86 << 'EOF'
cd /opt/btc_swing_system
git pull origin main          # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-swing-api
sleep 3

# 1. 后端 grep 自检
echo '=== src/ 中 onchain_asopr 引用(应只剩 _primary 版)==='
grep -n "onchain_asopr" src/strategy/factor_card_emitter.py

# 2. 跑一次 pipeline + curl,看新 run 的 onchain factor_cards 数
echo
echo '=== /api/strategy/current onchain group factor count ==='
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
s = json.load(sys.stdin)['state']
fcs = s.get('factor_cards') or []
onchain = [c for c in fcs if c.get('group') == 'onchain']
asopr_cards = [c for c in onchain if 'aSOPR' in (c.get('name') or '')]
print(f'onchain group cards: {len(onchain)} (was 16, now expected 15)')
print(f'aSOPR cards: {len(asopr_cards)} (was 2, now expected 1)')
for c in asopr_cards:
    print(f'  -> card_id={c.get(\"card_id\")}, tier={c.get(\"tier\")}')
"
EOF
```

### 浏览器手测

强制刷新 http://124.222.89.86 → 滚到 region-4 "原始数据因子" → "链上数据" 组:**aSOPR 卡只剩 1 张**(原来有 2 张同名)。

## 段 3:同类风险

1. **历史 strategy_runs**(1.8.2-G 部署前已 commit 的 v12/v13 run)的 `factor_cards` 数组仍含 `onchain_asopr_<old_date>` 卡 → 历史不会回写,仅影响**新跑**。region-4 渲染按当前 run 状态,**无残留**。

2. **测试 `test_emitter_still_has_asopr_card` 的 line 144 是子串匹配**(`assert "onchain_asopr" in src`),靠 `onchain_asopr_primary_` 子串通过。1.10 如果重命名 primary(如 `onchain_asopr_v2`),这个 assert 会失败 → 1.10 改名时同步更新此测试。

3. **`sopr_adjusted` 底层数据源未删**(用户红线:不删,可能 AI 间接消费)— 当前仅 primary emitter 1 处消费(line 1845)。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 980 passed, 1 skipped |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户 SSH 实证 onchain group 16→15 + aSOPR 卡只剩 1 张再 push |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯发射器代码删除,数据库 schema 不变) |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 1 行注释 + onchain_asopr 元组 | `src/strategy/factor_card_emitter.py:1227-1231` | 1.6 升级后 `_primary` 版本已替代,legacy reference 卡为重复发射,导致 region-4 同名 aSOPR 卡出现 2 张 |

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 8.34s
```

`test_sprint_1_7_factor_deletions.py` 中两处 `onchain_asopr` 引用经验证仍正常通过(子串匹配 + filter 条件)。

## 下一步

CC 故意不 push,等用户:
1. 主动 `git push origin main` 后 SSH 服务器看
2. 实证 `/api/strategy/current` 的 onchain group:16 → 15(aSOPR 卡 2 → 1)
3. 浏览器 region-4 链上组同名重复消失
4. 用户认可 → push 6 个 commit:1.8.2-B + 1.8.2-C + 1.8.2-D + 1.8.2-D.1 + 1.8.2-E + 本 commit (1.8.2-G)
