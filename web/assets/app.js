/* =========================================================================
   app.js — BTC Strategy 审计台(Sprint 1.8.2-B)

   消费 Sprint 1.8.2-A 后端 normalize_state 输出的统一 schema:
     state.schema_version
     state.summary_card
     state.layer_cards[]
     state.anti_patterns_active[]
     state.extreme_events_active[]
     state.raw  (调试用,前端不渲染)

   不引入新框架,继续 Alpine.js + Tailwind CDN。
   ========================================================================= */

function app() {
    return {
        // ============== 顶部状态 ==============
        loading: true,
        darkMode: false,
        nowBjt: '',
        dataSource: 'api',

        // BTC 价格(从 /api/market/btc-price)
        btcPrice: '—',
        btc24hChangePct: null,
        btc24hChangeText: '',
        btcSource: '',

        // ============== 主 schema 字段(从 /api/strategy/current 来)==============
        runId: '',
        schemaVersion: '',
        decisionTime: '',
        headline: '',
        actionStateLabel: '',
        stanceLabel: '',
        validatorPassed: null,

        layerCards: [],
        antiPatternsActive: [],
        extremeEventsActive: [],

        // 🩺 系统自检(独立 endpoint /api/system/health-detail)
        systemHealth: null,

        // 卡片展开状态(每张卡独立 boolean)
        cardOpen: {},

        // ============== 初始化 ==============
        init() {
            this.darkMode = (localStorage.getItem('btc_dark') === '1');
            this.tickClock();
            setInterval(() => this.tickClock(), 1000);
            this.fetchBtcPrice();
            this.fetchStrategy();
            this.fetchSystemHealth();
            // 30 秒轮询(简单可靠;SSE 旧版有,这里先用 polling)
            setInterval(() => {
                this.fetchBtcPrice();
                this.fetchStrategy();
                this.fetchSystemHealth();
            }, 30000);
        },

        // ============== 主题 ==============
        toggleDark() {
            this.darkMode = !this.darkMode;
            localStorage.setItem('btc_dark', this.darkMode ? '1' : '0');
        },

        // ============== 时钟 ==============
        tickClock() {
            const now = new Date();
            const bjt = new Date(now.getTime() + (8 * 60 - now.getTimezoneOffset()) * 60 * 1000);
            const fmt = bjt.toISOString().slice(0, 16).replace('T', ' ');
            this.nowBjt = `${fmt} BJT`;
        },

        // ============== 价格 ==============
        async fetchBtcPrice() {
            try {
                const r = await fetch('/api/market/btc-price', {credentials: 'include'});
                if (!r.ok) return;
                const d = await r.json();
                if (d.price != null) {
                    this.btcPrice = '$' + d.price.toLocaleString('en-US',
                        {minimumFractionDigits: 0, maximumFractionDigits: 0});
                }
                this.btc24hChangePct = d.price_24h_change_pct;
                if (d.price_24h_change_pct != null) {
                    const s = d.price_24h_change_pct >= 0 ? '+' : '';
                    this.btc24hChangeText = `${s}${d.price_24h_change_pct.toFixed(2)}% (24h)`;
                }
                this.btcSource = (d.source || '').replace(/_via_.*/, '');
            } catch (e) {
                console.warn('fetchBtcPrice failed:', e);
            }
        },

        // ============== 主策略 ==============
        async fetchStrategy() {
            this.loading = true;
            try {
                const r = await fetch('/api/strategy/current', {credentials: 'include'});
                if (!r.ok) {
                    console.warn('strategy current HTTP', r.status);
                    this.loading = false;
                    return;
                }
                const data = await r.json();
                this.runId = data.run_id || '';
                const state = data.state || {};
                this.applyState(state);
                this.loading = false;
            } catch (e) {
                console.warn('fetchStrategy failed:', e);
                this.loading = false;
            }
        },

        applyState(state) {
            // schema_version
            this.schemaVersion = state.schema_version || 'unknown';

            // summary_card
            const sc = state.summary_card || {};
            this.headline = sc.headline || '—';
            this.actionStateLabel = sc.action_state_label || '—';
            this.stanceLabel = sc.stance_label || '—';
            this.decisionTime = sc.decision_time || '';
            this.validatorPassed = sc.validator_passed;

            // layer_cards
            this.layerCards = Array.isArray(state.layer_cards) ? state.layer_cards : [];

            // 警告
            this.antiPatternsActive = state.anti_patterns_active || [];
            this.extremeEventsActive = state.extreme_events_active || [];

            // cardOpen 默认全 false(密度 C)
            this.cardOpen = {};
            this.layerCards.forEach((_, i) => { this.cardOpen[i] = false; });
        },

        // ============== 卡片展开 ==============
        toggleCard(idx) {
            this.cardOpen[idx] = !this.cardOpen[idx];
        },

        // ============== 🩺 系统自检 ==============
        async fetchSystemHealth() {
            try {
                const r = await fetch('/api/system/health-detail',
                                       {credentials: 'include'});
                if (!r.ok) return;
                this.systemHealth = await r.json();
            } catch (e) {
                console.warn('fetchSystemHealth failed:', e);
            }
        },

        layerHealthGlyph(health) {
            // ● healthy / ⚠ degraded / ✗ missing/critical
            if (health === 'healthy') return '●';
            if (health === 'degraded') return '⚠';
            return '✗';
        },

        sourceStatusGlyph(status) {
            if (status === 'fresh' || status === 'ok') return '●';
            if (status === 'stale' || status === 'degraded') return '⚠';
            return '✗';
        },

        // ============== 数据格式化(supporting_data 表用)==============
        formatValue(v) {
            if (v === null || v === undefined) return '—';
            if (typeof v === 'number') {
                if (Number.isInteger(v)) return v.toLocaleString('en-US');
                return v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
            }
            if (typeof v === 'string') return v;
            if (typeof v === 'boolean') return v ? '是' : '否';
            if (Array.isArray(v)) {
                if (v.length === 0) return '空';
                // 数组:简单 join
                return v.map(item => {
                    if (typeof item === 'object') return JSON.stringify(item);
                    return String(item);
                }).join(' / ');
            }
            if (typeof v === 'object') {
                // 对象:展示 key:value 简短
                try {
                    const entries = Object.entries(v).slice(0, 4);
                    return entries.map(([k, vv]) => {
                        const vs = typeof vv === 'object' ? JSON.stringify(vv) : String(vv);
                        return `${k}=${vs}`;
                    }).join(', ');
                } catch (e) {
                    return JSON.stringify(v);
                }
            }
            return String(v);
        },
    };
}
