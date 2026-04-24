/* =========================================================================
   app.js — BTC Strategy 审计台(Sprint 2.2)

   Alpine.js 全局组件 `app()`。
   Sprint 2.2 改动:
     * 走真实 API /api/strategy/current + /api/strategy/stream(SSE)
     * 失败回退 /mock/strategy_current.json 并在顶部 banner 提示
     * factor_cards 新字段(tier / plain_interpretation / impact_direction / ...)
     * trade_plan 从 state.adjudicator.trade_plan 读
     * 五层 plain_reading 直接显示
     * 6 个组合因子(tier='composite')独立成一区
   ========================================================================= */

function app() {
    return {
        // ================== 状态 ==================
        state: null,
        loading: true,
        error: null,
        darkMode: false,
        nowBjt: '',
        dataSource: 'api',      // 'api' | 'mock'
        _tickTimer: null,
        _sseSource: null,

        categories: [
            { key: 'price_structure', label: '价格与结构' },
            { key: 'derivatives',     label: '衍生品' },
            { key: 'onchain',         label: '链上' },
            { key: 'liquidity',       label: '流动性与清算' },
            { key: 'macro',           label: '宏观背景' },
            { key: 'events',          label: '事件日历' },
            { key: 'risk_tags',       label: '风险标签' },
        ],

        // ================== init ==================
        async init() {
            this._initDarkMode();
            this._startClock();
            await this._loadState();
            this._connectSSE();
        },

        // ================== Dark / Light ==================
        _initDarkMode() {
            const qs = new URLSearchParams(window.location.search);
            const q = qs.get('theme');
            if (q === 'dark' || q === 'light') {
                this.darkMode = (q === 'dark');
                return;
            }
            const saved = localStorage.getItem('btc_strategy_theme');
            if (saved === 'dark' || saved === 'light') {
                this.darkMode = (saved === 'dark');
            } else {
                this.darkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
            }
        },
        toggleDark() {
            this.darkMode = !this.darkMode;
            localStorage.setItem('btc_strategy_theme', this.darkMode ? 'dark' : 'light');
        },

        // ================== BJT 时钟 ==================
        _startClock() {
            const tick = () => { this.nowBjt = this._currentBjt(); };
            tick();
            this._tickTimer = setInterval(tick, 1000);
        },
        _currentBjt() {
            const now = new Date();
            const bjt = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
            const pad = (n) => String(n).padStart(2, '0');
            return `${bjt.getFullYear()}-${pad(bjt.getMonth() + 1)}-${pad(bjt.getDate())} ` +
                   `${pad(bjt.getHours())}:${pad(bjt.getMinutes())}:${pad(bjt.getSeconds())} (BJT)`;
        },

        formatBJT(isoString) {
            if (!isoString) return '';
            const d = new Date(isoString);
            if (isNaN(d.getTime())) return isoString;
            const bjt = new Date(d.getTime() + (d.getTimezoneOffset() + 480) * 60000);
            const pad = (n) => String(n).padStart(2, '0');
            return `${bjt.getFullYear()}-${pad(bjt.getMonth() + 1)}-${pad(bjt.getDate())} ` +
                   `${pad(bjt.getHours())}:${pad(bjt.getMinutes())} (BJT)`;
        },

        // ================== 数据加载:API 优先,失败回退 MOCK ==================
        async _loadState() {
            this.loading = true;
            this.error = null;
            let apiOk = false;
            // 1. try /api/strategy/current
            try {
                const res = await fetch('/api/strategy/current', { cache: 'no-cache' });
                if (res.ok) {
                    const body = await res.json();
                    const norm = this._normalize(body);
                    if (norm) {
                        this.state = norm;
                        this.dataSource = 'api';
                        apiOk = true;
                    }
                } else if (res.status !== 404) {
                    console.warn(`[app] API returned ${res.status}`);
                }
            } catch (e) {
                console.warn('[app] API fetch failed:', e);
            }
            // 2. fallback /mock/strategy_current.json
            if (!apiOk) {
                try {
                    const res = await fetch('/mock/strategy_current.json', { cache: 'no-cache' });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    const body = await res.json();
                    this.state = body.state || body;
                    this.dataSource = 'mock';
                } catch (e) {
                    this.error = String(e.message || e);
                    console.error('[app] mock also failed:', e);
                }
            }
            this.loading = false;
        },

        /**
         * /api/strategy/current 返回 {run_id, run_timestamp_utc, run_trigger,
         *   rules_version, ai_model_actual, state: { ... }, created_at}。
         * 前端只要 body.state(12 业务块)。若 body 已经是 state 结构(没外层
         * 包裹),直接用。
         */
        _normalize(body) {
            if (!body) return null;
            // 1) API 的形态:{run_id, run_timestamp_utc, ..., state: {...}}
            if (body.state && typeof body.state === 'object'
                && !Array.isArray(body.state) && 'evidence_reports' in body.state) {
                return this._to_display_state(body.state);
            }
            // 2) mock 的形态:直接是 12 块
            return this._to_display_state(body);
        },

        /**
         * 后端真实 state 的字段名和 mock 有差异,这里做一次映射,让前端模板
         * 不用 null-guard 到底。字段:
         *   * meta.* ← state.meta(若缺,从 run_id / rules_version 等顶层字段补)
         *   * market_snapshot.* ← 真实 API 还没有;用 fallback
         *   * main_strategy.* ← 从 state_machine + observation + adjudicator 拼
         *   * evidence_summary.layer_N ← 从 evidence_reports.layer_N 派生
         *   * risks.* ← 从 L4 评估结果读
         *   * ai_verdict.* ← state.adjudicator
         *   * factor_cards ← state.factor_cards(已是新结构)
         */
        _to_display_state(raw) {
            if (!raw || typeof raw !== 'object') return raw;
            const out = JSON.parse(JSON.stringify(raw));  // 不污染原对象

            // meta(若已有就沿用)
            if (!out.meta || typeof out.meta !== 'object') out.meta = {};
            const meta = out.meta;
            meta.run_id = meta.run_id || out.run_id;
            meta.rules_version = meta.rules_version || out.rules_version;
            meta.ai_model_actual = meta.ai_model_actual || out.ai_model_actual;
            meta.strategy_flavor = meta.strategy_flavor || 'swing';
            meta.generated_at_utc = meta.generated_at_utc || out.generated_at_utc
                || out.reference_timestamp_utc;
            meta.generated_at_bjt = meta.generated_at_bjt
                || this.formatBJT(meta.generated_at_utc);
            meta.fallback_level = meta.fallback_level
                || ((out.pipeline_meta || {}).fallback_level);
            meta.cold_start = meta.cold_start || out.cold_start || {};
            meta.next_run_eta_bjt = meta.next_run_eta_bjt || null;

            // market_snapshot:真实 API 可能没有;如果没有,留空(前端 null-guard)
            if (!out.market_snapshot || typeof out.market_snapshot !== 'object') {
                out.market_snapshot = this._derive_market_snapshot(raw);
            }

            // main_strategy
            if (!out.main_strategy || typeof out.main_strategy !== 'object') {
                out.main_strategy = {};
            }
            const ms = out.main_strategy;
            const sm = raw.state_machine || {};
            const observation = raw.observation || {};
            const adj = raw.adjudicator || {};
            const l3 = (raw.evidence_reports || {}).layer_3 || {};
            ms.action_state = ms.action_state || sm.current_state || 'FLAT';
            ms.previous_action_state = ms.previous_action_state || sm.previous_state;
            ms.stable_in_state = ms.stable_in_state ?? sm.stable_in_state;
            ms.state_transitioned = ms.state_transitioned ?? !sm.stable_in_state;
            ms.lifecycle_phase = ms.lifecycle_phase || (
                sm.current_state === 'FLAT' ? '待启动' : (sm.current_state || '—')
            );
            ms.opportunity_grade = ms.opportunity_grade
                || adj.opportunity_grade
                || l3.opportunity_grade || l3.grade || 'none';
            ms.execution_permission = ms.execution_permission
                || l3.execution_permission || 'watch';
            ms.observation_category = ms.observation_category
                || observation.observation_category || '—';

            // data_health
            if (!out.data_health || typeof out.data_health !== 'object') {
                out.data_health = {
                    overall: 'green',
                    data_completeness_pct: null,
                    sources: {}, degraded_stages: [],
                };
            }

            // evidence_summary(layer_N)—— 若 state.evidence_summary 存在就沿用,
            // 否则从 evidence_reports 派生一份精简版给前端。
            if (!out.evidence_summary || typeof out.evidence_summary !== 'object') {
                const er = raw.evidence_reports || {};
                const built = {};
                for (const [idx, key] of [
                    [1, 'layer_1'], [2, 'layer_2'], [3, 'layer_3'],
                    [4, 'layer_4'], [5, 'layer_5'],
                ]) {
                    const layer = er[key] || {};
                    built[key] = {
                        layer_id: idx,
                        layer_name: layer.layer_name || key,
                        verdict: layer.verdict || this._layer_verdict_from(layer, idx),
                        confidence_tier: layer.confidence_tier || 'medium',
                        confidence_numeric: this._confidence_numeric(layer),
                        data_freshness: layer.data_freshness || 'green',
                        contribution: layer.contribution || 'neutral',
                        key_signals: layer.key_signals || [],
                        contradicting_signals: layer.contradicting_signals || [],
                        plain_reading: layer.plain_reading || '',
                    };
                }
                out.evidence_summary = built;
            } else {
                // 若有 evidence_summary,补 plain_reading(从 evidence_reports.layer_N 取)
                const er = raw.evidence_reports || {};
                for (const k of ['layer_1','layer_2','layer_3','layer_4','layer_5']) {
                    if (out.evidence_summary[k]) {
                        out.evidence_summary[k].plain_reading =
                            out.evidence_summary[k].plain_reading
                            || ((er[k] || {}).plain_reading) || '';
                    }
                }
            }

            // risks(从 L4 hard_invalidation_levels)
            if (!out.risks || typeof out.risks !== 'object') {
                const l4 = (raw.evidence_reports || {}).layer_4 || {};
                out.risks = {
                    hard_invalidation_levels: l4.hard_invalidation_levels || [],
                    active_risk_tags: l4.active_risk_tags || [],
                    event_windows: (raw.composite_factors || {}).event_risk
                        ? ((raw.composite_factors.event_risk.contributing_events) || [])
                            .map((e) => ({
                                event_name: e.name || e.type,
                                event_time_bjt: e.time_bjt || '',
                                hours_to: e.hours_to,
                                in_window: (e.hours_to != null && e.hours_to < 48),
                            }))
                        : [],
                    worst_case_estimate: null,
                };
            }

            // ai_verdict —— 首选 state.ai_verdict,然后 adjudicator 的字段
            if (!out.ai_verdict || typeof out.ai_verdict !== 'object') {
                out.ai_verdict = {
                    one_line_summary: adj.one_line_summary || adj.rationale || '',
                    narrative: adj.narrative || adj.rationale || '',
                    primary_drivers: adj.primary_drivers || [],
                    counter_arguments: adj.counter_arguments || [],
                    what_would_change_mind: adj.what_would_change_mind || [],
                    thesis_assessment: null,
                    holding_guidance: null,
                    transition_reason: adj.transition_reason || '',
                    confidence_breakdown: adj.confidence_breakdown || {},
                };
            }

            // delta_from_previous
            if (!out.delta_from_previous || typeof out.delta_from_previous !== 'object') {
                out.delta_from_previous = {
                    has_previous: !!sm.previous_state,
                    summary_tag: sm.stable_in_state ? '状态未变' : '状态切换',
                    notable_changes: [],
                };
            }

            // factor_cards 已经是新结构
            if (!Array.isArray(out.factor_cards)) {
                out.factor_cards = raw.factor_cards || raw.evidence_cards || [];
            }

            // extra / trade_plan(旧 mock 有顶级字段,新 API 放 adjudicator 下)
            if (!out.extra || typeof out.extra !== 'object') out.extra = {};
            if (!Array.isArray(out.extra.history_timeline_preview)) {
                out.extra.history_timeline_preview = [];
            }

            return out;
        },

        _derive_market_snapshot(raw) {
            // 真实 API 暂无 market_snapshot;先占位,下个 Sprint 从 DB 查最新 close
            return {
                btc_price_usd: null,
                btc_price_change_24h_pct: null,
                btc_price_updated_bjt: null,
            };
        },

        _confidence_numeric(layer) {
            const c = layer.confidence_numeric;
            if (typeof c === 'number') return c;
            const tier = (layer.confidence_tier || '').toLowerCase();
            return { very_low: 0.25, low: 0.4, medium: 0.6, high: 0.8, very_high: 0.9 }[tier] ?? null;
        },

        _layer_verdict_from(layer, idx) {
            if (idx === 1) {
                return (layer.regime || layer.regime_primary || '—')
                    + (layer.volatility_regime ? ' / ' + layer.volatility_regime : '');
            }
            if (idx === 2) return (layer.stance || '—') + ' / ' + (layer.phase || '—');
            if (idx === 3) return 'grade=' + (layer.opportunity_grade || layer.grade || 'none');
            if (idx === 4) return 'cap=' + (layer.position_cap ?? '—') + ' / risk=' + (layer.overall_risk_level || '—');
            if (idx === 5) return layer.macro_stance || layer.macro_environment || '—';
            return '';
        },

        // ================== SSE ==================
        _connectSSE() {
            try {
                this._sseSource = new EventSource('/api/strategy/stream');
                this._sseSource.onmessage = (evt) => {
                    if (!evt.data) return;
                    try {
                        const body = JSON.parse(evt.data);
                        if (body && (body.state || body.run_id)) {
                            this.state = this._normalize(body);
                            this.dataSource = 'api';
                        }
                    } catch (e) { /* ignore malformed frame */ }
                };
                this._sseSource.onerror = () => { /* 浏览器会自动重连 */ };
            } catch (e) {
                console.warn('[app] SSE not available:', e);
            }
        },

        // ================== 派生只读 ==================
        tp() {
            // state.adjudicator.trade_plan > state.trade_plan(mock)兼容
            return (this.state && (
                (this.state.adjudicator && this.state.adjudicator.trade_plan)
                || this.state.trade_plan
            )) || {};
        },
        compositeCards() {
            return (this.state && this.state.factor_cards || []).filter(c => c.tier === 'composite');
        },
        primaryCards() {
            return (this.state && this.state.factor_cards || []).filter(c => c.tier === 'primary');
        },
        referenceCards() {
            return (this.state && this.state.factor_cards || []).filter(c => c.tier === 'reference');
        },
        orderedLayers() {
            if (!this.state || !this.state.evidence_summary) return [];
            const es = this.state.evidence_summary;
            return [1, 2, 3, 4, 5].map(i => es['layer_' + i]).filter(Boolean);
        },

        // ================== 格式化 ==================
        formatPrice(v) {
            if (v == null) return '—';
            return '$' + Number(v).toLocaleString(undefined, {
                minimumFractionDigits: 2, maximumFractionDigits: 2,
            });
        },
        formatPct(v, showSign) {
            if (v == null) return '—';
            const s = Number(v).toFixed(2);
            return (showSign && v >= 0 ? '+' : '') + s + '%';
        },
        formatFactorValue(v) {
            if (v == null) return '—';
            if (typeof v === 'number') {
                if (Math.abs(v) >= 1000) return v.toLocaleString();
                if (Math.abs(v) >= 1) return v.toFixed(2);
                if (Math.abs(v) >= 0.01) return v.toFixed(3);
                return v.toFixed(4);
            }
            return String(v);
        },
        shortId(id) {
            if (!id) return '—';
            return String(id).slice(0, 8);
        },

        // ================== 倒计时 ==================
        get countdownLabel() {
            if (!this.state || !this.state.meta || !this.state.meta.next_run_eta_bjt) return '—';
            const m = String(this.state.meta.next_run_eta_bjt).match(
                /(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/,
            );
            if (!m) return this.state.meta.next_run_eta_bjt;
            const eta = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 8, +m[5]);
            const diff = eta - Date.now();
            if (diff <= 0) return '即将运行';
            const hours = Math.floor(diff / 3600000);
            const mins = Math.floor((diff % 3600000) / 60000);
            if (hours > 0) return `${hours}h ${mins}m 后`;
            return `${mins}m 后`;
        },

        get dataSourceLabel() {
            return this.dataSource === 'api' ? '实时 API' : 'MOCK 回退';
        },

        // ================== 颜色 / 标签映射 ==================
        stateColor(state) {
            const map = {
                'FLAT':                       'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
                'LONG_PLANNED':               'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                'LONG_OPEN':                  'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200',
                'LONG_HOLD':                  'bg-blue-200 text-blue-900 dark:bg-blue-800 dark:text-blue-100',
                'LONG_TRIM':                  'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
                'LONG_EXIT':                  'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
                'SHORT_PLANNED':              'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
                'SHORT_OPEN':                 'bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-200',
                'SHORT_HOLD':                 'bg-rose-200 text-rose-900 dark:bg-rose-800 dark:text-rose-100',
                'SHORT_TRIM':                 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                'SHORT_EXIT':                 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
                'FLIP_WATCH':                 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300',
                'PROTECTION':                 'bg-red-500 text-white dark:bg-red-700',
                'POST_PROTECTION_REASSESS':   'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300',
            };
            return map[state] || 'bg-slate-100 text-slate-700';
        },

        observationLabel(cat) {
            return {
                'disciplined':            '纪律性观望',
                'watchful':               '正常等待',
                'possibly_suppressed':    '疑似被压制',
                'cold_start_warming_up':  '冷启动升温中',
            }[cat] || cat || '—';
        },
        observationColor(cat) {
            return {
                'disciplined':            'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
                'watchful':               'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                'possibly_suppressed':    'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                'cold_start_warming_up':  'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300',
            }[cat] || 'bg-slate-100 text-slate-700';
        },
        observationBorderClass(cat) {
            return {
                'disciplined':            'border-slate-400',
                'watchful':               'border-blue-400 dark:border-blue-500',
                'possibly_suppressed':    'border-amber-500',
                'cold_start_warming_up':  'border-cyan-400 dark:border-cyan-500',
            }[cat] || 'border-slate-300';
        },
        observationExplanation(cat) {
            return {
                'disciplined':           '证据明确不利于开仓,系统正确地保持观望。',
                'watchful':              '证据有正面因素但不足以开仓,继续观察。',
                'possibly_suppressed':   '多项正面证据已存在但仍无机会,需要关注是否门槛过严。',
                'cold_start_warming_up': '系统运行不足 7 天,KPI 不累计,仓位额外折减一半。',
            }[cat] || '—';
        },

        healthColor(status) {
            return {
                'green':  'bg-emerald-500',
                'yellow': 'bg-amber-400',
                'red':    'bg-rose-500',
            }[status] || 'bg-slate-400';
        },
        freshnessColor(status) {
            return this.healthColor(status);
        },

        fallbackLabel(level) {
            if (!level) return '正常';
            return { level_1: 'L1 保守', level_2: 'L2 防御', level_3: 'L3 紧急' }[level] || level;
        },
        fallbackLabelClass(level) {
            if (!level) return 'text-emerald-600 dark:text-emerald-400';
            return {
                level_1: 'text-amber-600 dark:text-amber-400',
                level_2: 'text-orange-600 dark:text-orange-400',
                level_3: 'text-rose-600 dark:text-rose-400',
            }[level] || 'text-slate-500';
        },

        contributionLabel(c) {
            return { supportive: '支持', neutral: '中性', challenging: '质疑', blocking: '阻止' }[c] || c;
        },
        contributionClass(c) {
            return {
                supportive:  'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                neutral:     'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
                challenging: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                blocking:    'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
            }[c] || 'bg-slate-100 text-slate-600';
        },

        directionClass(d) {
            return {
                bullish: 'text-emerald-600 dark:text-emerald-400',
                bearish: 'text-rose-600 dark:text-rose-400',
                neutral: 'text-slate-700 dark:text-slate-200',
            }[d] || 'text-slate-700 dark:text-slate-200';
        },
        directionLabel(d) {
            return { bullish: '偏多', bearish: '偏空', neutral: '中性' }[d] || d || '中性';
        },

        // trade_plan 信心档
        tradePlanTierLabel(tier) {
            return { high: 'A · 高信心', medium: 'B · 中信心', low: 'C · 低信心参考' }[tier] || tier || '—';
        },
        tradePlanTierClass(tier) {
            return {
                high:   'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
                medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                low:    'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
            }[tier] || 'bg-slate-100 text-slate-600';
        },

        layerChineseName(id) {
            return ['市场状态', '方向结构', '机会执行', '风险失效', '背景事件'][id - 1] || '';
        },

        timelineNodeColor(type) {
            return {
                state_enter:     'bg-blue-500',
                position_open:   'bg-emerald-500',
                position_trim:   'bg-amber-400',
                position_exit:   'bg-slate-400',
                flip:            'bg-purple-500',
                cold_start_tick: 'bg-cyan-400',
            }[type] || 'bg-slate-400';
        },
        timelineNodeTypeLabel(type) {
            return {
                state_enter:     '状态',
                position_open:   '开仓',
                position_trim:   '减仓',
                position_exit:   '离场',
                flip:            '切换',
                cold_start_tick: '冷启动',
            }[type] || type;
        },
        timelineNodeBadgeClass(type) {
            return {
                state_enter:     'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                position_open:   'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                position_trim:   'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                position_exit:   'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400',
                flip:            'bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
                cold_start_tick: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300',
            }[type] || 'bg-slate-100 text-slate-700';
        },

        // 点击论据亮点跳到对应因子卡
        jumpToCard(cardId) {
            if (!cardId) return;
            const target = document.getElementById('card-' + cardId);
            if (!target) { console.warn('[app] jumpToCard missing', cardId); return; }
            this.$nextTick(() => {
                target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                target.classList.add('ring-2', 'ring-blue-400', 'dark:ring-cyan-400');
                setTimeout(() => target.classList.remove(
                    'ring-2', 'ring-blue-400', 'dark:ring-cyan-400',
                ), 2000);
            });
        },
    };
}
