# Sprint 1.9-A AI SDK 选型诊断

**日期:** 2026-05-01
**范围:** 调研 only(不动代码)
**目的:** 核实旧 macro_l5_adjudicator 与新 1.8 _base.py 是否 SDK 选型不一致

---

## 5 件事结论(每件 ≤ 3 行,带行号)

### 1. macro_l5_adjudicator.py 用什么 SDK

`src/ai/macro_l5_adjudicator.py:23-28` 从 `.client` import
`build_anthropic_client / extract_text / extract_model / extract_usage`;
line 150 `resp = client.messages.create(...)`(anthropic Messages API)。
→ **anthropic SDK**(经 src/ai/client.py 工厂构造)

### 2. src/ai/client.py 用什么库

`src/ai/client.py:1-15` 注释明说"Sprint 1.5c C6:**anthropic Python SDK**
统一客户端工厂。建模 §10.1/§10.2 要求 AI SDK 用 anthropic,通过 base_url
切换中转站。**.env 沿用现有 OPENAI_API_BASE / OPENAI_API_KEY 键名**(用户
要求不动 .env)";line 19-20 `from anthropic import Anthropic`。
→ **anthropic SDK**(.env 变量名是历史遗留,实际不是 openai)

### 3. 1.8 新写的 _base.py 用什么 SDK

`src/ai/agents/_base.py:25-26` `from ..client import build_anthropic_client,
effective_model, extract_text, extract_usage, extract_model`;line 99
`client = self._client_override or build_anthropic_client(...)`;line 182
`resp = client.messages.create(...)`。
→ **anthropic SDK**(同 macro_l5_adjudicator,经同一个 src/ai/client.py 工厂)

### 4. .env.example 期望什么 key + base_url

`.env.example` line 70-77:
```
OPENAI_API_BASE=https://us.novaiapi.com/v1
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=claude-sonnet-4-5-20250929
```
→ **OpenAI-COMPATIBLE proxy(novaiapi.com)实际转 anthropic 给 Claude**;
key 名"OPENAI_*"是历史命名,内部走 anthropic SDK + base_url 指 novaiapi。

### 5. 历史 ai_model_actual 真实值

```
claude-sonnet-4-5-20250929 | 11 行
claude-sonnet-4-6           | 1 行
```
→ **生产端真已成功调过 anthropic API 12 次**(都是 Claude 模型)。
说明 SDK / base_url / key 链路是通的。

---

## 核心问题回答

| 问 | 答 |
|---|---|
| 旧 macro_l5_adjudicator 用 openai 库还是 anthropic 库? | **anthropic** |
| 新 1.8 _base.py 用 openai 库还是 anthropic 库? | **anthropic** |
| 两者是不是不一致? | **完全一致**(都经 src/ai/client.py 工厂调 anthropic.Anthropic.messages.create)|

---

## 结论:**不是 SDK 选型不一致问题**

旧 + 新 AI 调用全部是:
```
anthropic.Anthropic(base_url="https://us.novaiapi.com", api_key=<KEY>).messages.create(...)
```

`.env` 中变量名"OPENAI_*"是历史命名(novaiapi 是 OpenAI-compatible proxy
但实际转给 Claude),src/ai/client.py:31-40 `normalize_base_url()` 会自动
剥掉 `/v1` 后缀避免重复。

**生产 12 次成功调用印证链路通。**如果切 BTC_USE_ORCHESTRATOR=true 后报错,
原因**不在** SDK 选型,**在以下可能**:
1. novaiapi proxy 不完整支持 anthropic 多模态 image content block
   (1.8 chart_b64 → message["content"] 含 type=image)
2. Claude 模型对 6 个 prompt 的输出结构不达预期(JSON parse 失败)
3. ContextBuilder 实测在生产 DB 上抛异常(数据形态差异)

→ **下一步建议**:Step 5.2 切 true 前先在本地用真 anthropic key 跑一次
`ContextBuilder + AIOrchestrator`,看具体哪一层 fail。
