/* =========================================================================
   app.js — BTC Strategy 审计台(Sprint 2.1 骨架版)

   Alpine.js 全局组件 `app()`,挂在 <html x-data="app()">。
   Sprint 2.1 只走 MOCK 数据(/mock/strategy_current.json)。
   Sprint 2.2 换成 /api/strategy/current + /api/strategy/stream。
   ========================================================================= */

function app() {
    return {
        // ================== 状态 ==================
        state: null,
        loading: true,
        error: null,
        darkMode: false,
        nowBjt: '',           // 顶栏实时 BJT 时钟
        _tickTimer: null,

        // 手风琴(默认全部折叠)
        layerOpen: { 1: false, 2: false, 3: false, 4: false, 5: false },

        // 证据卡片 tab(默认第一个)
        activeCategory: 'price_structure',

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
        },

        // ================== Dark / Light ==================
        _initDarkMode() {
            // ?theme=dark / ?theme=light 查询参数优先(供截图 / 预览用)
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
            // 本地浏览器时区可能不是 BJT,强制转换到 UTC+8
            const now = new Date();
            const bjt = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
            const pad = (n) => String(n).padStart(2, '0');
            return `${bjt.getFullYear()}-${pad(bjt.getMonth() + 1)}-${pad(bjt.getDate())} ` +
                   `${pad(bjt.getHours())}:${pad(bjt.getMinutes())}:${pad(bjt.getSeconds())} (BJT)`;
        },

        // 对外暴露的 BJT 格式工具
        formatBJT(isoString) {
            if (!isoString) return '';
            const d = new Date(isoString);
            if (isNaN(d.getTime())) return isoString;  // 已经是 BJT 字符串的情况
            const bjt = new Date(d.getTime() + (d.getTimezoneOffset() + 480) * 60000);
            const pad = (n) => String(n).padStart(2, '0');
            return `${bjt.getFullYear()}-${pad(bjt.getMonth() + 1)}-${pad(bjt.getDate())} ` +
                   `${pad(bjt.getHours())}:${pad(bjt.getMinutes())} (BJT)`;
        },

        // ================== 数据加载 ==================
        async _loadState() {
            this.loading = true;
            this.error = null;
            try {
                const res = await fetch('/mock/strategy_current.json', { cache: 'no-cache' });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.state = await res.json();
            } catch (e) {
                this.error = String(e.message || e);
                console.error('[app] loadState failed:', e);
            } finally {
                this.loading = false;
            }
        },

        // ================== 格式化工具 ==================
        formatPrice(v) {
            if (v == null) return '-';
            return '$' + Number(v).toLocaleString(undefined, {
                minimumFractionDigits: 2, maximumFractionDigits: 2,
            });
        },
        formatPct(v, showSign) {
            if (v == null) return '-';
            const s = Number(v).toFixed(2);
            return (showSign && v >= 0 ? '+' : '') + s + '%';
        },
        shortId(id) {
            if (!id) return '-';
            return String(id).slice(0, 8);
        },

        // ================== 倒计时(next_run)==================
        get countdownLabel() {
            if (!this.state || !this.state.meta.next_run_eta_bjt) return '-';
            // 从 "2026-04-24 15:39 (BJT)" 解析
            const m = String(this.state.meta.next_run_eta_bjt).match(
                /(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/,
            );
            if (!m) return this.state.meta.next_run_eta_bjt;
            // BJT (UTC+8) → UTC
            const eta = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 8, +m[5]);
            const diff = eta - Date.now();
            if (diff <= 0) return '即将运行';
            const hours = Math.floor(diff / 3600000);
            const mins = Math.floor((diff % 3600000) / 60000);
            if (hours > 0) return `${hours}h ${mins}m 后`;
            return `${mins}m 后`;
        },

        // ================== 颜色 / 标签映射 ==================
        stateColor(state) {
            const map = {
                'FLAT':                       'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200',
                'LONG_PLANNED':               'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                'LONG_OPEN':                  'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200',
                'LONG_HOLD':                  'bg-blue-200 text-blue-900 dark:bg-blue-800 dark:text-blue-100',
                'LONG_TRIM':                  'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
                'LONG_EXIT':                  'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
                'SHORT_PLANNED':              'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
                'SHORT_OPEN':                 'bg-rose-100 text-rose-700 dark:bg-rose-900 dark:text-rose-200',
                'SHORT_HOLD':                 'bg-rose-200 text-rose-900 dark:bg-rose-800 dark:text-rose-100',
                'SHORT_TRIM':                 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                'SHORT_EXIT':                 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
                'FLIP_WATCH':                 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300',
                'PROTECTION':                 'bg-red-500 text-white dark:bg-red-700',
                'POST_PROTECTION_REASSESS':   'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300',
            };
            return map[state] || 'bg-gray-100 text-gray-700';
        },

        observationLabel(cat) {
            return {
                'disciplined':            '纪律性观望',
                'watchful':               '正常等待',
                'possibly_suppressed':    '疑似被压制',
                'cold_start_warming_up':  '冷启动升温中',
            }[cat] || cat;
        },
        observationColor(cat) {
            return {
                'disciplined':            'bg-gray-100 text-gray-700 dark:bg-dark-card dark:text-gray-300',
                'watchful':               'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                'possibly_suppressed':    'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                'cold_start_warming_up':  'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300',
            }[cat] || 'bg-gray-100 text-gray-700';
        },
        observationBorderClass(cat) {
            return {
                'disciplined':            'border-gray-400',
                'watchful':               'border-blue-400 dark:border-blue-500',
                'possibly_suppressed':    'border-amber-500',
                'cold_start_warming_up':  'border-cyan-400 dark:border-cyan-500',
            }[cat] || 'border-gray-300';
        },
        observationExplanation(cat) {
            return {
                'disciplined':
                    '纪律性观望 —— 证据明确不利于开仓,系统正确地保持观望。',
                'watchful':
                    '正常等待 —— 证据有正面因素但不足以开仓,继续观察。',
                'possibly_suppressed':
                    '疑似被压制 —— 多项正面证据已存在但仍无机会,需要关注是否门槛过严。',
                'cold_start_warming_up':
                    '冷启动升温中 —— 系统运行不足 7 天,KPI 不累计,仓位额外折减一半。',
            }[cat] || cat;
        },

        healthColor(status) {
            return {
                'green':  'bg-emerald-500',
                'yellow': 'bg-amber-400',
                'red':    'bg-rose-500',
            }[status] || 'bg-gray-400';
        },

        freshnessColor(status) {
            // §9.9:绿(< 1h)/ 黄(1-6h)/ 红(> 6h)
            return {
                'green':  'bg-emerald-500',
                'yellow': 'bg-amber-400',
                'red':    'bg-rose-500',
            }[status] || 'bg-gray-400';
        },

        fallbackLabel(level) {
            if (!level) return '正常';
            return {
                'level_1': 'L1 保守保持',
                'level_2': 'L2 防御性干预',
                'level_3': 'L3 紧急保护',
            }[level] || level;
        },
        fallbackLabelClass(level) {
            if (!level) return 'text-emerald-600 dark:text-emerald-400';
            return {
                'level_1': 'text-amber-600 dark:text-amber-400',
                'level_2': 'text-orange-600 dark:text-orange-400',
                'level_3': 'text-rose-600 dark:text-rose-400',
            }[level] || 'text-gray-500';
        },

        contributionLabel(c) {
            return {
                'supportive':  '支持',
                'neutral':     '中性',
                'challenging': '质疑',
                'blocking':    '阻止',
            }[c] || c;
        },
        contributionClass(c) {
            return {
                'supportive':  'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                'neutral':     'bg-gray-100 text-gray-600 dark:bg-dark-card dark:text-gray-400',
                'challenging': 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                'blocking':    'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
            }[c] || 'bg-gray-100 text-gray-600';
        },

        directionClass(d) {
            return {
                'bullish': 'text-emerald-600 dark:text-emerald-400',
                'bearish': 'text-rose-600 dark:text-rose-400',
                'neutral': 'text-gray-500 dark:text-gray-400',
            }[d] || 'text-gray-500';
        },

        layerChineseName(id) {
            return ['市场状态', '方向结构', '机会执行', '风险失效', '背景事件'][id - 1] || '';
        },

        timelineNodeColor(type) {
            return {
                'state_enter':       'bg-blue-500',
                'position_open':     'bg-emerald-500',
                'position_trim':     'bg-amber-400',
                'position_exit':     'bg-gray-400',
                'flip':              'bg-purple-500',
                'cold_start_tick':   'bg-cyan-400',
            }[type] || 'bg-gray-400';
        },
        timelineNodeTypeLabel(type) {
            return {
                'state_enter':       '状态',
                'position_open':     '开仓',
                'position_trim':     '减仓',
                'position_exit':     '离场',
                'flip':              '切换',
                'cold_start_tick':   '冷启动',
            }[type] || type;
        },
        timelineNodeBadgeClass(type) {
            return {
                'state_enter':       'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
                'position_open':     'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                'position_trim':     'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
                'position_exit':     'bg-gray-100 text-gray-700 dark:bg-dark-card dark:text-gray-400',
                'flip':              'bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
                'cold_start_tick':   'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300',
            }[type] || 'bg-gray-100 text-gray-700';
        },

        // ================== 手风琴 ==================
        toggleLayer(layerId) {
            this.layerOpen[layerId] = !this.layerOpen[layerId];
        },
        orderedLayers() {
            if (!this.state) return [];
            const es = this.state.evidence_summary;
            return [es.layer_1, es.layer_2, es.layer_3, es.layer_4, es.layer_5]
                .filter(Boolean);
        },

        // ================== 证据卡片筛选 ==================
        cardsByCategory(category) {
            if (!this.state || !this.state.evidence_cards) return [];
            return this.state.evidence_cards.filter(c => c.category === category);
        },

        // 点击论据亮点跳转到对应证据卡
        jumpToCard(cardId) {
            if (!cardId) return;
            const target = document.getElementById('card-' + cardId);
            if (!target) {
                console.warn('[app] jumpToCard: not found', cardId);
                return;
            }
            // 先切换 tab 到对应类别
            const card = (this.state.evidence_cards || []).find(c => c.card_id === cardId);
            if (card) this.activeCategory = card.category;
            // 等 DOM 渲染完再滚
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
