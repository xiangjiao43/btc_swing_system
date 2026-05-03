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

        // Sprint 1.5n/1.5o:系统自检面板数据(每 5 分钟刷一次,永久展开)
        systemHealth: null,
        _healthTimer: null,

        // Sprint 1.10-I §9.2:5 模块数据
        virtualAccount: null,           // 模块 1 — virtual_account 最新快照
        accountReturns: {               // 模块 1 — 各周期收益率
            daily_pct: null, weekly_pct: null, monthly_pct: null,
            yearly_pct: null, total_pct: null,
        },
        accountHistory: [],             // 模块 1 — 30 天 snapshots(sparkline 数据)
        activeThesis: null,             // 模块 2 — 当前 active thesis
        positionSummary: null,          // 模块 3 — 持仓摘要(从 strategy/current 复用)
        ordersPending: {                // 模块 3 — 当前 pending 挂单
            active_thesis_id: null, items: [],
        },
        _v14ModulesTimer: null,         // 5 分钟刷一次新模块数据

        // ============== 初始化 ==============
        async init() {
            this._initDarkMode();
            this._startClock();
            await this._loadState();
            this._connectSSE();
            // 顶栏 BTC 价格每分钟刷一次(零 AI 消耗,只碰 /api/market/btc-price)
            await this._refreshLivePrice();
            // Sprint 1.5k:轮询 30 秒(后端切到现货 1m 数据,1 分钟太慢)
            this._priceTimer = setInterval(() => this._refreshLivePrice(), 30000);
            // Sprint 1.5n:系统自检面板,首次拉 + 5 分钟刷新
            await this._refreshSystemHealth();
            this._healthTimer = setInterval(
                () => this._refreshSystemHealth(), 5 * 60 * 1000,
            );
            // Sprint 1.10-I:5 模块数据,首次拉 + 5 分钟刷新
            await this._refreshV14Modules();
            this._v14ModulesTimer = setInterval(
                () => this._refreshV14Modules(), 5 * 60 * 1000,
            );
        },

        // Sprint 1.10-I §9.2:刷新 5 模块数据(account / thesis / orders /
        //                    weekly_review / pending_orders 一波 fetch)
        async _refreshV14Modules() {
            const fetchJson = async (url, fallback) => {
                try {
                    const r = await fetch(url, { cache: 'no-cache' });
                    if (r.ok) return await r.json();
                } catch (e) { /* 静默 */ }
                return fallback;
            };
            const [acc, accRet, accHist, active, orders] = await Promise.all([
                fetchJson('/api/account/current', {}),
                fetchJson('/api/account/returns', {
                    daily_pct: null, weekly_pct: null, monthly_pct: null,
                    yearly_pct: null, total_pct: null,
                }),
                fetchJson('/api/account/history?days=30', { snapshots: [] }),
                fetchJson('/api/theses/active', {}),
                fetchJson('/api/orders/pending', {
                    active_thesis_id: null, items: [],
                }),
            ]);
            this.virtualAccount = (acc && acc.snapshot_id) ? acc : null;
            this.accountReturns = accRet || this.accountReturns;
            this.accountHistory = (accHist && accHist.snapshots) || [];
            this.activeThesis = (active && active.thesis_id) ? active : null;
            this.ordersPending = orders || this.ordersPending;
            // position_summary 从 strategy/current 复用(commit 3 加的字段)
            this.positionSummary = (
                this.state && this.state.position_summary
            ) || null;
        },

        // Sprint 1.10-I §9.2.1 D1=c:30 天资金曲线 sparkline(纯 SVG polyline)
        sparklinePoints(snapshots) {
            if (!snapshots || snapshots.length < 2) return '';
            const equities = snapshots.map(s => Number(s.total_equity || 0));
            const minE = Math.min(...equities);
            const maxE = Math.max(...equities);
            const range = (maxE - minE) || 1;
            const w = 300, h = 60, pad = 2;
            const xStep = (w - pad * 2) / (equities.length - 1);
            return equities.map((e, i) => {
                const x = pad + i * xStep;
                // y 反转:高 equity 在上
                const y = pad + (h - pad * 2) * (1 - (e - minE) / range);
                return `${x.toFixed(1)},${y.toFixed(1)}`;
            }).join(' ');
        },

        // Sprint 1.10-I §9.2.1:USD 格式化(简化版,不引入 Intl)
        formatUsd(v) {
            if (v == null || isNaN(v)) return '—';
            const n = Number(v);
            if (Math.abs(n) >= 1000) return '$' + n.toLocaleString(undefined, {
                maximumFractionDigits: 0,
            });
            return '$' + n.toFixed(2);
        },

        // Sprint 1.10-I §9.2.3:挂单价距当前 BTC 现价的 %(带 ± 号)
        distanceFromLive(orderPrice) {
            const live = this.livePrice();
            if (!live || !orderPrice) return '—';
            const pct = ((Number(orderPrice) - live) / live) * 100;
            return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        },

        async _refreshSystemHealth() {
            try {
                const r = await fetch('/api/system/health-detail',
                                      { cache: 'no-cache' });
                if (r.ok) this.systemHealth = await r.json();
            } catch (e) { /* 静默失败 */ }
        },
        selfCheckBadgeLabel() {
            const s = this.systemHealth && this.systemHealth.overall_status;
            if (s === 'all_healthy') return '全部正常 ✅';
            if (s === 'partial_degraded') return '⚠️ 部分降级';
            if (s === 'critical') return '❌ 数据中断 / 关键缺失';
            return '检测中…';
        },
        selfCheckBadgeClass() {
            const s = this.systemHealth && this.systemHealth.overall_status;
            if (s === 'all_healthy')
                return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300';
            if (s === 'partial_degraded')
                return 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300';
            if (s === 'critical')
                return 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300';
            return 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400';
        },
        // Sprint 1.5o:三段式视觉(● 绿点 / ⚠ 黄三角 / ✗ 红叉)
        layerHealthGlyph(h) {
            if (h === 'healthy') return '●';
            if (h === 'degraded') return '⚠';
            return '✗';  // missing
        },
        layerHealthGlyphClass(h) {
            if (h === 'healthy') return 'text-emerald-500';
            if (h === 'degraded') return 'text-amber-500';
            return 'text-rose-500 font-bold';
        },
        layerHealthTextClass(h) {
            if (h === 'healthy') return 'text-slate-700 dark:text-slate-300';
            if (h === 'degraded') return 'text-amber-600 dark:text-amber-400';
            return 'text-rose-600 dark:text-rose-400 font-medium';
        },
        sourceStatusGlyph(s) {
            if (s === 'ok') return '●';
            if (s === 'warn') return '⚠';
            if (s === 'critical') return '✗';
            return '○';  // no_data
        },
        sourceStatusGlyphClass(s) {
            if (s === 'ok') return 'text-emerald-500';
            if (s === 'warn') return 'text-amber-500';
            if (s === 'critical') return 'text-rose-500 font-bold';
            return 'text-slate-400';
        },
        sourceAgeLabel(s) {
            if (s.age_minutes == null) return '无数据';
            const m = s.age_minutes;
            if (m < 60) return `${m.toFixed(1)} 分钟前`;
            if (m < 1440) return `${(m/60).toFixed(1)} 小时前`;
            return `${(m/1440).toFixed(1)} 天前`;
        },
        sourceTextClass(s) {
            if (s === 'ok') return 'text-slate-700 dark:text-slate-300';
            if (s === 'warn') return 'text-amber-600 dark:text-amber-400';
            if (s === 'critical')
                return 'text-rose-600 dark:text-rose-400 font-medium';
            return 'text-slate-400 dark:text-slate-500';  // no_data
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
        // Sprint 1.5k:动态显示数据源标签(spot 1m 主路径 vs K 线 fallback)
        livePriceSourceLabel() {
            const src = this.livePriceData && this.livePriceData.source || '';
            if (src.startsWith('binance_spot')) return '实时(分钟级,Binance 现货)';
            if (src.includes('kline_1h')) return '1h K 线(fallback)';
            return '—';
        },

        // Sprint 2.3 R4:data_freshness 可能是字符串 'green'/'yellow'/'red',
        // 也可能是对象 {status, captured_at, age_seconds}。统一抽 status 字段 + age。
        _freshStatus(v) {
            if (v == null) return null;
            if (typeof v === 'string') return v;
            if (typeof v === 'object') return v.status || null;
            return null;
        },
        _freshAgeSec(v) {
            if (v && typeof v === 'object' && typeof v.age_seconds === 'number') {
                return v.age_seconds;
            }
            return null;
        },
        formatAge(sec) {
            if (sec == null || !isFinite(sec)) return '';
            if (sec < 60) return 'just now';
            if (sec < 3600) return Math.floor(sec / 60) + 'min ago';
            if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
            return Math.floor(sec / 86400) + 'd ago';
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
        // Sprint 1.8.2-C:layer_cards 折叠状态
        layerCardsOpen: {},
        toggleLayerCard(layer) {
            this.layerCardsOpen = {
                ...this.layerCardsOpen,
                [layer]: !this.layerCardsOpen[layer],
            };
        },
        layerCardOpen(layer) {
            return !!this.layerCardsOpen[layer];
        },
        // Sprint 1.8.2-D:13 张小卡 helpers
        cardOpportunityGrade() {
            const grade = this.state?.main_strategy?.opportunity_grade;
            if (!grade || grade === 'none' || grade === 'None') return '无机会';
            return grade + ' 级';
        },
        cardConfidence() {
            const tier = this.tp().confidence_tier;
            if (!tier) return '—';
            return { high: '高', medium: '中', low: '低' }[tier] || tier;
        },
        cardEntryZones() {
            const zones = this.tp().entry_zones || [];
            if (zones.length === 0) return '—';
            return zones.map(z =>
                `$${z.price_low}-${z.price_high} (${z.allocation_pct}%)`
            ).join(', ');
        },
        cardStopLoss() {
            const sl = this.tp().stop_loss;
            return sl != null ? '$' + sl : '—';
        },
        cardTakeProfits() {
            const tps = this.tp().take_profit_plan || [];
            if (tps.length === 0) return '—';
            return tps.map((t, i) =>
                `TP${i+1} $${t.price} ×${t.size_pct}%`
            ).join(', ');
        },
        cardPositionCap() {
            const cap = this.tp().max_position_size_pct;
            return cap != null ? cap + '%' : '—';
        },
        hasActivePosition() {
            const st = this.state?.main_strategy?.action_state;
            return ['LONG_OPEN', 'LONG_HOLD', 'LONG_TRIM', 'SHORT_OPEN', 'SHORT_HOLD', 'SHORT_TRIM'].includes(st);
        },
        cardCurrentPnl() {
            return '—';
        },
        cardDistanceToStop() { return '—'; },
        cardHoldingDuration() { return '—'; },
        cardHardInvalidations() {
            const his = this.hardInvalidationLevels();
            if (his.length === 0) return '—';
            return his.slice(0, 3).map(h => `$${h.price}`).join(', ');
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
            if (!apiOk && !this.error) {
                this.error = '⚠️ /api/strategy/current 不可用。请检查 service 状态或等待下次定时运行。';
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
            const raw = body.state || body;
            if (!raw || typeof raw !== 'object') return null;
            if (raw.schema_version === 'v13' && raw.summary_card) {
                return this._to_display_state_v13(raw);
            }
            // 非 v13 数据:不静默兜底,显式报错让用户知道
            console.error('[app] 收到非 v13 数据,无法渲染。schema_version=', raw.schema_version);
            this.error = '⚠️ 数据格式异常(非 v13 schema)。系统下次定时运行后会自动恢复,如紧急可联系管理员重启服务。';
            return null;
        },

        _to_display_state_v13(raw) {
            // 消费新 v13 schema(state.summary_card / layer_cards / anti_patterns_active /
            // extreme_events_active / factor_cards / meta / raw),映射回前端期望字段。
            if (!raw || typeof raw !== 'object') return raw;
            const out = JSON.parse(JSON.stringify(raw));

            // meta:从 state.meta 派生 generated_at_bjt 等
            const m = out.meta || {};
            const sc = out.summary_card || {};
            out.meta = {
                run_id: m.run_id,
                rules_version: m.rules_version || 'v1.3',
                ai_model_actual: m.ai_model_actual || 'claude-sonnet-4-5',
                strategy_flavor: 'swing',
                generated_at_utc: m.generated_at_utc,
                generated_at_bjt: sc.decision_time || m.generated_at_bjt
                    || this.formatBJT(m.generated_at_utc),
                fallback_level: m.fallback_level,
                cold_start: m.cold_start || {},
                next_run_eta_bjt: m.next_run_eta_bjt || null,
            };

            // market_snapshot:v13 没有,顶部 BTC 价格条走 /api/market/btc-price 独立路径,
            // 这里给空兜底就行
            out.market_snapshot = {
                btc_price_usd: null, btc_price_change_24h_pct: null,
                btc_price_updated_bjt: null,
            };

            // main_strategy:从 summary_card 反向推导(给老前端组件用)
            out.main_strategy = {
                action_state: this._reverseLookupState(sc.action_state_label) || 'FLAT',
                lifecycle_phase: sc.action_state_label || '—',
                opportunity_grade: this._extractGrade(out.layer_cards) || 'none',
                execution_permission: this._extractPermission(out.layer_cards) || 'watch',
                observation_category: 'disciplined',
            };

            // data_health:简单兜底
            out.data_health = {
                overall: sc.validator_passed === false ? 'yellow' : 'green',
                data_completeness_pct: 95,
                sources: {}, degraded_stages: [],
            };

            // risks:从 L4 layer_card 提取(supporting_data)
            out.risks = {
                hard_invalidation_levels: this._extractHardInvalidations(out.layer_cards),
                active_risk_tags: out.anti_patterns_active || [],
                event_windows: [],
                worst_case_estimate: null,
            };

            // ai_verdict:用 master 卡的 narrative 等字段
            const masterCard = (out.layer_cards || []).find(c => c.layer === 'master') || {};
            out.ai_verdict = {
                one_line_summary: sc.headline || '',
                narrative: masterCard.narrative || sc.headline || '',
                primary_drivers: (masterCard.key_observations || []).map(t => ({ text: t, evidence_ref: null })),
                counter_arguments: (masterCard.contradicting_signals || []).map(t => ({ text: t })),
                what_would_change_mind: [],
                thesis_assessment: null, holding_guidance: null,
                transition_reason: '',
                confidence_breakdown: {},
            };

            // delta_from_previous:简单兜底
            out.delta_from_previous = {
                has_previous: true,
                summary_tag: '状态未变',
                notable_changes: [],
            };

            // factor_cards:已透传,无需额外处理
            if (!Array.isArray(out.factor_cards)) {
                out.factor_cards = [];
            }

            // extra
            out.extra = { history_timeline_preview: [] };
            return out;
        },

        // helper:从中文 label 反推 v12 state code(用于老前端组件兼容)
        _reverseLookupState(label) {
            const m = {
                '空仓观察': 'FLAT',
                '准备做多(还没开)': 'LONG_PLANNED',
                '已开多仓(初次入场)': 'LONG_OPEN',
                '持有多单': 'LONG_HOLD',
                '多单减仓中': 'LONG_TRIM',
                '多单清仓': 'LONG_EXIT',
                '准备做空(还没开)': 'SHORT_PLANNED',
                '已开空仓': 'SHORT_OPEN',
                '持有空单': 'SHORT_HOLD',
                '空单减仓中': 'SHORT_TRIM',
                '空单清仓': 'SHORT_EXIT',
                '反手冷却期(刚平仓,不能立刻反手)': 'FLIP_WATCH',
                '保护模式(极端事件,只清仓不开新仓)': 'PROTECTION',
                '保护后重新评估': 'POST_PROTECTION_REASSESS',
            };
            return m[label] || null;
        },

        _extractGrade(layer_cards) {
            const l3 = (layer_cards || []).find(c => c.layer === 'l3') || {};
            const sd = l3.supporting_data || {};
            // l3 卡的 supporting_data 通常含 opportunity_grade 原值,或 label 含 "C 级机会"
            if (sd.opportunity_grade && sd.opportunity_grade.value) return sd.opportunity_grade.value;
            const label = l3.label || '';
            if (label.startsWith('A ')) return 'A';
            if (label.startsWith('B ')) return 'B';
            if (label.startsWith('C ')) return 'C';
            if (label.includes('无机会')) return 'none';
            return null;
        },

        _extractPermission(layer_cards) {
            const l3 = (layer_cards || []).find(c => c.layer === 'l3') || {};
            const sd = l3.supporting_data || {};
            if (sd.execution_permission && sd.execution_permission.value) return sd.execution_permission.value;
            return null;
        },

        _extractHardInvalidations(layer_cards) {
            const l4 = (layer_cards || []).find(c => c.layer === 'l4') || {};
            const sd = l4.supporting_data || {};
            const v = sd.hard_invalidation_levels;
            if (v && Array.isArray(v.value)) return v.value;
            if (Array.isArray(v)) return v;
            return [];
        },

        // ============== 派生 ==============
        tp() {
            // adjudicator.trade_plan 优先,否则回退 state.trade_plan(mock)
            return (this.state && (
                (this.state.adjudicator && this.state.adjudicator.trade_plan)
                || this.state.trade_plan
            )) || {};
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
                // Sprint 2.3 R2:2 列等宽网格,主要在前(绿左边框),次要在后
                const allOrdered = [...primary, ...secondary];
                return { ...s, primary, secondary, allOrdered };
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
        eventWindows() {
            return (this.state && this.state.risks && this.state.risks.event_windows) || [];
        },

        // 历史
        historyTimeline() {
            return (this.state && this.state.extra
                    && this.state.extra.history_timeline_preview) || [];
        },

        // ============== 格式化 ==============
        formatPrice(v) {
            // Sprint 1.5k:数据是 USDT 计价(Binance 现货 BTCUSDT),改 USDT 后缀
            if (v == null) return '—';
            return Number(v).toLocaleString(undefined,
                { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' USDT';
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

        directionClass(d) {
            return { bullish: 'text-emerald-600 dark:text-emerald-400',
                     bearish: 'text-rose-600 dark:text-rose-400',
                     neutral: 'text-slate-700 dark:text-slate-200' }[d] || 'text-slate-700 dark:text-slate-200';
        },
        directionLabel(d) {
            return { bullish: '偏多', bearish: '偏空', neutral: '中性' }[d] || d || '中性';
        },

        // ---- Sprint 2.6-H.1:单行 fetched_at_bjt 显示 ----
        // 用户只关心"什么时候抓的 + 多新",K 线 bar 时间对其没用且误导。
        // fetched 缺失时降级到 captured(老兜底)。
        _parseBjt(s) {
            // "2026-04-27 14:06:23 (BJT)" 或 "2026-04-27 14:06 (BJT)" → Date(UTC = BJT - 8h)
            // Sprint 2.6-J:支持秒级输入(后端 _utc_iso_to_bjt_pretty 现在产 "HH:MM:SS")。
            // 没有秒就当 0 处理(兼容 captured_at_bjt 等仍为分钟级的字段)。
            if (!s || typeof s !== 'string') return null;
            const m = s.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
            if (!m) return null;
            const [, y, mo, d, h, mi, sec] = m;
            return new Date(Date.UTC(+y, +mo - 1, +d, +h - 8, +mi, +(sec || 0)));
        },
        _agoLabel(s) {
            const dt = this._parseBjt(s);
            if (!dt) return null;
            const diffMs = Date.now() - dt.getTime();
            if (diffMs < 0) return null;       // 未来时刻,异常
            const mins = Math.floor(diffMs / 60000);
            if (mins < 1) return '刚刚';
            if (mins < 60) return mins + ' 分钟前';
            const hours = Math.floor(mins / 60);
            if (hours < 24) return hours + ' 小时前';
            const days = Math.floor(hours / 24);
            return days + ' 天前';
        },
        fetchedAtPrimary(c) {
            // fetched_at_bjt 存在 → "抓取于 YYYY-MM-DD HH:MM(N 分钟前)"
            // 否则 → 原样返回 captured_at_bjt(降级)
            if (!c) return null;
            if (!c.fetched_at_bjt) return c.captured_at_bjt || null;
            // 去掉 " (BJT)" 后缀(用户已知是 BJT,简化文案)
            const stamp = c.fetched_at_bjt.replace(/\s*\(BJT\)\s*$/, '');
            const ago = this._agoLabel(c.fetched_at_bjt);
            return ago ? '抓取于 ' + stamp + '(' + ago + ')' : '抓取于 ' + stamp;
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
    };
}
