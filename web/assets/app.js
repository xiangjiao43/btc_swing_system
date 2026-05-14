/* =========================================================================
   app.js - BTC Strategy 审计台(Sprint 2.3)
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

        // Sprint B(数据真实性透明化):/api/data_sources/freshness 真实抓取状态
        // 替换原"数据源"那栏从 systemHealth.data_sources(老 inserted_at_utc 推断)
        // 走的逻辑;每 5 分钟刷一次,与 systemHealth 同 timer。
        dataSourcesFreshness: [],

        // Sprint 1.10-I §9.2:5 模块数据
        virtualAccount: null,           // 模块 1 - virtual_account 最新快照
        accountReturns: {               // 模块 1 - 各周期收益率
            daily_pct: null, weekly_pct: null, monthly_pct: null,
            yearly_pct: null, total_pct: null,
        },
        accountHistory: [],             // 模块 1 - 30 天 snapshots(sparkline 数据)
        activeThesis: null,             // 模块 2 - 当前 active thesis
        positionSummary: null,          // 模块 3 - 持仓摘要(从 strategy/current 复用)
        ordersPending: {                // 模块 3 - 当前 pending 挂单
            active_thesis_id: null, items: [],
        },
        thesesHistory: [],              // 模块 4 - thesis 历史时间线
        weeklyReviewSelected: null,     // 模块 5 - 当前选中周复盘
        weeklyReviewHistory: [],        // 模块 5 - 历史 12 周(D3=a)
        weeklyReviewSelectedIdx: 0,     // 模块 5 下拉切换 index

        // RP 红色横幅(D2=a 来自 health.review_pending)+ 模态框(D4=b)
        reviewPending: null,
        rpModalOpen: false,
        rpExitType: 'a',
        rpReason: '',
        rpResolveError: '',

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
        //                    weekly_review / pending_orders + thesis_history + RP 一波 fetch)
        async _refreshV14Modules() {
            const fetchJson = async (url, fallback) => {
                try {
                    const r = await fetch(url, { cache: 'no-cache' });
                    if (r.ok) return await r.json();
                } catch (e) { /* 静默 */ }
                return fallback;
            };
            const [acc, accRet, accHist, active, orders, thHistory,
                   wrLatest, wrHistory, health] = await Promise.all([
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
                fetchJson('/api/theses/history?limit=20', { items: [] }),
                fetchJson('/api/review/weekly/latest', {}),
                fetchJson('/api/review/weekly/history?limit=12', { items: [] }),
                fetchJson('/api/health', {}),
            ]);
            this.virtualAccount = (acc && acc.snapshot_id) ? acc : null;
            this.accountReturns = accRet || this.accountReturns;
            this.accountHistory = (accHist && accHist.snapshots) || [];
            this.activeThesis = (active && active.thesis_id) ? active : null;
            this.ordersPending = orders || this.ordersPending;
            this.thesesHistory = (thHistory && thHistory.items) || [];
            this.weeklyReviewHistory = (wrHistory && wrHistory.items) || [];
            // 默认选中最新(D3=a)
            this.weeklyReviewSelected = (wrLatest && wrLatest.week_start_utc)
                ? wrLatest : null;
            this.weeklyReviewSelectedIdx = 0;
            // RP 红色横幅(D2=a)
            this.reviewPending = (health && health.review_pending) || null;
            // position_summary 从 strategy/current 复用(commit 3 加的字段)
            this.positionSummary = (
                this.state && this.state.position_summary
            ) || null;

            // Sprint 1.10-L commit 8 P1 #4:state_machine.thesis / system_state
            // 镜像消费(K-A commit 7 加,1.10-L 真接通)
            // - 主路径不变:/api/theses/active 拿真 thesis 行 +
            //   /api/health.review_pending 拿 RP 状态
            // - 镜像路径(本 commit 加):state.state_machine.{thesis,system_state}
            //   作 fallback,防 API 失败时网页死锁;同时让用户能从 strategy/current
            //   一次拿全(减少跨 API 一致性窗口)
            const sm = (this.state && this.state.state_machine) || {};
            const smSystemState = sm.system_state || null;
            const smThesis = sm.thesis || null;

            // fallback 1:若 health 没返 review_pending 但 system_state='review_pending'
            // → 临时合成 RP 占位让横幅显示(reason 标 mirror)
            if (!this.reviewPending && smSystemState === 'review_pending') {
                this.reviewPending = {
                    state_id: null,
                    reason: 'state_machine.system_state=review_pending(镜像 fallback)',
                    related_thesis_id: null,
                    entered_at_utc: null,
                    _from_state_machine_mirror: true,
                };
            }

            // fallback 2:若 /api/theses/active 没返(如 API 失败 / 仍冷启动)
            // 但 state_machine.thesis 有镜像 → 最小占位让"当前 thesis"模块显示
            // (主路径仍优先 - 仅 activeThesis null 时镜像顶上)
            if (!this.activeThesis && smThesis) {
                this.activeThesis = {
                    thesis_id: '(state_machine 镜像)',
                    direction: smThesis.direction,
                    lifecycle_stage: smThesis.lifecycle_stage,
                    status: smThesis.status,
                    _from_state_machine_mirror: true,
                };
            }
        },

        // v1.4.1 涂装:AI 模型简化显示(策略建议 header)
        // 'claude-sonnet-4-5-20250929' → 'Claude Sonnet 4.5'
        // 不匹配正则 → 直接返原值(future Opus / Haiku 兼容);空 → 空字符串
        simplifyAiModel(model) {
            if (!model) return '';
            const m = String(model).match(/^claude-(\w+)-(\d+)-(\d+)/);
            if (!m) return String(model);
            const name = m[1].charAt(0).toUpperCase() + m[1].slice(1);
            return `Claude ${name} ${m[2]}.${m[3]}`;
        },

        // Sprint 1.10-I §9.2.4 模块 4:thesis 时间线辅助函数
        thesisDurationDays(t) {
            if (!t || !t.created_at_utc) return '-';
            try {
                const start = new Date(t.created_at_utc);
                const end = t.closed_at_utc ? new Date(t.closed_at_utc) : new Date();
                const days = Math.max(0, Math.round((end - start) / 86400000));
                return days + 'd';
            } catch (e) { return '-'; }
        },
        thesisStatusColor(status) {
            if (status === 'active') return 'text-blue-600 dark:text-blue-400';
            if (status === 'closed_profit') return 'text-emerald-600 dark:text-emerald-400';
            if (status === 'closed_loss') return 'text-rose-600 dark:text-rose-400';
            if (status === 'invalidated') return 'text-amber-600 dark:text-amber-400';
            return 'text-slate-500';
        },

        // Sprint 1.10-I §9.2.5 模块 5:23 V key list(给 hard_constraint 表用)
        validatorKeys() {
            return [
                'validator_1_stop_loss_overridden',
                'validator_2_position_capped',
                'validator_3_entry_size_normalized',
                'validator_4_protection_blocked',
                'validator_5_grade_permission_lock',
                'validator_6_thesis_lock',
                'validator_7_invalidation_check',
                'validator_8_break_objectivity',
                'validator_9_break_distance',
                'validator_10_grade_lock',
                'validator_11_direction_lock',
                'validator_12_evidence_real',
                'validator_13_objective_evidence',
                'validator_14_counter_argument',
                'validator_15_confidence_capped',
                'validator_16_change_mind',
                'validator_17_stop_tightening',
                'validator_18_14d_fuse_active',
                'validator_19_60d_cap',
                'validator_20_consecutive_fuse',
                'validator_21_soft_resistance',
                'validator_22_3day_fail',
                'validator_23_conflict_missing',
            ];
        },
        weeklyReviewOutput() {
            return (this.weeklyReviewSelected && this.weeklyReviewSelected.output) || {};
        },
        weeklyReviewSampleBase() {
            const out = this.weeklyReviewOutput();
            if (out.sample_base) return out.sample_base;
            const perf = out.performance_summary || {};
            const hc = out.hard_constraint_activation_review || {};
            let denominator = null;
            for (const k of this.validatorKeys()) {
                const rate = hc[k] && hc[k].rate;
                const m = String(rate || '').match(/^\s*\d+\s*\/\s*(\d+)/);
                if (m) {
                    denominator = Number(m[1]);
                    break;
                }
            }
            if (perf.total_runs == null || denominator == null) return null;
            return {
                total_strategy_runs: perf.total_runs,
                valid_constraint_runs: denominator,
                missing_constraint_runs: Math.max(Number(perf.total_runs) - denominator, 0),
                legacy_inferred: true,
            };
        },
        formatValidatorRate(rate) {
            if (!rate) return '-';
            return String(rate)
                .replace(/\s*days\b/g, ' 有效决策')
                .replace(/\s*valid_runs\b/g, ' 有效决策');
        },
        weeklyReviewRecommendationAction(r) {
            if (!r) return '';
            return r['具体调整路径'] || r['建议'] || r.suggested_action || '';
        },
        weeklyReviewRecommendationId(r) {
            if (!r) return '-';
            return r.normalized_recommendation_id
                || r.recommendation_id
                || r.id
                || r.canonical_id
                || r.issue_id
                || '-';
        },
        weeklyReviewRecommendationConfidence(r) {
            if (!r) return 'low';
            return r.evidence_confidence || r.confidence || r.confidence_level || 'low';
        },
        weeklyReviewRecommendationConfidenceReason(r) {
            if (!r) return '-';
            return r.confidence_reason || r.evidence_reason || '-';
        },
        weeklyReviewRecommendationOutcome(r) {
            return (r && r.outcome_tracking) || {};
        },
        weeklyReviewAiVsActual() {
            const sq = this.weeklyReviewOutput().strategy_quality || {};
            const rows = sq.ai_vs_actual_comparison || [];
            return Array.isArray(rows) ? rows : [];
        },
        weeklyReviewDiagnostics() {
            const out = this.weeklyReviewOutput();
            const nested = out.evidence_diagnostics || {};
            return {
                l3: out.l3_diagnostics || nested.l3_diagnostics || {},
                l4: out.l4_diagnostics || nested.l4_diagnostics || {},
                validator: out.validator_diagnostics
                    || nested.validator_diagnostics || {},
            };
        },
        hasDiagnosticData(value) {
            if (value == null || value === '') return false;
            if (Array.isArray(value)) {
                return value.some(v => this.hasDiagnosticData(v));
            }
            if (typeof value === 'object') {
                return Object.values(value).some(v => this.hasDiagnosticData(v));
            }
            if (typeof value === 'number') return value !== 0;
            return true;
        },
        hasWeeklyReviewDiagnostics() {
            const d = this.weeklyReviewDiagnostics();
            return this.hasDiagnosticData(d.l3)
                || this.hasDiagnosticData(d.l4)
                || this.hasDiagnosticData(d.validator);
        },
        weeklyReviewTemporalDiagnostics() {
            const out = this.weeklyReviewOutput();
            return out.temporal_consistency_diagnostics || {};
        },
        hasWeeklyReviewTemporalDiagnostics() {
            return this.hasDiagnosticData(this.weeklyReviewTemporalDiagnostics());
        },
        weeklyReviewAnomalyStreaks() {
            return this.weeklyReviewTemporalDiagnostics().anomaly_streaks || {};
        },
        weeklyReviewRecurringRecommendations() {
            const rows = this.weeklyReviewTemporalDiagnostics().recommendation_recurrence || [];
            return Array.isArray(rows) ? rows : [];
        },
        diagnosticEntries(obj) {
            if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return [];
            return Object.entries(obj).map(([key, value]) => ({
                key,
                value: this.formatReviewValue(value),
            }));
        },

        // Sprint 1.10-I §9.4:AI 失败状态显示(替换"无机会"模糊)
        // 数据源:state.raw.retry_log_json(commit 1.10-F migration 012)
        aiFailureStatus() {
            const raw = (this.state && this.state.raw) || {};
            const rl = raw.retry_log || raw.retry_log_json || {};
            // retry_log_json 可能是字符串
            const rlObj = (typeof rl === 'string') ? this._safeParseJson(rl) : rl;
            if (!rlObj || Object.keys(rlObj).length === 0) return null;

            const failedLayers = rlObj.failed_layers || [];
            const macroFb = rlObj.macro_fallback_applied;
            const thesisFb = rlObj.thesis_aware_fallback_applied;
            const retryExhausted = rlObj.retry_exhausted;
            const retryNext = rlObj.retry_next_attempt;

            if (retryExhausted) {
                return 'AI 介入失败 - 请人工介入(超 2h 重试窗口或 max_attempts)';
            }
            if (failedLayers.length > 0) {
                const layers = failedLayers.join('/');
                if (failedLayers.includes('master')) {
                    if (thesisFb) {
                        return 'master AI 失败,thesis_aware fallback 已接管(等下次重试)';
                    }
                    return `${layers} 失败,Master 已短路`;
                }
                return `${layers} 失败,下游已短路`;
            }
            if (macroFb) {
                return 'L5 macro AI 失败,使用硬编码 macro fallback';
            }
            if (retryNext) {
                return `AI 介入失败,重试中(第 ${retryNext} 次)`;
            }
            return null;
        },
        aiFailureDetail() {
            const raw = (this.state && this.state.raw) || {};
            const rl = raw.retry_log || raw.retry_log_json || {};
            const rlObj = (typeof rl === 'string') ? this._safeParseJson(rl) : rl;
            if (!rlObj || Object.keys(rlObj).length === 0) return null;
            return JSON.stringify(rlObj);
        },
        _safeParseJson(s) {
            try { return JSON.parse(s); } catch (e) { return null; }
        },

        // Sprint 1.10-I D4=b+c:POST /api/review_pending/resolve
        async resolveReviewPending() {
            this.rpResolveError = '';
            const reasonText = (this.rpReason || '').trim();
            if (reasonText.length < 10) {
                this.rpResolveError = '理由至少 10 字符';
                return;
            }
            try {
                const r = await fetch('/api/review_pending/resolve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        exit_type: this.rpExitType,
                        reason: reasonText,
                    }),
                });
                if (!r.ok) {
                    const body = await r.json().catch(() => ({}));
                    this.rpResolveError = (body.detail && (
                        typeof body.detail === 'string'
                            ? body.detail : JSON.stringify(body.detail)
                    )) || `HTTP ${r.status}`;
                    return;
                }
                // 成功 → 关闭模态框 + 刷新 RP 状态
                this.rpModalOpen = false;
                this.rpReason = '';
                await this._refreshV14Modules();
            } catch (e) {
                this.rpResolveError = String(e);
            }
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
            if (v == null || isNaN(v)) return '-';
            const n = Number(v);
            if (Math.abs(n) >= 1000) return '$' + n.toLocaleString(undefined, {
                maximumFractionDigits: 0,
            });
            return '$' + n.toFixed(2);
        },

        // Sprint 1.10-I §9.2.3:挂单价距当前 BTC 现价的 %(带 ± 号)
        distanceFromLive(orderPrice) {
            const live = this.livePrice();
            if (!live || !orderPrice) return '-';
            const pct = ((Number(orderPrice) - live) / live) * 100;
            return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        },

        async _refreshSystemHealth() {
            try {
                const r = await fetch('/api/system/health-detail',
                                      { cache: 'no-cache' });
                if (r.ok) this.systemHealth = await r.json();
            } catch (e) { /* 静默失败 */ }
            // Sprint B:同时刷新 fetch_attempts 真实抓取状态(数据源那栏)
            try {
                const r2 = await fetch('/api/data_sources/freshness',
                                       { cache: 'no-cache' });
                if (r2.ok) this.dataSourcesFreshness = await r2.json();
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
        // Sprint B:fetch_attempts 真实状态 helper(替代老的 inserted_at_utc 推断)
        // status ∈ {success, failure, no_data}
        sourceStatusGlyph(status) {
            if (status === 'success') return '●';
            if (status === 'failure') return '●';
            return '○';  // no_data
        },
        sourceStatusGlyphClass(status) {
            if (status === 'success') return 'text-emerald-500';
            if (status === 'failure') return 'text-rose-500 font-bold';
            return 'text-slate-400';
        },
        sourceTextClass(status) {
            if (status === 'success') return 'text-slate-700 dark:text-slate-300';
            if (status === 'failure')
                return 'text-rose-600 dark:text-rose-400 font-medium';
            return 'text-slate-400 dark:text-slate-500';
        },
        sourceAgeLabel(src) {
            // src 是 freshness 行(包含 status / minutes_ago / failure_reason 等)
            // Sprint D:no_data 时也用 last_success_at_bjt(API fallback 到数据表
            // MAX),显示距今多久 — 不再「尚未抓取」。
            if (src.status === 'no_data') {
                return src.last_success_at_bjt
                    ? this._humanAgeFromBjt(src.last_success_at_bjt)
                    : '无可用数据';
            }
            const m = src.minutes_ago;
            if (m == null) return '-';
            let timeStr;
            if (m < 60) timeStr = `${m} 分钟前`;
            else if (m < 1440) timeStr = `${(m/60).toFixed(1)} 小时前`;
            else timeStr = `${(m/1440).toFixed(1)} 天前`;
            if (src.status === 'failure') return `${timeStr}抓取失败`;
            return timeStr;
        },
        // 「沿用 X 月 X 日数据」灰字小注脚:failure / no_data 都可显示
        sourceStaleHint(src) {
            if (src.status === 'success') return null;
            if (!src.last_success_at_bjt) return '无可用数据';
            const m = src.last_success_at_bjt.match(/^\d{4}-(\d{2})-(\d{2})/);
            if (!m) return src.last_success_at_bjt;
            return `沿用 ${parseInt(m[1])} 月 ${parseInt(m[2])} 日数据`;
        },
        // Sprint D 内部 helper:从 BJT 字符串算「X 分钟/小时前」
        _humanAgeFromBjt(bjtStr) {
            try {
                const m = bjtStr.match(
                    /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/);
                if (!m) return bjtStr;
                // BJT 是 UTC+8;转成 epoch(假设浏览器时区不影响绝对差值)
                const utcMs = Date.UTC(
                    +m[1], +m[2]-1, +m[3], +m[4]-8, +m[5], +m[6]);
                const ageMin = (Date.now() - utcMs) / 60000;
                if (ageMin < 60) return `${Math.round(ageMin)} 分钟前`;
                if (ageMin < 1440) return `${(ageMin/60).toFixed(1)} 小时前`;
                return `${(ageMin/1440).toFixed(1)} 天前`;
            } catch (e) { return bjtStr; }
        },
        // failure_reason 中文徽章 class
        sourceReasonBadgeClass(reason) {
            if (reason === 'quota_exceeded')
                return 'bg-rose-500 text-white';
            if (reason === 'network_error' || reason === 'api_error'
                || reason === 'parse_error')
                return 'bg-amber-200 text-amber-900 dark:bg-amber-700 dark:text-amber-100';
            return 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300';
        },
        // hover tooltip:完整信息(BJT 时间 + 失败时 error_message + 持续 ms)
        sourceTooltip(src) {
            const parts = [];
            if (src.last_attempt_at_bjt) {
                parts.push(`最近 attempt: ${src.last_attempt_at_bjt}`);
            }
            if (src.status === 'failure' && src.last_success_at_bjt) {
                parts.push(`最近成功: ${src.last_success_at_bjt}`);
            }
            if (src.duration_ms != null) {
                parts.push(`耗时: ${src.duration_ms} ms`);
            }
            if (src.rows_upserted != null) {
                parts.push(`入库行数: ${src.rows_upserted}`);
            }
            if (src.error_message) {
                parts.push(`错误: ${src.error_message}`);
            }
            return parts.join(' · ') || src.display_name;
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
            return '-';
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
            if (!tier) return '-';
            return { high: '高', medium: '中', low: '低' }[tier] || tier;
        },
        cardEntryZones() {
            const zones = this.tp().entry_zones || [];
            if (zones.length === 0) return '-';
            return zones.map(z =>
                `$${z.price_low}-${z.price_high} (${z.allocation_pct}%)`
            ).join(', ');
        },
        cardStopLoss() {
            const sl = this.tp().stop_loss;
            return sl != null ? '$' + sl : '-';
        },
        cardTakeProfits() {
            const tps = this.tp().take_profit_plan || [];
            if (tps.length === 0) return '-';
            return tps.map((t, i) =>
                `TP${i+1} $${t.price} ×${t.size_pct}%`
            ).join(', ');
        },
        cardPositionCap() {
            const cap = this.tp().max_position_size_pct;
            return cap != null ? cap + '%' : '-';
        },
        hasActivePosition() {
            const st = this.state?.main_strategy?.action_state;
            return ['LONG_OPEN', 'LONG_HOLD', 'LONG_TRIM', 'SHORT_OPEN', 'SHORT_HOLD', 'SHORT_TRIM'].includes(st);
        },
        cardCurrentPnl() {
            return '-';
        },
        cardDistanceToStop() { return '-'; },
        cardHoldingDuration() { return '-'; },
        cardHardInvalidations() {
            // Sprint K++:优先 filtered(过滤掉跟 entry 重叠 / 反向 type / 弱预警),
            // 通常返 1-2 条:active stop_loss + 紧邻一档预警。
            const filtered = (this.state
                && this.state.hard_invalidation_levels_filtered) || [];
            if (filtered.length > 0) return filtered;
            // 兜底:无 filtered 字段(老 schema)→ 用 classified 全列表(top 4)
            const classified = (this.state
                && this.state.hard_invalidation_levels_classified) || [];
            if (classified.length > 0) return classified.slice(0, 4);
            // fallback v1.3 老格式(list of float / dict 但无 type)
            const his = this.hardInvalidationLevels();
            if (his.length === 0) return [];
            return his.slice(0, 3).map(h => ({
                price: (typeof h === 'object' ? h.price : h),
                type_label: '—', severity_label: '硬止损',
                severity_rank: 3, is_active_stop_loss: false,
            }));
        },
        cardHardInvalidationsEmpty() {
            return this.cardHardInvalidations().length === 0;
        },
        severityClass(rank) {
            if (rank >= 3) return 'text-rose-600 dark:text-rose-400 font-semibold';
            if (rank >= 2) return 'text-amber-600 dark:text-amber-400';
            return 'text-slate-500 dark:text-slate-400';
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
            // Sprint 1.10-I commit 7 fix:schema gate 三态升级
            // 真用户测试发现:写死 raw.schema_version === 'v13' 后,新 v14
            // 数据(无 schema_version 或 schema_version='v14')永远不渲染,
            // 5 个 1.10-I 新模块全黑屏。改为兼容 3 形态:
            //   - v13:走 _to_display_state_v13(老路径)
            //   - v14:含 v14 模块字段(account_summary 等),直接消费
            //   - hasBasicData 兜底:有 run_id + generated_at_utc 就允许渲染
            //     (各模块自己处理空字段占位符,避免新 schema 出现时再死锁)
            if (!body) return null;
            const raw = body.state || body;
            if (!raw || typeof raw !== 'object') return null;

            const hasV13Schema = raw.schema_version === 'v13' && raw.summary_card;
            const hasV14Modules = !!(
                raw.account_summary || raw.active_thesis ||
                raw.position_summary || raw.pending_orders_summary ||
                raw.schema_version === 'v14'
            );
            const hasBasicData = !!(raw.run_id && raw.generated_at_utc);

            if (hasV13Schema) {
                return this._to_display_state_v13(raw);
            }
            if (hasV14Modules || hasBasicData) {
                // 直接消费 raw(含 1.10-I 新 4 字段 + 1.10-I.commit 3 normalize_state 输出)
                // 各模块的 cold-start placeholder 已实施(commit 4/5),
                // 字段为空 → 显示"未初始化"而非整页报错
                return raw;
            }

            // 完全空(无 run_id):说明系统从未跑过 → 友好提示
            this.error = '⚠️ 数据为空,等待下次 strategy_run(每日 16:00 BJT 自动跑)';
            console.warn('[app] strategy_run 数据为空,等待下次自动 run');
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
                // Sprint 1.10-J commit 6 §X:删 cold_start 字段(v1.4 §11.2)
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
                lifecycle_phase: sc.action_state_label || '-',
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
                '保护模式(极端事件,只清仓不开新仓)': 'PROTECTION',
                // Sprint 1.10-J commit 4b §X(E.1.a 网页脱钩):
                // FLIP_WATCH / POST_PROTECTION_REASSESS label 反向映射删
                // (v1.4 §11.2);state_machine 主体重写留 1.10-K
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

        // ============== Layer A 大周期现货策略 ==============
        spotStrategy() {
            return (this.state && this.state.layer_a_spot_strategy) || null;
        },
        spotStrategyFallbackText() {
            return '暂无大周期策略，本 run 尚未记录 Layer A 输出。';
        },
        spotStrategyUpdatedAt() {
            const s = this.spotStrategy() || {};
            if (s.generated_at_bjt) return s.generated_at_bjt;
            if (s.generated_at_utc) return this.formatBJT(s.generated_at_utc);
            const m = (this.state && this.state.meta) || {};
            if (m.layer_a_spot_updated_at_bjt) return m.layer_a_spot_updated_at_bjt;
            if (m.layer_a_spot_updated_at_utc) return this.formatBJT(m.layer_a_spot_updated_at_utc);
            return '-';
        },
        spotActionLabel(v) {
            const m = {
                dca_buy: '分批买入',
                aggressive_buy: '强势买入',
                hold: '持有',
                scale_out: '分批卖出',
                aggressive_sell: '强力卖出',
            };
            return m[v] || '持有';
        },
        spotCycleStageLabel(v) {
            const m = {
                bear_bottom: '熊市底部',
                accumulation: '底部吸筹',
                early_bull: '牛市早期',
                mid_bull: '牛市中段',
                late_bull: '牛市末期',
                distribution: '顶部派发',
                bear_transition: '转熊阶段',
                deep_bear: '深度熊市',
                unclear: '不明确',
            };
            return m[v] || '不明确';
        },
        spotConfidenceLabel(v) {
            return ({ low: '低', medium: '中', high: '高' })[v] || '低';
        },
        spotRiskLabel(v) {
            return ({
                low: '低',
                moderate: '中等',
                elevated: '偏高',
                high: '高',
                critical: '极端',
            })[v] || '偏高';
        },
        spotLayerCards() {
            const s = this.spotStrategy();
            if (!s) return [];
            const a1 = s.a1_cycle_stage || {};
            const a2 = s.a2_onchain_macro || {};
            const a3 = s.a3_spot_opportunity || {};
            const a4 = s.a4_spot_risk || {};
            const a5 = s.a5_spot_adjudicator || {};
            return [
                {
                    key: 'layer_a_a1',
                    title: 'A1 大周期阶段',
                    badge: this.spotConfidenceLabel(a1.confidence),
                    label: this.spotCycleStageLabel(a1.cycle_stage),
                    summary: a1.human_summary,
                    supporting: a1.bullish_evidence || [],
                    opposing: [...(a1.bearish_evidence || []), ...(a1.conflicting_evidence || [])],
                    dataQuality: a1.data_quality_notes || [],
                },
                {
                    key: 'layer_a_a2',
                    title: 'A2 链上与宏观',
                    badge: this.spotConfidenceLabel(a2.confidence),
                    label: a2.onchain_macro_stance || 'unclear',
                    summary: a2.human_summary,
                    supporting: a2.supporting_evidence || [],
                    opposing: a2.opposing_evidence || [],
                    dataQuality: a2.data_quality_notes || [],
                },
                {
                    key: 'layer_a_a3',
                    title: 'A3 现货策略机会',
                    badge: this.spotConfidenceLabel(a3.confidence),
                    label: this.spotActionLabel(a3.preferred_action_candidate),
                    summary: a3.human_summary,
                    supporting: [a3.buy_logic, ...(a3.suggested_plan || [])].filter(Boolean),
                    opposing: [a3.sell_logic, ...(a3.do_not_do || [])].filter(Boolean),
                    dataQuality: a3.data_quality_notes || [],
                },
                {
                    key: 'layer_a_a4',
                    title: 'A4 现货风险',
                    badge: this.spotConfidenceLabel(a4.confidence),
                    label: this.spotRiskLabel(a4.spot_risk_level),
                    summary: a4.human_summary,
                    supporting: [...(a4.risk_controls || []), ...(a4.overheat_signals || [])],
                    opposing: [...(a4.main_risks || []), ...(a4.downside_risks || []), ...(a4.invalidation_watch || [])],
                    dataQuality: a4.data_quality_notes || [],
                },
                {
                    key: 'layer_a_a5',
                    title: 'A5 大周期主裁',
                    badge: this.spotConfidenceLabel(a5.confidence),
                    label: this.spotActionLabel(a5.spot_action),
                    summary: a5.human_summary,
                    supporting: [...(a5.supporting_evidence || []), ...(a5.suggested_plan || [])],
                    opposing: [...(a5.opposing_evidence || []), ...(a5.do_not_do || [])],
                    dataQuality: [...(a5.data_quality_notes || []), ...((s.validator && s.validator.warnings) || [])],
                },
            ];
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
        layerAFactorCardSpecs() {
            return [
                {
                    key: 'lth_sopr',
                    name: 'LTH SOPR',
                    name_en: 'Long-Term Holder SOPR',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [['onchain_holder_behavior', 'lth_sopr']],
                },
                {
                    key: 'sth_sopr',
                    name: 'STH SOPR',
                    name_en: 'Short-Term Holder SOPR',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [['onchain_holder_behavior', 'sth_sopr']],
                },
                {
                    key: 'rhodl_ratio',
                    name: 'RHODL Ratio',
                    name_en: 'Realized HODL Ratio',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [['onchain_valuation', 'rhodl_ratio']],
                },
                {
                    key: 'reserve_risk',
                    name: 'Reserve Risk',
                    name_en: 'Reserve Risk',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [['onchain_valuation', 'reserve_risk']],
                },
                {
                    key: 'puell_multiple',
                    name: 'Puell Multiple',
                    name_en: 'Puell Multiple',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [['onchain_valuation', 'puell_multiple']],
                },
                {
                    key: 'lth_net_position_change',
                    name: 'LTH 净头寸变化',
                    name_en: 'LTH Net Position Change',
                    group: 'onchain',
                    source: 'Glassnode',
                    value_unit: 'BTC',
                    paths: [['onchain_holder_behavior', 'lth_net_position_change']],
                },
                {
                    key: 'percent_supply_in_profit',
                    name: '盈利供给比例',
                    name_en: 'Percent Supply in Profit',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [
                        ['onchain_holder_behavior', 'percent_supply_in_profit'],
                        ['onchain_valuation', 'percent_supply_in_profit'],
                    ],
                },
                {
                    key: 'percent_supply_in_loss',
                    name: '亏损供给比例',
                    name_en: 'Percent Supply in Loss',
                    group: 'onchain',
                    source: 'Glassnode',
                    paths: [['onchain_holder_behavior', 'percent_supply_in_loss']],
                },
                {
                    key: 'exchange_balance',
                    name: '交易所余额',
                    name_en: 'Exchange Balance',
                    group: 'onchain',
                    source: 'Glassnode',
                    value_unit: 'BTC',
                    paths: [
                        ['onchain_holder_behavior', 'exchange_balance'],
                        ['exchange_and_flows', 'exchange_balance'],
                    ],
                },
                {
                    key: 'exchange_net_position_change',
                    name: '交易所净头寸变化',
                    name_en: 'Exchange Net Position Change',
                    group: 'onchain',
                    source: 'Glassnode',
                    value_unit: 'BTC',
                    paths: [['onchain_holder_behavior', 'exchange_net_position_change']],
                },
                {
                    key: 'us2y',
                    name: '美国 2 年期收益率',
                    name_en: 'US2Y',
                    group: 'macro',
                    source: 'FRED',
                    value_unit: '%',
                    paths: [['macro_liquidity', 'us2y'], ['macro', 'us2y']],
                },
                {
                    key: 'fed_funds_rate',
                    name: '联邦基金利率',
                    name_en: 'Fed Funds Rate',
                    group: 'macro',
                    source: 'FRED',
                    value_unit: '%',
                    paths: [
                        ['macro_liquidity', 'fed_funds_rate'],
                        ['macro', 'fed_funds_rate'],
                    ],
                },
                {
                    key: 'real_yield',
                    name: '美国 10 年期实际利率',
                    name_en: '10Y Real Yield',
                    group: 'macro',
                    source: 'FRED',
                    value_unit: '%',
                    paths: [
                        ['macro_inflation_rates', 'real_yield'],
                        ['macro_liquidity', 'real_yield'],
                        ['macro', 'real_yield'],
                    ],
                },
                {
                    key: 'cpi',
                    name: 'CPI',
                    name_en: 'Consumer Price Index',
                    group: 'macro',
                    source: 'FRED',
                    paths: [['macro_inflation_rates', 'cpi'], ['macro', 'cpi']],
                },
                {
                    key: 'core_cpi',
                    name: '核心 CPI',
                    name_en: 'Core CPI',
                    group: 'macro',
                    source: 'FRED',
                    paths: [['macro_inflation_rates', 'core_cpi'], ['macro', 'core_cpi']],
                },
                {
                    key: 'm2',
                    name: 'M2',
                    name_en: 'M2 Money Stock',
                    group: 'macro',
                    source: 'FRED',
                    value_unit: 'B',
                    paths: [['macro_liquidity', 'm2'], ['macro', 'm2']],
                },
                {
                    key: 'fed_balance_sheet',
                    name: '美联储资产负债表',
                    name_en: 'Fed Balance Sheet',
                    group: 'macro',
                    source: 'FRED',
                    value_unit: 'M',
                    paths: [
                        ['macro_liquidity', 'fed_balance_sheet'],
                        ['macro', 'fed_balance_sheet'],
                    ],
                },
            ];
        },
        layerAFactorContextValue(spec) {
            const spot = this.spotStrategy() || {};
            const snapshots = [
                spot.input_context_snapshot,
                spot.spot_cycle_context,
                spot.context,
            ].filter(Boolean);
            for (const snapshot of snapshots) {
                const factors = snapshot.available_factors || {};
                for (const path of (spec.paths || [])) {
                    let cur = factors;
                    for (const part of path) cur = cur && cur[part];
                    if (cur && typeof cur === 'object') return cur;
                }
            }
            return null;
        },
        layerAFactorUnavailableStatus(key) {
            const unavailable = this.spotStrategy()?.unavailable_factors
                || this.spotStrategy()?.input_context_snapshot?.unavailable_factors
                || [];
            const item = unavailable.find(x => x && x.factor === key);
            return item ? (item.project_status || 'unavailable') : null;
        },
        layerAFactorUnavailableLabel(status) {
            const labels = {
                proxy_endpoint_404: '未接入',
                not_supported_by_current_proxy: '未接入',
                uncertain_rate_limited: '数据受限',
                not_found: '未接入',
                config_only: '未启用',
                deprecated_candidate: '已废弃',
                partial_event_calendar_only: '仅事件日历部分可用',
                ai_derived_not_precomputed_for_layer_a: '尚未预计算',
                missing: '当前缺值',
                unavailable: '不可用',
            };
            return labels[status] || (status || '不可用');
        },
        layerAFactorStatusLabel(status, freshness) {
            if (status === 'available' && !(freshness && freshness.is_stale)) return '可用';
            if (status === 'stale' || (freshness && freshness.is_stale)) return '数据过期';
            return this.layerAFactorUnavailableLabel(status);
        },
        layerAFactorFetchedAt(factor) {
            if (!factor) return null;
            return factor.fetched_at_bjt || this.formatBJT(factor.fetched_at_utc);
        },
        layerAFactorCapturedAt(factor) {
            if (!factor) return null;
            return this.formatBJT(factor.captured_at_utc || factor.as_of);
        },
        layerAFactorCoverageSummary() {
            const coverage = this.spotStrategy()?.factor_coverage
                || this.spotStrategy()?.input_context_snapshot?.factor_coverage
                || null;
            if (!coverage) return 'Layer A 因子覆盖: 旧 run 未记录';
            const available = coverage.available_factor_count ?? '-';
            const missing = coverage.missing_integrated_factor_count ?? '-';
            const stale = coverage.stale_factor_count ?? '-';
            const critical = coverage.critical_unavailable_count ?? '-';
            const cap = coverage.confidence_cap || '-';
            return `Layer A 因子覆盖: 可用 ${available} / 缺值 ${missing} / 过期 ${stale} / 关键未接入 ${critical} / 置信度上限 ${cap}`;
        },
        layerAFactorUnavailableSummary() {
            const unavailable = this.spotStrategy()?.unavailable_factors
                || this.spotStrategy()?.input_context_snapshot?.unavailable_factors
                || [];
            if (!unavailable.length) return 'Layer A 未接入因子: 暂无';
            return 'Layer A 未接入因子: ' + unavailable
                .slice(0, 6)
                .map(x => `${x.factor || '-'}(${this.layerAFactorUnavailableLabel(x.project_status || 'unavailable')})`)
                .join('、');
        },
        layerAFactorDataQualitySummary() {
            const notes = this.spotStrategy()?.data_quality_notes
                || this.spotStrategy()?.input_context_snapshot?.data_quality_notes
                || [];
            if (!notes.length) return 'Layer A 数据质量: 暂无额外备注';
            return 'Layer A 数据质量: ' + notes.slice(0, 2).join('；');
        },
        layerAFactorValueText(value, unit) {
            const base = this.formatFactorValue(value);
            return unit ? `${base}${unit}` : base;
        },
        layerAFactorPlainReading(spec, factor, statusLabel, hasValue) {
            const value = hasValue ? Number(factor.actual_value) : null;
            const shown = hasValue ? this.layerAFactorValueText(value, spec.value_unit || '') : null;
            const statusText = statusLabel || '不可用';
            const unavailable = statusText === '当前缺值'
                ? '当前缺值'
                : `当前数据${statusText}`;
            const unavailableLine = (purpose) => `📊 ${purpose}；${unavailable}。`;
            if (!hasValue) {
                const purpose = {
                    lth_sopr: 'LTH SOPR 用于观察长期持有人是否在获利卖出',
                    sth_sopr: 'STH SOPR 用于观察短期持有人是否接近盈亏平衡',
                    rhodl_ratio: 'RHODL Ratio 用于观察大周期估值温度',
                    reserve_risk: 'Reserve Risk 用于观察长期持有者信心与价格风险',
                    puell_multiple: 'Puell Multiple 用于观察矿工收入压力与周期位置',
                    lth_net_position_change: 'LTH 净头寸变化用于观察长期持有人增持或减持方向',
                    percent_supply_in_profit: '盈利供给比例用于判断市场筹码盈利面是否过热',
                    percent_supply_in_loss: '亏损供给比例用于判断市场是否仍有恐慌或承压筹码',
                    exchange_balance: '交易所余额用于观察可交易供给压力',
                    exchange_net_position_change: '交易所净头寸变化用于观察资金流入或流出交易所',
                    us2y: '美国 2 年期收益率用于观察短端利率压力',
                    fed_funds_rate: '联邦基金利率用于观察政策利率环境',
                    real_yield: '美国 10 年期实际利率用于观察通胀调整后的利率压力',
                    cpi: 'CPI 用于观察通胀压力',
                    core_cpi: '核心 CPI 用于观察剔除食品能源后的基础通胀压力',
                    m2: 'M2 用于观察美元流动性规模',
                    fed_balance_sheet: '美联储资产负债表用于观察基础流动性环境',
                }[spec.key] || `${spec.name} 用于 Layer A 大周期判断`;
                return unavailableLine(purpose);
            }

            if (spec.key === 'lth_sopr') {
                const state = value > 1.03 ? '长期持有人获利卖出压力较明显'
                    : value >= 1 ? '长期持有人整体处于轻微盈利卖出状态'
                    : '长期持有人仍接近亏损卖出或承压状态';
                return `📊 当前 LTH SOPR ${shown}，${state} 🔍 >1 = 获利卖出，<1 = 亏损卖出。`;
            }
            if (spec.key === 'sth_sopr') {
                const state = value >= 1.03 ? '短期持有人获利释放较明显'
                    : value >= 0.98 ? '短期持有人接近盈亏平衡'
                    : '短期筹码仍处于亏损承压状态';
                return `📊 当前 STH SOPR ${shown}，${state} 🔍 <1 往往代表短期筹码承压。`;
            }
            if (spec.key === 'rhodl_ratio') {
                const state = value >= 10000 ? '大周期估值温度偏热'
                    : value >= 2000 ? '估值温度处于中高区'
                    : '估值温度仍偏低或处在修复区';
                return `📊 当前 RHODL Ratio ${shown}，${state} 🔍 越高越需要警惕周期顶部过热，越低越接近底部估值区。`;
            }
            if (spec.key === 'reserve_risk') {
                const state = value >= 0.02 ? '长期持有者风险回报开始偏热'
                    : value >= 0.005 ? '长期持有者风险回报处于中性区'
                    : '长期持有者信心相对价格风险仍较健康';
                return `📊 当前 Reserve Risk ${shown}，${state} 🔍 低位偏长期吸筹，高位偏周期过热。`;
            }
            if (spec.key === 'puell_multiple') {
                const state = value >= 3 ? '矿工收入相对高企，需警惕周期过热'
                    : value >= 1 ? '矿工收入处于正常扩张区'
                    : '矿工收入偏低，更接近压力释放或底部修复区';
                return `📊 当前 Puell Multiple ${shown}，${state} 🔍 高位常见于过热，低位常见于矿工压力释放。`;
            }
            if (spec.key === 'lth_net_position_change') {
                const state = value > 0 ? '长期持有人净增持，偏筹码沉淀'
                    : value < 0 ? '长期持有人净减持，偏分发压力'
                    : '长期持有人净变化接近 0';
                return `📊 当前 LTH 净头寸变化 ${shown}，${state} 🔍 增持偏累积，减持偏派发。`;
            }
            if (spec.key === 'percent_supply_in_profit') {
                const state = value >= 0.9 ? '绝大多数筹码盈利，需警惕过热'
                    : value >= 0.55 ? '市场多数筹码处于盈利状态'
                    : '盈利筹码比例偏低，更接近压力释放区';
                return `📊 当前盈利供给占比 ${shown}，${state} 🔍 极高时需警惕过热，极低时常见于底部区。`;
            }
            if (spec.key === 'percent_supply_in_loss') {
                const state = value >= 0.5 ? '市场仍有较多筹码承压'
                    : value >= 0.2 ? '市场仍有部分筹码承压'
                    : '亏损筹码占比较低，整体压力较轻';
                return `📊 当前亏损供给占比 ${shown}，${state} 🔍 高亏损占比通常对应恐慌或底部修复阶段。`;
            }
            if (spec.key === 'exchange_balance') {
                return `📊 当前交易所余额 ${shown}，反映可交易供给压力 🔍 余额上升偏卖压，余额下降偏长期持有。`;
            }
            if (spec.key === 'exchange_net_position_change') {
                const state = value > 0 ? '资金净流入交易所，偏卖压'
                    : value < 0 ? '资金净流出交易所，偏囤币'
                    : '净变化接近 0，交易所压力不明显';
                return `📊 当前交易所净头寸变化 ${shown}，${state} 🔍 流入偏卖压，流出偏囤币。`;
            }
            if (spec.key === 'us2y') {
                const state = value >= 4 ? '短端利率压力仍偏高'
                    : value >= 3 ? '短端利率仍有压力但边际可观察'
                    : '短端利率压力相对缓和';
                return `📊 当前美国 2 年期收益率 ${shown}，${state} 🔍 上升通常压制风险资产，下降偏流动性改善。`;
            }
            if (spec.key === 'fed_funds_rate') {
                const state = value >= 4 ? '政策利率环境仍偏紧'
                    : value >= 2 ? '政策利率仍有约束但低于紧缩高峰'
                    : '政策利率环境相对宽松';
                return `📊 当前联邦基金利率 ${shown}，${state} 🔍 高利率通常压制风险资产估值。`;
            }
            if (spec.key === 'real_yield') {
                const state = value >= 2 ? '实际利率压力偏高'
                    : value >= 1 ? '实际利率仍有一定压力'
                    : '实际利率压力相对缓和';
                return `📊 当前美国 10 年期实际利率 ${shown}，${state} 🔍 实际利率上升通常压制 BTC 等风险资产估值。`;
            }
            if (spec.key === 'cpi') {
                return `📊 当前 CPI 为 ${shown}，反映整体通胀水平 🔍 通胀偏高可能限制流动性宽松。`;
            }
            if (spec.key === 'core_cpi') {
                return `📊 当前 Core CPI 为 ${shown}，剔除食品和能源后的核心通胀 🔍 核心通胀偏高通常压制降息预期。`;
            }
            if (spec.key === 'm2') {
                return `📊 当前 M2 为 ${shown}，反映美元流动性规模 🔍 扩张偏利好风险资产，收缩偏压制。`;
            }
            if (spec.key === 'fed_balance_sheet') {
                return `📊 当前美联储资产负债表 ${shown}，反映基础流动性环境 🔍 扩表偏宽松，缩表偏紧缩。`;
            }
            return `📊 当前 ${spec.name} ${shown}，用于 Layer A 大周期判断。`;
        },
        layerAFactorCards() {
            return this.layerAFactorCardSpecs().map(spec => {
                const factor = this.layerAFactorContextValue(spec);
                const unavailableStatus = this.layerAFactorUnavailableStatus(spec.key);
                const status = (factor && factor.status) || unavailableStatus || 'unavailable';
                const hasValue = factor
                    && factor.actual_value !== undefined && factor.actual_value !== null;
                const freshness = (factor && factor.freshness) || {};
                const available = status === 'available' && hasValue && !freshness.is_stale;
                const statusLabel = this.layerAFactorStatusLabel(status, freshness);
                const timestampLabel = this.layerAFactorFetchedAt(factor)
                    || this.layerAFactorCapturedAt(factor);
                const interpretation = this.layerAFactorPlainReading(
                    spec, factor, statusLabel, hasValue,
                );
                return {
                    card_id: 'layer_a_' + spec.key,
                    group: spec.group,
                    tier: 'raw',
                    is_primary: false,
                    name: spec.name,
                    name_en: spec.name_en,
                    current_value: hasValue ? factor.actual_value : null,
                    value_unit: spec.value_unit || '',
                    impact_direction: 'neutral',
                    data_fresh: available && !freshness.is_stale,
                    plain_interpretation: interpretation,
                    linked_layer: 'Layer A',
                    raw_status: status,
                    status_label: statusLabel,
                    captured_at_bjt: this.layerAFactorCapturedAt(factor),
                    fetched_at_bjt: timestampLabel,
                    source: spec.source,
                };
            });
        },
        rawFactorCards() {
            const cards = ((this.state && this.state.factor_cards) || [])
                .filter(c => c.tier !== 'composite');
            return [...cards, ...this.layerAFactorCards()];
        },
        factorGroups() {
            const cards = this.rawFactorCards();
            const specs = [
                { key: 'price_technical',label: '价格技术',  icon: '🕯️', source: 'CoinGlass klines' },
                { key: 'derivatives',    label: '衍生品',    icon: '📈', source: 'CoinGlass' },
                { key: 'onchain',        label: '链上数据',  icon: '⛓️', source: 'Glassnode' },
                { key: 'macro',          label: '宏观',      icon: '🌍', source: 'FRED' },
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
            // v1.3 路径:state.risks.hard_invalidation_levels
            const v13 = this.state && this.state.risks
                        && this.state.risks.hard_invalidation_levels;
            if (Array.isArray(v13) && v13.length > 0) return v13;
            // Sprint K:v1.4 路径 — 从 layer_cards[3](L4)的 supporting_data 抽
            const cards = (this.state && this.state.layer_cards) || [];
            const l4 = cards.find(c => c && c.layer === 'l4');
            const sd = l4 && l4.supporting_data;
            const hi = sd && sd.hard_invalidation_levels;
            if (hi && Array.isArray(hi.value)) return hi.value;
            return [];
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
            if (v == null) return '-';
            return Number(v).toLocaleString(undefined,
                { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' USDT';
        },
        formatPct(v, showSign) {
            if (v == null) return '-';
            const s = Number(v).toFixed(2);
            return (showSign && v >= 0 ? '+' : '') + s + '%';
        },
        formatDrawdownPct(v) {
            if (v == null || isNaN(v)) return '-';
            const n = Number(v);
            if (n === 0) return '0.00%';
            return n.toFixed(2) + '%';
        },
        drawdownColorClass(v) {
            return Number(v) < 0
                ? 'text-rose-600'
                : 'text-slate-700 dark:text-slate-300';
        },
        formatReviewValue(v) {
            if (v == null || v === '') return '-';
            if (Array.isArray(v)) return v.length ? v.join(', ') : '-';
            if (typeof v === 'object') return JSON.stringify(v);
            return String(v);
        },
        formatFactorValue(v) {
            if (v == null) return '-';
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
        shortId(id) { return id ? String(id).slice(0, 8) : '-'; },

        get countdownLabel() {
            if (!this.state || !this.state.meta || !this.state.meta.next_run_eta_bjt) return '-';
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
                PROTECTION: 'bg-red-500 text-white dark:bg-red-700',
                // Sprint 1.10-J commit 4b §X:删 FLIP_WATCH / POST_PROTECTION_REASSESS
                // 颜色映射(v1.4 §11.2);若底层仍输出这两档,fallthrough
                // 到默认灰色样式(graceful)。state_machine 主体重写留 1.10-K
            }[s] || 'bg-slate-100 text-slate-700';
        },

        observationLabel(c) {
            // Sprint 1.10-J commit 6 §X:删 cold_start_warming_up label(observation
            // 4 取值之一,observation_classifier 整删,见 commit 5)
            return {
                disciplined: '纪律性观望', watchful: '正常等待',
                possibly_suppressed: '疑似被压制',
            }[c] || c || '-';
        },
        observationColor(c) {
            // Sprint 1.10-J commit 6 §X:删 cold_start_warming_up 颜色映射
            return {
                disciplined: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
                watchful: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                possibly_suppressed: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
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
        factorStatusLabel(c) {
            if (!c) return '-';
            if (c.status_label) return c.status_label;
            if (c.data_fresh === true) return '可用';
            if (c.data_fresh === false) return '需检查';
            return '-';
        },
        factorStatusLine(c) {
            const layer = c && c.linked_layer ? c.linked_layer : '-';
            return '状态:' + this.factorStatusLabel(c) + ' · ' + layer;
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
            // Sprint 1.10-J commit 6 §X:删 cold_start_tick 类型(v1.4 §11.2)
            return { state_enter: 'bg-blue-500', position_open: 'bg-emerald-500',
                     position_trim: 'bg-amber-400', position_exit: 'bg-slate-400',
                     flip: 'bg-purple-500' }[t] || 'bg-slate-400';
        },
        timelineNodeTypeLabel(t) {
            return { state_enter: '状态', position_open: '开仓', position_trim: '减仓',
                     position_exit: '离场', flip: '切换' }[t] || t;
        },
        timelineNodeBadgeClass(t) {
            // Sprint 1.10-J commit 6 §X:删 cold_start_tick badge
            return {
                state_enter: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                position_open: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                position_trim: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                position_exit: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400',
                flip: 'bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
            }[t] || 'bg-slate-100 text-slate-700';
        },
    };
}
