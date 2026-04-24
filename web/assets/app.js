/* =========================================================================
   app.js — BTC Strategy 审计台(Sprint 2.3)
   单栏全宽 5 区域布局 + 讲述式详情。
   ========================================================================= */

function app() {
    return {
        // ============== 状态 ==============
        state: null,
        loading: true,
        error: null,
        darkMode: false,
        nowBjt: '',
        dataSource: 'api',
        _tickTimer: null,
        _sseSource: null,

        // 折叠状态(Region 4 每个 group 独立)
        expandedGroups: {},

        // Sprint 2.3 tuning:独立顶栏价格(每分钟刷一次)
        livePriceData: null,
        _priceTimer: null,

        // ============== 初始化 ==============
        async init() {
            this._initDarkMode();
            this._startClock();
            await this._loadState();
            this._connectSSE();
            // 顶栏 BTC 价格每分钟刷一次(零 AI 消耗,只碰 /api/market/btc-price)
            await this._refreshLivePrice();
            this._priceTimer = setInterval(() => this._refreshLivePrice(), 60000);
        },

        async _refreshLivePrice() {
            try {
                const r = await fetch('/api/market/btc-price', { cache: 'no-cache' });
                if (r.ok) this.livePriceData = await r.json();
            } catch (e) { /* 静默失败 */ }
        },
        livePrice() {
            if (this.livePriceData && this.livePriceData.price != null) {
                return this.livePriceData.price;
            }
            return this.state && this.state.market_snapshot
                ? this.state.market_snapshot.btc_price_usd : null;
        },
        livePrice24hChange() {
            if (this.livePriceData && this.livePriceData.price_24h_change_pct != null) {
                return this.livePriceData.price_24h_change_pct;
            }
            return this.state && this.state.market_snapshot
                ? this.state.market_snapshot.btc_price_change_24h_pct : null;
        },
        livePriceCapturedAt() {
            if (this.livePriceData && this.livePriceData.captured_at_bjt) {
                return this.livePriceData.captured_at_bjt;
            }
            return this.state && this.state.market_snapshot
                ? this.state.market_snapshot.btc_price_updated_bjt : null;
        },
        livePriceStale() {
            return !!(this.livePriceData && this.livePriceData.stale);
        },
        _initDarkMode() {
            const q = new URLSearchParams(window.location.search).get('theme');
            if (q === 'dark' || q === 'light') { this.darkMode = (q === 'dark'); return; }
            const saved = localStorage.getItem('btc_strategy_theme');
            if (saved === 'dark' || saved === 'light') this.darkMode = (saved === 'dark');
            else this.darkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
        },
        toggleDark() {
            this.darkMode = !this.darkMode;
            localStorage.setItem('btc_strategy_theme', this.darkMode ? 'dark' : 'light');
        },
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
        formatBJT(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            if (isNaN(d.getTime())) return iso;
            const b = new Date(d.getTime() + (d.getTimezoneOffset() + 480) * 60000);
            const pad = (n) => String(n).padStart(2, '0');
            return `${b.getFullYear()}-${pad(b.getMonth() + 1)}-${pad(b.getDate())} ` +
                   `${pad(b.getHours())}:${pad(b.getMinutes())} (BJT)`;
        },

        async _loadState() {
            this.loading = true;
            this.error = null;
            let apiOk = false;
            try {
                const r = await fetch('/api/strategy/current', { cache: 'no-cache' });
                if (r.ok) {
                    const body = await r.json();
                    const norm = this._normalize(body);
                    if (norm) {
                        this.state = norm;
                        this.dataSource = 'api';
                        apiOk = true;
                    }
                } else if (r.status !== 404) {
                    console.warn('[app] API status', r.status);
                }
            } catch (e) { console.warn('[app] API fetch failed:', e); }
            if (!apiOk) {
                try {
                    const r = await fetch('/mock/strategy_current.json', { cache: 'no-cache' });
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    const body = await r.json();
                    this.state = body.state || body;
                    this.dataSource = 'mock';
                } catch (e) {
                    this.error = String(e.message || e);
                    console.error('[app] mock fallback failed:', e);
                }
            }
            this.loading = false;
        },

        _connectSSE() {
            try {
                this._sseSource = new EventSource('/api/strategy/stream');
                this._sseSource.onmessage = (evt) => {
                    if (!evt.data) return;
                    try {
                        const body = JSON.parse(evt.data);
                        if (body && (body.state || body.run_id)) {
                            const norm = this._normalize(body);
                            if (norm) {
                                this.state = norm;
                                this.dataSource = 'api';
                            }
                        }
                    } catch (_) { /* ignore */ }
                };
            } catch (e) { console.warn('[app] SSE unavailable:', e); }
        },

        _normalize(body) {
            if (!body) return null;
            if (body.state && typeof body.state === 'object'
                && 'evidence_reports' in body.state) {
                return this._to_display_state(body.state);
            }
            return this._to_display_state(body);
        },

        _to_display_state(raw) {
            if (!raw || typeof raw !== 'object') return raw;
            const out = JSON.parse(JSON.stringify(raw));

            // meta
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

            // market_snapshot(Sprint 2.2 hotfix:后端已派生)
            if (!out.market_snapshot || typeof out.market_snapshot !== 'object') {
                out.market_snapshot = {
                    btc_price_usd: null, btc_price_change_24h_pct: null,
                    btc_price_updated_bjt: null,
                };
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
                    overall: 'green', data_completeness_pct: null,
                    sources: {}, degraded_stages: [],
                };
            }

            // evidence_summary:优先沿用,否则从 evidence_reports 派生
            if (!out.evidence_summary || typeof out.evidence_summary !== 'object') {
                const er = raw.evidence_reports || {};
                const built = {};
                for (const [idx, key] of [[1,'layer_1'],[2,'layer_2'],[3,'layer_3'],[4,'layer_4'],[5,'layer_5']]) {
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
                        // Sprint 2.3:pillars / core_question / rule_trace / downstream_hint
                        core_question: layer.core_question || '',
                        pillars: layer.pillars || [],
                        rule_trace: layer.rule_trace || null,
                        position_cap_chain: layer.position_cap_chain || null,
                        permission_chain: layer.permission_chain || null,
                        macro_stance: layer.macro_stance || null,
                        completeness_warning: layer.completeness_warning || null,
                        downstream_hint: layer.downstream_hint || '',
                        health_status: layer.health_status || '—',
                    };
                }
                out.evidence_summary = built;
            } else {
                const er = raw.evidence_reports || {};
                for (const k of ['layer_1','layer_2','layer_3','layer_4','layer_5']) {
                    if (out.evidence_summary[k] && er[k]) {
                        const tgt = out.evidence_summary[k];
                        const src = er[k];
                        for (const f of ['plain_reading','core_question','pillars','rule_trace',
                                         'position_cap_chain','permission_chain','macro_stance',
                                         'completeness_warning','downstream_hint','health_status']) {
                            if (tgt[f] == null && src[f] != null) tgt[f] = src[f];
                        }
                    }
                }
            }

            // risks
            if (!out.risks || typeof out.risks !== 'object') {
                const l4 = (raw.evidence_reports || {}).layer_4 || {};
                const er = (raw.composite_factors || {}).event_risk || {};
                out.risks = {
                    hard_invalidation_levels: l4.hard_invalidation_levels || [],
                    active_risk_tags: l4.active_risk_tags || [],
                    event_windows: (er.contributing_events || []).map(e => ({
                        event_name: e.name || e.type || '—',
                        event_time_bjt: e.time_bjt || '',
                        hours_to: e.hours_to,
                        in_window: (e.hours_to != null && e.hours_to < 48),
                    })),
                    worst_case_estimate: null,
                };
            }

            // ai_verdict
            if (!out.ai_verdict || typeof out.ai_verdict !== 'object') {
                out.ai_verdict = {
                    one_line_summary: adj.one_line_summary || adj.rationale || '',
                    narrative: adj.narrative || adj.rationale || '',
                    primary_drivers: adj.primary_drivers || [],
                    counter_arguments: adj.counter_arguments || [],
                    what_would_change_mind: adj.what_would_change_mind || [],
                    thesis_assessment: null, holding_guidance: null,
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

            // factor_cards
            if (!Array.isArray(out.factor_cards)) {
                out.factor_cards = raw.factor_cards || raw.evidence_cards || [];
            }

            // extra / history
            if (!out.extra || typeof out.extra !== 'object') out.extra = {};
            if (!Array.isArray(out.extra.history_timeline_preview)) {
                out.extra.history_timeline_preview = [];
            }
            return out;
        },

        _confidence_numeric(layer) {
            const c = layer.confidence_numeric;
            if (typeof c === 'number') return c;
            const tier = (layer.confidence_tier || '').toLowerCase();
            return { very_low: 0.25, low: 0.4, medium: 0.6, high: 0.8, very_high: 0.9 }[tier] ?? null;
        },
        _layer_verdict_from(layer, idx) {
            if (idx === 1) return (layer.regime || layer.regime_primary || '—')
                + (layer.volatility_regime ? ' / ' + layer.volatility_regime : '');
            if (idx === 2) return (layer.stance || '—') + ' / ' + (layer.phase || '—');
            if (idx === 3) return 'grade=' + (layer.opportunity_grade || layer.grade || 'none');
            if (idx === 4) return 'cap=' + (layer.position_cap ?? '—') + ' / risk=' + (layer.overall_risk_level || '—');
            if (idx === 5) return layer.macro_stance || layer.macro_environment || '—';
            return '';
        },

        // ============== 派生 ==============
        tp() {
            // adjudicator.trade_plan 优先,否则回退 state.trade_plan(mock)
            return (this.state && (
                (this.state.adjudicator && this.state.adjudicator.trade_plan)
                || this.state.trade_plan
            )) || {};
        },
        strategyDirection() {
            const tp = this.tp();
            if (tp && tp.direction) return tp.direction;
            const adj = this.state && this.state.adjudicator || {};
            return adj.direction || 'none';
        },
        orderedLayers() {
            if (!this.state || !this.state.evidence_summary) return [];
            const es = this.state.evidence_summary;
            return [1, 2, 3, 4, 5].map(i => es['layer_' + i]).filter(Boolean);
        },
        compositeCards() {
            // Sprint 2.3 tuning:按对策略建议的影响程度重排
            const all = (this.state && this.state.factor_cards || [])
                .filter(c => c.tier === 'composite');
            const order = [
                'cycle_position',    // 决定动态门槛 + stance
                'truth_trend',       // L1 regime 主导
                'band_position',     // L2 phase 决定
                'crowding',          // L4 position_cap 主要乘数
                'macro_headwind',    // L5 → L4 乘数
                'event_risk',        // L4 事件乘数
            ];
            const idxOf = (c) => {
                // card_id 形如 composite_cycle_position_20260424
                const m = (c.card_id || '').match(/^composite_([a-z_]+)_\d{8}$/);
                const key = m ? m[1] : '';
                const i = order.indexOf(key);
                return i === -1 ? 99 : i;
            };
            return [...all].sort((a, b) => idxOf(a) - idxOf(b));
        },
        // 6 composite 因子 composition 等字段目前在 composite_factors[key] 上
        _composite_raw(card_id) {
            if (!this.state) return null;
            const key = (card_id || '').replace(/^composite_/, '').replace(/_\d{8}$/, '');
            return (this.state.composite_factors || {})[key] || null;
        },
        compositeComposition(card_id) {
            const r = this._composite_raw(card_id);
            return r && r.composition || [];
        },
        compositeRule(card_id) {
            const r = this._composite_raw(card_id);
            return r && r.rule_description || '';
        },
        compositeInterpretation(card_id) {
            const r = this._composite_raw(card_id);
            return r && r.value_interpretation || '';
        },
        compositeAffects(card_id) {
            const r = this._composite_raw(card_id);
            return r && r.affects_layer || '';
        },

        // 区域 4 分组(Sprint 2.3 tuning:顺序改为价格→衍生→链上→宏观→事件)
        factorGroups() {
            const cards = ((this.state && this.state.factor_cards) || [])
                .filter(c => c.tier !== 'composite');
            const specs = [
                { key: 'price_technical',label: '价格技术',  icon: '🕯️', source: 'Binance klines' },
                { key: 'derivatives',    label: '衍生品',    icon: '📈', source: 'CoinGlass / Binance' },
                { key: 'onchain',        label: '链上数据',  icon: '⛓️', source: 'Glassnode' },
                { key: 'macro',          label: '宏观',      icon: '🌍', source: 'Yahoo / FRED' },
                { key: 'events',         label: '事件日历',  icon: '📅', source: 'Manual calendar' },
            ];
            return specs.map(s => {
                const group = cards.filter(c => c.group === s.key);
                const primary = group.filter(c => c.is_primary);
                const secondary = group.filter(c => !c.is_primary);
                return { ...s, primary, secondary };
            }).filter(g => g.primary.length + g.secondary.length > 0);
        },
        toggleGroup(key) {
            this.expandedGroups = {
                ...this.expandedGroups,
                [key]: !this.expandedGroups[key],
            };
        },

        // 风险提示
        hardInvalidationLevels() {
            return (this.state && this.state.risks
                    && this.state.risks.hard_invalidation_levels) || [];
        },
        activeRiskTags() {
            return (this.state && this.state.risks && this.state.risks.active_risk_tags) || [];
        },
        eventWindows() {
            return (this.state && this.state.risks && this.state.risks.event_windows) || [];
        },

        // 历史
        historyTimeline() {
            return (this.state && this.state.extra
                    && this.state.extra.history_timeline_preview) || [];
        },

        // primary_drivers / counter_arguments / what_would_change_mind 兜底
        primaryDriversDisplay() {
            const raw = (this.state && this.state.ai_verdict
                         && this.state.ai_verdict.primary_drivers) || [];
            if (raw.length > 0) return raw;
            // 兜底:基于 L3 rule_trace 生成"为什么是这个档"的 drivers
            const l3 = (this.state && this.state.evidence_summary
                        && this.state.evidence_summary.layer_3) || {};
            const rt = l3.rule_trace;
            if (rt && rt.matched_rule) {
                return [{ text: rt.matched_rule, evidence_ref: null }];
            }
            return [{ text: '规则兜底:证据尚未达到 AI 裁决调用门槛', evidence_ref: null }];
        },
        counterArgumentsDisplay() {
            const raw = (this.state && this.state.ai_verdict
                         && this.state.ai_verdict.counter_arguments) || [];
            if (raw.length > 0) return raw;
            return [{ text: '规则兜底:未列出具体反方,证据冲突程度低' }];
        },
        whatWouldChangeMindDisplay() {
            const raw = (this.state && this.state.ai_verdict
                         && this.state.ai_verdict.what_would_change_mind) || [];
            if (raw.length >= 3) return raw;
            // 兜底:从 L3 upgrade_conditions 补
            const l3 = (this.state && this.state.evidence_summary
                        && this.state.evidence_summary.layer_3) || {};
            const rt = l3.rule_trace;
            const upgrades = rt && rt.upgrade_conditions || [];
            const merged = [...raw, ...upgrades];
            if (merged.length >= 3) return merged.slice(0, 5);
            // 再兜底 3 条通用
            const generic = [
                '稳态证据连续 3 次运行一致',
                'L1 regime 切换稳定(非 transition / chaos)',
                'L2 stance_confidence 达到动态门槛',
            ];
            return [...merged, ...generic].slice(0, 5);
        },

        // 策略说明兜底
        strategyFallbackNarrative() {
            const adj = (this.state && this.state.adjudicator) || {};
            if (adj.rationale) return adj.rationale;
            const grade = (this.state && this.state.main_strategy
                           && this.state.main_strategy.opportunity_grade) || 'none';
            if (grade === 'none') {
                return '当前无符合 A/B/C 门槛的机会,系统按纪律保持观望。下方"五层证据链"详细说明每层如何判定,"什么会改变判断"列出升档所需条件。';
            }
            return '基于五层证据链和规则判档,当前机会等级为 ' + grade + '。详见下方分析过程。';
        },

        // stop_loss basis 展示
        stopLossBasis() {
            const his = this.hardInvalidationLevels();
            if (!his.length) return null;
            const p = this.tp().stop_loss;
            if (p == null) return null;
            const match = his.find(h => Math.abs((h.price || 0) - p) < 0.5);
            return match ? (match.basis + ' · ' + (match.confirmation_timeframe || '4H')) : null;
        },

        // position_cap 说明
        positionCapExplain() {
            const tier = this.tp().confidence_tier;
            const mul = { high: '1.0', medium: '0.7', low: '0.4' }[tier];
            if (!mul) return '';
            return `${tier} 档 × L4 合成 position_cap × ${mul}`;
        },

        // ============== 格式化 ==============
        formatPrice(v) {
            if (v == null) return '—';
            return '$' + Number(v).toLocaleString(undefined,
                { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
            if (typeof v === 'boolean') return v ? '是' : '否';
            if (Array.isArray(v)) return v.length > 0 ? `[${v.length}]` : '[]';
            if (typeof v === 'object') return '...';
            return String(v);
        },
        shortId(id) { return id ? String(id).slice(0, 8) : '—'; },

        get countdownLabel() {
            if (!this.state || !this.state.meta || !this.state.meta.next_run_eta_bjt) return '—';
            const m = String(this.state.meta.next_run_eta_bjt).match(
                /(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/);
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

        // L4 chain 文本化
        positionCapChainText(chain) {
            if (!chain || typeof chain !== 'object') return '';
            const base = chain.base != null ? `${chain.base}%` : '70%';
            const risk = chain.l4_risk_multiplier != null ? `× ${chain.l4_risk_multiplier}` : '';
            const crowd = chain.l4_crowding_multiplier != null ? `× ${chain.l4_crowding_multiplier}` : '';
            const macro = chain.l5_macro_headwind_multiplier != null ? `× ${chain.l5_macro_headwind_multiplier}` : '';
            const event = chain.l4_event_risk_multiplier != null ? `× ${chain.l4_event_risk_multiplier}` : '';
            const final = chain.final != null ? `${chain.final}%` : '—';
            const floor = chain.hard_floor_applied_to_final ? ' · hard_floor 15% 已抬升' : '';
            return `基础 ${base} ${risk} (L4 risk) ${crowd} (crowding) ${macro} (macro) ${event} (event) → ${final}${floor}`;
        },
        permissionChainText(chain) {
            if (!chain || typeof chain !== 'object') return '';
            const sug = chain.suggestions || {};
            const merged = chain.merged_before_buffer || '—';
            const final_ = chain.final_permission || '—';
            const buffer = chain.a_grade_buffer_applied ? '(A 级缓冲已触发)'
                         : chain.override_reason ? `(例外:${chain.override_reason})` : '';
            const parts = [];
            if (sug.l4_risk_level) parts.push(`L4 risk → ${sug.l4_risk_level}`);
            if (sug.l4_crowding) parts.push(`Crowding → ${sug.l4_crowding}`);
            if (sug.l4_event_risk) parts.push(`EventRisk → ${sug.l4_event_risk}`);
            if (sug.l5_macro_headwind) parts.push(`Macro → ${sug.l5_macro_headwind}`);
            return `${parts.join(' · ')} → 归并 ${merged} → 最终 ${final_} ${buffer}`;
        },

        // ============== 颜色 / 标签 ==============
        stateColor(s) {
            return {
                FLAT: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
                LONG_PLANNED: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                LONG_OPEN: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200',
                LONG_HOLD: 'bg-blue-200 text-blue-900 dark:bg-blue-800 dark:text-blue-100',
                LONG_TRIM: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
                LONG_EXIT: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
                SHORT_PLANNED: 'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
                SHORT_OPEN: 'bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-200',
                SHORT_HOLD: 'bg-rose-200 text-rose-900 dark:bg-rose-800 dark:text-rose-100',
                SHORT_TRIM: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                SHORT_EXIT: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
                FLIP_WATCH: 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300',
                PROTECTION: 'bg-red-500 text-white dark:bg-red-700',
                POST_PROTECTION_REASSESS: 'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300',
            }[s] || 'bg-slate-100 text-slate-700';
        },

        directionHeroClass(d) {
            return {
                long:   'text-emerald-600 dark:text-emerald-400',
                short:  'text-rose-600 dark:text-rose-400',
                'none': 'text-slate-600 dark:text-slate-400',
            }[d] || 'text-slate-600 dark:text-slate-400';
        },
        directionHeroLabel(d) {
            return { long: 'LONG 做多', short: 'SHORT 做空', 'none': '观望' }[d] || '观望';
        },

        gradeLabel(g) {
            return { A: '高信心', B: '中信心', C: '低信心', 'none': '无机会' }[g] || '';
        },
        permissionClass(p) {
            return {
                can_open: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
                cautious_open: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                ambush_only: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300',
                no_chase: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
                hold_only: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300',
                watch: 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
                protective: 'bg-rose-200 text-rose-900 dark:bg-rose-950 dark:text-rose-300',
            }[p] || 'bg-slate-100 text-slate-700';
        },

        observationLabel(c) {
            return {
                disciplined: '纪律性观望', watchful: '正常等待',
                possibly_suppressed: '疑似被压制', cold_start_warming_up: '冷启动升温中',
            }[c] || c || '—';
        },
        observationColor(c) {
            return {
                disciplined: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
                watchful: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                possibly_suppressed: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                cold_start_warming_up: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300',
            }[c] || 'bg-slate-100 text-slate-700';
        },

        healthColor(s) {
            return { green: 'bg-emerald-500', yellow: 'bg-amber-400', red: 'bg-rose-500' }[s] || 'bg-slate-400';
        },
        freshnessColor(s) { return this.healthColor(s); },

        fallbackLabel(l) {
            if (!l) return '正常';
            return { level_1: 'L1 保守', level_2: 'L2 防御', level_3: 'L3 紧急' }[l] || l;
        },
        fallbackLabelClass(l) {
            if (!l) return 'text-emerald-600 dark:text-emerald-400';
            return { level_1: 'text-amber-600 dark:text-amber-400',
                     level_2: 'text-orange-600 dark:text-orange-400',
                     level_3: 'text-rose-600 dark:text-rose-400' }[l] || 'text-slate-500';
        },

        contributionLabel(c) {
            return { supportive: '支持', neutral: '中性', challenging: '质疑', blocking: '阻止' }[c] || c;
        },
        contributionClass(c) {
            return {
                supportive: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                neutral: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
                challenging: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                blocking: 'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
            }[c] || 'bg-slate-100 text-slate-600';
        },

        directionClass(d) {
            return { bullish: 'text-emerald-600 dark:text-emerald-400',
                     bearish: 'text-rose-600 dark:text-rose-400',
                     neutral: 'text-slate-700 dark:text-slate-200' }[d] || 'text-slate-700 dark:text-slate-200';
        },
        directionLabel(d) {
            return { bullish: '偏多', bearish: '偏空', neutral: '中性' }[d] || d || '中性';
        },

        tradePlanTierLabel(t) {
            return { high: 'A · 高信心', medium: 'B · 中信心', low: 'C · 低信心参考' }[t] || t;
        },
        tradePlanTierClass(t) {
            return {
                high:   'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
                medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                low:    'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
            }[t] || 'bg-slate-100 text-slate-600';
        },

        layerChineseName(id) {
            return ['市场状态', '方向结构', '机会执行', '风险失效', '背景事件'][id - 1] || '';
        },

        timelineNodeColor(t) {
            return { state_enter: 'bg-blue-500', position_open: 'bg-emerald-500',
                     position_trim: 'bg-amber-400', position_exit: 'bg-slate-400',
                     flip: 'bg-purple-500', cold_start_tick: 'bg-cyan-400' }[t] || 'bg-slate-400';
        },
        timelineNodeTypeLabel(t) {
            return { state_enter: '状态', position_open: '开仓', position_trim: '减仓',
                     position_exit: '离场', flip: '切换', cold_start_tick: '冷启动' }[t] || t;
        },
        timelineNodeBadgeClass(t) {
            return {
                state_enter: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                position_open: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                position_trim: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                position_exit: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400',
                flip: 'bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
                cold_start_tick: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300',
            }[t] || 'bg-slate-100 text-slate-700';
        },

        jumpToCard(cardId) {
            if (!cardId) return;
            const target = document.getElementById('card-' + cardId);
            if (!target) { console.warn('[app] jumpToCard missing', cardId); return; }
            this.$nextTick(() => {
                // 若 card 在折叠组里,先展开
                for (const g of this.factorGroups()) {
                    if (g.secondary.some(c => c.card_id === cardId)) {
                        this.expandedGroups = { ...this.expandedGroups, [g.key]: true };
                        break;
                    }
                }
                setTimeout(() => {
                    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    target.classList.add('ring-2', 'ring-blue-400', 'dark:ring-cyan-400');
                    setTimeout(() => target.classList.remove(
                        'ring-2', 'ring-blue-400', 'dark:ring-cyan-400'), 2000);
                }, 200);
            });
        },
    };
}
