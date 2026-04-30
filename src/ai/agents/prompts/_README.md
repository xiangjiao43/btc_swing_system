# Sprint 1.8 Prompt Drafts — User Review Required

## v1.3 AI Input 哲学(L1-L5 + 主裁通用,本目录所有 prompt 严格遵守)

1. **给视觉(K 线图等)+ 给客观数值,不给规则结论标签**
   - ✗ `ema_alignment='bullish'`(规则结论)
   - ✓ `ema_20=75320, ema_50=71420, ema_200=65890`(客观数值)+ K 线图

2. **系统做精确计算(ADX/EMA/ATR/Swing 检测),不让 AI 自己算**
   理由:AI 算递归公式偶尔出错,系统算 100% 精确。

3. **AI 做综合判断(看图 + 看数值识别市场状态),不依赖单一阈值**
   prompt 不写 "ADX≥25 = trend_up",只写 "trend_up 是真正的上升趋势(定性描述)"。

4. **fewshot 给"输入数据 + 图描述 → 输出 JSON",不给"参考信号"提示**
   不教 AI 怎么对照阈值,只给典型场景的输入输出。

> volatility_regime 是唯一例外:它本身是客观档位,可保留 atr_180d_percentile
> 阈值。但这个例外**仅限 volatility_regime**,其他字段全部按上述 4 条。

---

## 实施流程

每个 `.txt` prompt 文件都需要用户**逐字审定**后才会进入下一份:

1. CC 写一个 prompt 草稿,commit + push,让用户审
2. 用户在对话里改 prompt(或要求重写)
3. CC 按反馈改 → 重新 commit
4. 用户通过 → 进下一个 prompt

---

## Prompt 9 段结构

每个 prompt 必须包含:
1. 角色定位
2. 输入数据说明(图描述 + 客观数值字段;**禁止规则结论标签**)
3. 输出 JSON schema(严格)
4. 判定标准(定性定义,**禁止硬阈值表**;volatility_regime 例外)
5. 你必须做的
6. 你绝对不能做的(防偏见)
7. 你必须诚实承认的
8. 输出格式(严格 JSON,首字符 `{`,尾字符 `}`)
9. fewshot 示例(1-2 个真实场景,**含图描述**)

---

## 文件清单(对应 6 AI 角色)

- l1_regime.txt
- l2_direction.txt
- l3_opportunity.txt
- l4_risk.txt
- l5_macro.txt
- master_adjudicator.txt

如 prompt 文件缺失,BaseAgent.analyze() 会走 fallback 路径返回
`status='degraded_prompt_load_failed'`,系统不崩。

---

## 多模态输入(v5,Sprint 1.8)

- `ChartRenderer` 渲染 base64 PNG(`src/ai/agents/chart_renderer.py`)
- BaseAgent 自动处理 `context['chart_b64']`:有图 → multi-modal user content,
  无图 → 纯文本(向后兼容)
- 图本身**不画判断结论**(不画 trend_up 文字标签),AI 看图自己识别
