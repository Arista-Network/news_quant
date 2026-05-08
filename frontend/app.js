document.addEventListener('DOMContentLoaded', () => {

    // ===== Dark Mode =====
    const themeBtn = document.getElementById('theme-toggle');
    const savedTheme = localStorage.getItem('theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const applyTheme = (t) => {
        document.body.classList.toggle('dark', t === 'dark');
        themeBtn.textContent = t === 'dark' ? '☀️' : '🌙';
    };
    applyTheme(savedTheme);
    themeBtn.addEventListener('click', () => {
        const next = document.body.classList.contains('dark') ? 'light' : 'dark';
        applyTheme(next);
        localStorage.setItem('theme', next);
        if (heatmapChart) heatmapChart.resize();
        if (trendChart) trendChart.resize();
        if (miniChart) miniChart.resize();
    });

    // ===== Watchlist (localStorage) =====
    const WATCHLIST_KEY = 'nq_watchlist_v2';
    function getWatchlist() { return JSON.parse(localStorage.getItem(WATCHLIST_KEY) || '[]'); }
    function saveWatchlist(list) { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list)); }
    function toggleWatch(ticker, name) {
        const list = getWatchlist();
        const idx = list.findIndex(w => w.ticker === ticker);
        if (idx >= 0) { list.splice(idx, 1); } else { list.unshift({ ticker, name }); }
        saveWatchlist(list);
        renderWatchlist();
        return idx < 0;
    }
    function isWatched(ticker) { return getWatchlist().some(w => w.ticker === ticker); }

    function renderWatchlist() {
        const section = document.getElementById('watchlist-section');
        const container = document.getElementById('watchlist-items');
        const list = getWatchlist();
        if (list.length === 0) { section.classList.add('hidden'); return; }
        section.classList.remove('hidden');
        container.innerHTML = list.map(w => `
            <div class="wl-chip" data-ticker="${w.ticker}" data-name="${w.name}">
                <span class="wl-name">${w.name}</span>
                <span class="wl-code">${w.ticker}</span>
                <button class="wl-remove" data-ticker="${w.ticker}" title="삭제">×</button>
            </div>`).join('');
        container.querySelectorAll('.wl-chip').forEach(chip => {
            chip.addEventListener('click', e => {
                if (e.target.classList.contains('wl-remove')) return;
                openStockPanel(chip.dataset.ticker, chip.dataset.name);
            });
        });
        container.querySelectorAll('.wl-remove').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                toggleWatch(btn.dataset.ticker, '');
                document.querySelectorAll(`.star-btn[data-ticker="${btn.dataset.ticker}"]`)
                    .forEach(s => s.classList.remove('starred'));
            });
        });
    }

    document.getElementById('watchlist-clear')?.addEventListener('click', () => {
        saveWatchlist([]);
        renderWatchlist();
        document.querySelectorAll('.star-btn.starred').forEach(s => s.classList.remove('starred'));
    });
    renderWatchlist();

    // ===== Tab Navigation =====
    const tabBtns     = document.querySelectorAll('.tab-btn');
    const mnavBtns    = document.querySelectorAll('.mnav-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    let heatmapLoaded = false;
    let etfLoaded     = false;
    let screenerLoaded = false;

    function activateTab(tabName) {
        tabBtns.forEach(b  => b.classList.toggle('active', b.dataset.tab === tabName));
        mnavBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
        tabContents.forEach(c => c.classList.remove('active'));
        document.getElementById(`tab-${tabName}`)?.classList.add('active');

        if (tabName === 'heatmap' && !heatmapLoaded) {
            loadHeatmap('KOSPI', currentPeriod);
            loadTrendChart('KOSPI', currentPeriod);
            heatmapLoaded = true;
        }
        if (tabName === 'etf' && !etfLoaded) {
            loadETFTab();
            etfLoaded = true;
        }
        if (tabName === 'screener' && !screenerLoaded) {
            // screener loaded on demand
        }
    }

    tabBtns.forEach(btn  => btn.addEventListener('click', () => activateTab(btn.dataset.tab)));
    mnavBtns.forEach(btn => btn.addEventListener('click', () => activateTab(btn.dataset.tab)));

    // ===== Market toggle (heatmap) =====
    document.querySelectorAll('.market-btn:not([data-smarket])').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.market-btn:not([data-smarket])').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            if (_heatmapPollTimer) clearTimeout(_heatmapPollTimer);
            if (_trendPollTimer)   clearTimeout(_trendPollTimer);
            const market = btn.dataset.market;
            loadHeatmap(market, currentPeriod);
            loadTrendChart(market, currentPeriod);
        });
    });

    // ===== Period toggle =====
    let currentPeriod = 7;
    const PERIOD_LABELS       = { 1:'최근 1일', 7:'최근 7일', 30:'최근 30일', 365:'최근 1년(주간)' };
    const PERIOD_TABLE_LABELS = { 1:'당일', 7:'최근 7일', 30:'최근 30일', 365:'최근 60거래일' };

    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentPeriod = parseInt(btn.dataset.period, 10);
            const pLabel = document.getElementById('trend-period-label');
            if (pLabel) pLabel.textContent = PERIOD_LABELS[currentPeriod] || '';
            const tLabel = document.getElementById('flow-table-period-label');
            if (tLabel) tLabel.textContent = `(${PERIOD_TABLE_LABELS[currentPeriod]} 합산)`;
            const market = document.querySelector('.market-btn:not([data-smarket]).active')?.dataset.market || 'KOSPI';
            if (_heatmapPollTimer) clearTimeout(_heatmapPollTimer);
            if (_trendPollTimer)   clearTimeout(_trendPollTimer);
            loadHeatmap(market, currentPeriod);
            loadTrendChart(market, currentPeriod);
        });
    });

    // ===== Refresh buttons =====
    document.getElementById('refresh-rebal')?.addEventListener('click', () => loadRebalancing());

    // ─────────────────────────────────────────────
    // ===== SMART MONEY RADAR =====
    // ─────────────────────────────────────────────
    async function loadSmartRadar() {
        try {
            const res  = await fetch('/api/market-flow?market=KOSPI&period=7');
            const json = await res.json();
            if (json.status !== 'success' || !json.data?.length) return;
            renderSmartRadar(json.data);
        } catch { /* silent */ }
    }

    function renderSmartRadar(data) {
        const radarEl = document.getElementById('smart-radar');
        const colsEl  = document.getElementById('radar-cols');
        if (!data.length) return;

        const topForeigner  = [...data].sort((a,b) => b.foreigner - a.foreigner).slice(0,3);
        const topInstitution= [...data].sort((a,b) => b.institution - a.institution).slice(0,3);
        const topBoth       = [...data]
            .filter(d => d.foreigner > 0 && d.institution > 0)
            .sort((a,b) => b.total - a.total).slice(0,3);

        const mkGroup = (title, icon, items, colorClass) => `
            <div class="radar-group">
                <div class="radar-group-title ${colorClass}">${icon} ${title}</div>
                ${items.map(d => `
                    <div class="radar-chip" data-ticker="${d.code}" data-name="${d.name}">
                        <span class="radar-chip-name">${d.name}</span>
                        <span class="radar-chip-val ${colorClass}">${fmtWon(d.foreigner > d.institution ? d.foreigner : d.institution)}</span>
                    </div>`).join('')}
            </div>`;

        colsEl.innerHTML = [
            mkGroup('외국인 TOP', '🌍', topForeigner,   'radar-blue'),
            mkGroup('기관 TOP',   '🏦', topInstitution, 'radar-orange'),
            mkGroup('동시매수',   '🔥', topBoth,        'radar-green'),
        ].join('');

        colsEl.querySelectorAll('.radar-chip').forEach(chip => {
            chip.addEventListener('click', () => openStockPanel(chip.dataset.ticker, chip.dataset.name));
        });

        radarEl.classList.remove('hidden');
    }

    function fmtWon(val) {
        if (!val) return '-';
        const abs = Math.abs(val);
        let d;
        if (abs >= 1e12)     d = (val/1e12).toFixed(1)+'조';
        else if (abs >= 1e8) d = (val/1e8).toFixed(1)+'억';
        else if (abs >= 1e4) d = (val/1e4).toFixed(0)+'만';
        else                 d = val.toLocaleString();
        return (val > 0 ? '+' : '') + d;
    }

    // ─────────────────────────────────────────────
    // ===== STOCK DETAIL PANEL =====
    // ─────────────────────────────────────────────
    let miniChart = null;
    const panelEl      = document.getElementById('stock-panel');
    const panelOverlay = document.getElementById('panel-overlay');
    const panelClose   = document.getElementById('panel-close');
    const panelLoading = document.getElementById('panel-loading');
    const panelContent = document.getElementById('panel-content');

    function openStockPanel(ticker, name) {
        document.getElementById('panel-name').textContent   = name;
        document.getElementById('panel-ticker').textContent = ticker;
        panelLoading.classList.remove('hidden');
        panelContent.classList.add('hidden');
        panelEl.classList.add('open');
        document.body.style.overflow = 'hidden';
        loadStockDetail(ticker, name);
    }

    function closeStockPanel() {
        panelEl.classList.remove('open');
        document.body.style.overflow = '';
    }

    panelOverlay?.addEventListener('click', closeStockPanel);
    panelClose?.addEventListener('click',  closeStockPanel);

    async function loadStockDetail(ticker, name) {
        try {
            const res  = await fetch(`/api/stock/${ticker}`);
            const json = await res.json();
            if (json.status !== 'success' || !json.data) {
                panelLoading.innerHTML = '<p style="color:var(--red);padding:1rem">데이터를 불러오지 못했습니다.</p>';
                return;
            }
            panelLoading.classList.add('hidden');
            panelContent.classList.remove('hidden');
            renderMiniChart(json.data.price_history);
            renderPanelQuant(json.data.quant, name);
        } catch {
            panelLoading.innerHTML = '<p style="color:var(--red);padding:1rem">오류가 발생했습니다.</p>';
        }
    }

    function renderMiniChart(history) {
        const container = document.getElementById('mini-chart');
        if (miniChart) { miniChart.dispose(); miniChart = null; }
        if (!history?.length) { container.innerHTML = ''; return; }

        miniChart = echarts.init(container, document.body.classList.contains('dark') ? 'dark' : null);
        const dates  = history.map(h => `${h.date.slice(4,6)}/${h.date.slice(6,8)}`);
        const prices = history.map(h => h.close);
        const first  = prices[0], last = prices[prices.length-1];
        const lineColor = last >= first ? '#10b981' : '#ef4444';

        miniChart.setOption({
            backgroundColor: 'transparent',
            grid: { top:8, right:8, bottom:24, left:56 },
            xAxis: { type:'category', data:dates, axisLabel:{fontSize:9, interval:Math.floor(dates.length/6)}, axisTick:{show:false} },
            yAxis: {
                type:'value', scale:true,
                axisLabel: { fontSize:9, formatter: v => v.toLocaleString() },
                splitLine: { lineStyle:{type:'dashed', opacity:0.3} }
            },
            series: [{
                type:'line', data:prices, smooth:true, symbol:'none',
                lineStyle:{ color:lineColor, width:2 },
                areaStyle:{ color:{ type:'linear', x:0,y:0,x2:0,y2:1,
                    colorStops:[{offset:0,color:lineColor+'55'},{offset:1,color:lineColor+'05'}] } }
            }],
            tooltip:{ trigger:'axis', formatter: p => `${p[0].axisValue}: <b>${p[0].value.toLocaleString()}원</b>` }
        });
    }

    function renderPanelQuant(q, name) {
        const wrap = document.getElementById('panel-quant-wrap');
        if (!q) { wrap.innerHTML = ''; return; }
        const sigLabels = { STRONG_BUY:'강력 매수', BUY:'매수 관점', SELL:'매도 관점', STRONG_SELL:'강력 매도', NEUTRAL:'중립' };
        const maStatus  = q.ma5>q.ma20&&q.ma20>q.ma60&&q.ma60>0 ? '정배열 ↑' :
                          q.ma5<q.ma20&&q.ma20<q.ma60&&q.ma5>0  ? '역배열 ↓' : '혼조';
        const maClass   = q.ma5>q.ma20&&q.ma20>q.ma60 ? 'pos' : q.ma5<q.ma20&&q.ma20<q.ma60 ? 'neg' : '';

        wrap.innerHTML = `
            <div class="panel-quant-grid">
                <div class="pq-row">
                    <span class="pq-label">시그널</span>
                    <span class="qc-signal-badge" data-sig="${q.signal}">${sigLabels[q.signal]||'중립'}</span>
                </div>
                <div class="pq-row">
                    <span class="pq-label">퀀트 스코어</span>
                    <span class="pq-val">${q.score > 0 ? '+' : ''}${q.score}</span>
                </div>
                <div class="pq-row">
                    <span class="pq-label">RSI</span>
                    <span class="pq-val ${q.rsi<=30?'pos':q.rsi>=70?'neg':''}">${q.rsi}</span>
                </div>
                <div class="pq-row">
                    <span class="pq-label">MACD</span>
                    <span class="pq-val ${q.macd>=0?'pos':'neg'}">${q.macd>0?'+':''}${q.macd}</span>
                </div>
                <div class="pq-row">
                    <span class="pq-label">MA 배열</span>
                    <span class="pq-val ${maClass}">${maStatus}</span>
                </div>
                <div class="pq-row">
                    <span class="pq-label">외국인</span>
                    <span class="pq-val ${q.foreigner_net>0?'pos':q.foreigner_net<0?'neg':'neutral'}">${q.foreigner_net?fmtWon(q.foreigner_net)+'원':'-'}</span>
                </div>
                <div class="pq-row">
                    <span class="pq-label">기관</span>
                    <span class="pq-val ${q.institution_net>0?'pos':q.institution_net<0?'neg':'neutral'}">${q.institution_net?fmtWon(q.institution_net)+'원':'-'}</span>
                </div>
            </div>
            ${q.reason?.length ? `<ul class="qc-reasons panel-reasons">${q.reason.map(r=>`<li>${r}</li>`).join('')}</ul>` : ''}
            <div class="panel-watchlist-row">
                <button class="panel-watch-btn ${isWatched(q.ticker)?'starred':''}" id="panel-watch-btn" data-ticker="${q.ticker}" data-name="${name}">
                    ${isWatched(q.ticker) ? '⭐ 관심 종목 해제' : '☆ 관심 종목 추가'}
                </button>
            </div>`;

        document.getElementById('panel-watch-btn')?.addEventListener('click', function() {
            const added = toggleWatch(this.dataset.ticker, this.dataset.name);
            this.textContent = added ? '⭐ 관심 종목 해제' : '☆ 관심 종목 추가';
            this.classList.toggle('starred', added);
            document.querySelectorAll(`.star-btn[data-ticker="${this.dataset.ticker}"]`)
                .forEach(s => s.classList.toggle('starred', added));
        });
    }

    // ─────────────────────────────────────────────
    // ===== NEWS FEED =====
    // ─────────────────────────────────────────────
    const newsFeed = document.getElementById('news-feed');
    const loadFeed = document.getElementById('loading-feed');
    const newsTpl  = document.getElementById('news-tpl');
    const quantTpl = document.getElementById('quant-tpl');

    const CATEGORY_COLORS = {
        '실적':    { bg:'#dbeafe', fg:'#1d4ed8' },
        'M&A':     { bg:'#ede9fe', fg:'#6d28d9' },
        '수급':    { bg:'#d1fae5', fg:'#065f46' },
        'ETF':     { bg:'#fef3c7', fg:'#92400e' },
        '거시경제': { bg:'#f1f5f9', fg:'#334155' },
        '규제':    { bg:'#fee2e2', fg:'#991b1b' },
        '일반':    { bg:'#f8fafc', fg:'#64748b' },
    };

    async function fetchNews() {
        try {
            const res  = await fetch('/api/news');
            const json = await res.json();
            if (json.status === 'success') renderFeed(json.data);
            else throw new Error('API error');
        } catch {
            loadFeed.innerHTML = '<p style="color:var(--red);padding:1rem">데이터 로딩 실패. 새로고침 해주세요.</p>';
        }
        loadSmartRadar();
    }

    function renderFeed(items) {
        loadFeed.classList.add('hidden');
        newsFeed.classList.remove('hidden');
        newsFeed.innerHTML = '';

        items.forEach(item => {
            const card = newsTpl.content.cloneNode(true);

            card.querySelector('.news-source').textContent = item.source || '뉴스';
            const pubDate = new Date(item.published);
            card.querySelector('.news-time').textContent = isNaN(pubDate) ? item.published : formatTime(pubDate);

            const catTag = card.querySelector('.category-tag');
            if (item.category && item.category !== '일반') {
                const c = CATEGORY_COLORS[item.category] || CATEGORY_COLORS['일반'];
                catTag.textContent = item.is_etf_rebal ? '🔄 ETF' : item.category;
                catTag.style.background = c.bg;
                catTag.style.color      = c.fg;
            } else { catTag.style.display = 'none'; }

            const sentTag = card.querySelector('.sentiment-tag');
            if (item.sentiment) {
                const s = item.sentiment;
                sentTag.textContent = s.label === 'POSITIVE' ? `긍정 +${s.score}` :
                                      s.label === 'NEGATIVE' ? `부정 ${s.score}` : '중립';
                sentTag.setAttribute('data-s', s.label);
            } else { sentTag.style.display = 'none'; }

            const linkEl = card.querySelector('.news-title a');
            linkEl.textContent = item.title;
            linkEl.href        = item.link;
            card.querySelector('.news-summary').textContent = item.summary;

            const qSection = card.querySelector('.quant-section');
            if (item.quant_data && item.quant_data.length > 0) {
                item.quant_data.forEach(q => {
                    const qc = quantTpl.content.cloneNode(true);

                    const nameEl = qc.querySelector('.qc-name');
                    nameEl.textContent = q.name;
                    nameEl.style.cursor = 'pointer';
                    nameEl.title = '상세 보기';
                    nameEl.addEventListener('click', () => openStockPanel(q.ticker, q.name));

                    qc.querySelector('.qc-ticker').textContent = q.ticker;
                    qc.querySelector('.qc-price').textContent  = q.current_price.toLocaleString() + '원';

                    // Star button
                    const starBtn = document.createElement('button');
                    starBtn.className = `star-btn${isWatched(q.ticker) ? ' starred' : ''}`;
                    starBtn.dataset.ticker = q.ticker;
                    starBtn.dataset.name   = q.name;
                    starBtn.title = '관심 종목';
                    starBtn.textContent = isWatched(q.ticker) ? '⭐' : '☆';
                    starBtn.addEventListener('click', function() {
                        const added = toggleWatch(this.dataset.ticker, this.dataset.name);
                        document.querySelectorAll(`.star-btn[data-ticker="${this.dataset.ticker}"]`)
                            .forEach(s => {
                                s.classList.toggle('starred', added);
                                s.textContent = added ? '⭐' : '☆';
                            });
                    });
                    qc.querySelector('.qc-name-wrap').appendChild(starBtn);

                    const chEl  = qc.querySelector('.qc-change');
                    const chVal = q.change_rate;
                    chEl.textContent = (chVal > 0 ? '+' : '') + chVal + '%';
                    chEl.classList.add(chVal >= 0 ? 'up' : 'down');

                    const sigLabels = { STRONG_BUY:'강력 매수', BUY:'매수 관점', SELL:'매도 관점', STRONG_SELL:'강력 매도', NEUTRAL:'중립' };
                    const sigBadge  = qc.querySelector('.qc-signal-badge');
                    sigBadge.textContent = sigLabels[q.signal] || '중립';
                    sigBadge.setAttribute('data-sig', q.signal);
                    qc.querySelector('.qc-score-badge').textContent = `Score ${q.score > 0 ? '+' : ''}${q.score}`;

                    qc.querySelector('.rsi-bar').style.width = `${Math.min(q.rsi, 100)}%`;
                    qc.querySelector('.ind-item:nth-child(1) .ind-val').textContent = q.rsi;

                    const macdEl = qc.querySelector('.macd-val');
                    macdEl.textContent = q.macd > 0 ? `+${q.macd}` : q.macd;
                    macdEl.classList.add(q.macd >= 0 ? 'up' : 'down');

                    qc.querySelector('.stoch-bar').style.width = `${Math.min(q.stoch_k, 100)}%`;
                    qc.querySelector('.stoch-val').textContent  = q.stoch_k;

                    setSmVal(qc.querySelector('.foreigner-val'),   q.foreigner_net);
                    setSmVal(qc.querySelector('.institution-val'), q.institution_net);

                    const maEl = qc.querySelector('.ma-status');
                    if (q.ma5 > q.ma20 && q.ma20 > q.ma60 && q.ma60 > 0) {
                        maEl.textContent = '정배열 ↑'; maEl.classList.add('pos');
                    } else if (q.ma5 < q.ma20 && q.ma20 < q.ma60 && q.ma5 > 0) {
                        maEl.textContent = '역배열 ↓'; maEl.classList.add('neg');
                    } else { maEl.textContent = '혼조'; }

                    const ul = qc.querySelector('.qc-reasons');
                    (q.reason || []).forEach(r => {
                        const li = document.createElement('li');
                        li.textContent = r;
                        ul.appendChild(li);
                    });

                    qSection.appendChild(qc);
                });
            } else { qSection.style.display = 'none'; }

            newsFeed.appendChild(card);
        });
    }

    function setSmVal(el, val) {
        if (!el) return;
        el.classList.remove('neutral', 'pos', 'neg');
        if (!val || val === 0) { el.textContent = '-'; el.classList.add('neutral'); return; }
        const abs = Math.abs(val);
        let display;
        if (abs >= 1e12)     display = (val/1e12).toFixed(1)+'조';
        else if (abs >= 1e8) display = (val/1e8).toFixed(1)+'억';
        else if (abs >= 1e4) display = (val/1e4).toFixed(0)+'만';
        else                 display = val.toLocaleString();
        el.textContent = (val > 0 ? '+' : '') + display + '원';
        el.classList.add(val > 0 ? 'pos' : 'neg');
    }

    function formatTime(d) {
        const diff = Math.floor((Date.now() - d) / 60000);
        if (diff < 1)    return '방금 전';
        if (diff < 60)   return `${diff}분 전`;
        if (diff < 1440) return `${Math.floor(diff / 60)}시간 전`;
        return d.toLocaleDateString('ko-KR');
    }

    // ─────────────────────────────────────────────
    // ===== QUANT SCREENER =====
    // ─────────────────────────────────────────────
    let screenerPollTimer  = null;
    let screenerPollKey    = null;
    let _screenerPollKey   = null;

    // Preset buttons
    const PRESETS = {
        buy:      ['signal_buy', 'ma_up', 'rsi_low'],
        smart:    ['smart_money', 'foreigner_buy'],
        oversold: ['rsi_low', 'bb_lower'],
        clear:    [],
    };

    document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const preset = PRESETS[btn.dataset.preset] || [];
            document.querySelectorAll('.screener-box input[type=checkbox]').forEach(cb => {
                cb.checked = preset.includes(cb.value);
            });
        });
    });

    // Screener market toggle
    let screenerMarket = 'KOSPI';
    document.querySelectorAll('[data-smarket]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-smarket]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            screenerMarket = btn.dataset.smarket;
        });
    });

    document.getElementById('screener-run')?.addEventListener('click', runScreener);

    function runScreener(refresh = false) {
        const checked = [...document.querySelectorAll('.screener-box input[type=checkbox]:checked')]
            .map(cb => cb.value);
        const condStr = checked.join(',');
        const pollKey = `${screenerMarket}_${condStr}_${Date.now()}`;
        screenerPollKey = pollKey;
        _screenerPollKey = pollKey;

        document.getElementById('loading-screener').classList.remove('hidden');
        document.getElementById('screener-result').classList.add('hidden');
        document.getElementById('screener-empty').classList.add('hidden');

        fetchScreener(screenerMarket, condStr, refresh, pollKey);
    }

    async function fetchScreener(market, conditions, refresh, pollKey) {
        try {
            const url = `/api/screener?market=${market}&conditions=${conditions}&refresh=${refresh}`;
            const res  = await fetch(url);
            const json = await res.json();

            if (screenerPollKey !== pollKey) return;

            if (json.status === 'loading') {
                document.getElementById('screener-loading-msg').textContent = '시장 전체 종목 분석 중... (1~2분 소요)';
                screenerPollTimer = setTimeout(() => {
                    if (screenerPollKey === pollKey) fetchScreener(market, conditions, false, pollKey);
                }, 8000);
                return;
            }

            document.getElementById('loading-screener').classList.add('hidden');

            if (json.status === 'success' && json.data.length > 0) {
                renderScreenerResult(json.data, conditions);
            } else {
                document.getElementById('screener-empty').classList.remove('hidden');
            }
        } catch (e) {
            console.error('Screener error:', e);
            document.getElementById('loading-screener').classList.add('hidden');
        }
    }

    function renderScreenerResult(data, conditions) {
        const tbody  = document.getElementById('screener-tbody');
        const result = document.getElementById('screener-result');
        const count  = document.getElementById('screener-result-count');

        count.textContent = `${data.length}종목 발견`;
        tbody.innerHTML = '';

        const sigLabels = { STRONG_BUY:'강력 매수', BUY:'매수', SELL:'매도', STRONG_SELL:'강력 매도', NEUTRAL:'중립' };

        data.forEach(r => {
            const maStatus = r.ma5>r.ma20&&r.ma20>r.ma60&&r.ma60>0 ? '정배열↑' :
                             r.ma5<r.ma20&&r.ma20<r.ma60&&r.ma5>0 ? '역배열↓' : '혼조';
            const maClass  = r.ma5>r.ma20&&r.ma20>r.ma60 ? 'pos' : r.ma5<r.ma20&&r.ma20<r.ma60 ? 'neg' : '';
            const tr = document.createElement('tr');
            tr.style.cursor = 'pointer';
            tr.innerHTML = `
                <td><strong class="screener-name">${r.name}</strong> <small style="color:var(--text-3)">${r.ticker}</small></td>
                <td>${r.current_price.toLocaleString()}원</td>
                <td class="${r.change_rate>=0?'pos':'neg'}">${r.change_rate>0?'+':''}${r.change_rate}%</td>
                <td class="${r.rsi<=30?'pos':r.rsi>=70?'neg':''}">${r.rsi}</td>
                <td class="${r.macd>=0?'pos':'neg'}">${r.macd>0?'+':''}${r.macd}</td>
                <td class="${maClass}">${maStatus}</td>
                <td class="${r.foreigner_net>0?'pos':r.foreigner_net<0?'neg':'neutral'}">${r.foreigner_net?fmtWon(r.foreigner_net)+'원':'-'}</td>
                <td class="${r.institution_net>0?'pos':r.institution_net<0?'neg':'neutral'}">${r.institution_net?fmtWon(r.institution_net)+'원':'-'}</td>
                <td><span class="qc-signal-badge" data-sig="${r.signal}">${sigLabels[r.signal]||'중립'}</span></td>
                <td><strong>${r.score>0?'+':''}${r.score}</strong></td>`;
            tr.addEventListener('click', () => openStockPanel(r.ticker, r.name));
            tbody.appendChild(tr);
        });

        result.classList.remove('hidden');
    }

    // ─────────────────────────────────────────────
    // ===== ETF 리밸런싱 TAB =====
    // ─────────────────────────────────────────────
    async function loadETFTab() { loadRebalancing(); loadETFPerformance(); }

    async function loadRebalancing() {
        const loadEl   = document.getElementById('loading-rebal');
        const eventsEl = document.getElementById('rebal-events');
        const emptyEl  = document.getElementById('rebal-empty');
        loadEl.classList.remove('hidden');
        eventsEl.innerHTML = '';
        emptyEl.classList.add('hidden');
        try {
            const res  = await fetch('/api/etf-rebalancing');
            const json = await res.json();
            loadEl.classList.add('hidden');
            if (json.status === 'success' && json.data.length > 0) renderRebalEvents(json.data, eventsEl);
            else emptyEl.classList.remove('hidden');
        } catch {
            loadEl.classList.add('hidden');
            eventsEl.innerHTML = '<p style="color:var(--red);padding:1rem">리밸런싱 데이터 조회 실패.</p>';
        }
    }

    function renderRebalEvents(events, container) {
        events.forEach(ev => {
            const card = document.createElement('div');
            card.className = 'rebal-card';
            const badgeClass = ev.category==='레버리지'?'badge-lev':ev.category==='인버스'?'badge-inv':ev.category==='섹터'?'badge-sec':ev.category==='테마'?'badge-theme':'badge-idx';
            let changesHtml = '';
            if (ev.added.length > 0) changesHtml += `<div class="rebal-group"><span class="rebal-group-label added">▲ 신규편입</span><div class="rebal-chips">${ev.added.map(s=>`<span class="chip chip-added">${s.name} <em>${s.weight}%</em></span>`).join('')}</div></div>`;
            if (ev.removed.length > 0) changesHtml += `<div class="rebal-group"><span class="rebal-group-label removed">▼ 편출</span><div class="rebal-chips">${ev.removed.map(s=>`<span class="chip chip-removed">${s.name}</span>`).join('')}</div></div>`;
            if (ev.reweighted.length > 0) {
                const top5 = ev.reweighted.slice(0,5);
                changesHtml += `<div class="rebal-group"><span class="rebal-group-label reweight">⇄ 비중 변경</span><div class="rebal-table-wrap"><table class="rebal-mini-table"><thead><tr><th>종목</th><th>변경 전</th><th>변경 후</th><th>변화</th></tr></thead><tbody>${top5.map(s=>`<tr><td>${s.name}</td><td>${s.prev_weight}%</td><td>${s.curr_weight}%</td><td class="${s.change>0?'pos':'neg'}">${s.change>0?'+':''}${s.change}%p</td></tr>`).join('')}</tbody></table></div></div>`;
            }
            card.innerHTML = `<div class="rebal-card-header"><div class="rebal-etf-info"><span class="rebal-etf-name">${ev.etf_name}</span><span class="rebal-ticker">${ev.etf_ticker}</span><span class="rebal-category-badge ${badgeClass}">${ev.category}</span></div><div class="rebal-date">${formatDate(ev.date)} 기준</div></div><p class="rebal-summary">${ev.summary}</p><div class="rebal-changes">${changesHtml}</div>`;
            container.appendChild(card);
        });
    }

    function formatDate(dateStr) {
        if (!dateStr || dateStr.length < 8) return dateStr;
        return `${dateStr.slice(0,4)}.${dateStr.slice(4,6)}.${dateStr.slice(6,8)}`;
    }

    async function loadETFPerformance() {
        const loadEl  = document.getElementById('loading-perf');
        const tableEl = document.getElementById('etf-perf-table');
        const tbody   = document.getElementById('perf-tbody');
        loadEl.classList.remove('hidden');
        tableEl.classList.add('hidden');
        try {
            const res  = await fetch('/api/etf-performance');
            const json = await res.json();
            loadEl.classList.add('hidden');
            if (json.status === 'success' && json.data.length > 0) {
                tbody.innerHTML = '';
                json.data.forEach(etf => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td><strong>${etf.name}</strong> <small style="color:var(--text-3)">${etf.ticker}</small></td><td><span class="etf-cat-tag">${etf.category}</span></td><td>${etf.price.toLocaleString()}원</td><td class="${etf.change_1d>=0?'pos':'neg'}">${etf.change_1d>0?'+':''}${etf.change_1d}%</td><td class="${etf.change_1m>=0?'pos':'neg'}">${etf.change_1m>0?'+':''}${etf.change_1m}%</td>`;
                    tbody.appendChild(tr);
                });
                tableEl.classList.remove('hidden');
            }
        } catch (e) { loadEl.classList.add('hidden'); }
    }

    // ─────────────────────────────────────────────
    // ===== TREND CHART =====
    // ─────────────────────────────────────────────
    let trendChart = null;
    let _trendPollTimer = null;
    let _trendPollKey   = null;

    async function loadTrendChart(market, period, isRetry) {
        const pollKey = `${market}_${period}`;
        _trendPollKey = pollKey;
        const loadEl  = document.getElementById('loading-trend');
        const chartEl = document.getElementById('trend-chart');
        loadEl.classList.remove('hidden');
        if (!isRetry) { chartEl.innerHTML = ''; if (trendChart) { trendChart.dispose(); trendChart = null; } }
        try {
            const res  = await fetch(`/api/market-flow/trend?market=${market}&period=${period}`);
            const json = await res.json();
            if (json.status === 'loading') {
                const pEl = loadEl.querySelector('p');
                if (pEl) pEl.textContent = '추이 데이터 집계 중... (최대 2분 소요)';
                _trendPollTimer = setTimeout(() => { if (_trendPollKey===pollKey) loadTrendChart(market,period,true); }, 8000);
                return;
            }
            loadEl.classList.add('hidden');
            if (json.status==='success' && json.data.length>0) renderTrendChart(json.data, period);
            else { chartEl.style.height=''; chartEl.innerHTML=`<div class="heatmap-empty"><span style="font-size:1.8rem">📉</span><span>추이 데이터를 불러오지 못했습니다.</span></div>`; }
        } catch (e) { loadEl.classList.add('hidden'); }
    }

    function renderTrendChart(data, period) {
        const container = document.getElementById('trend-chart');
        container.style.height = '300px';
        const isDark = document.body.classList.contains('dark');
        if (!trendChart) trendChart = echarts.init(container, isDark ? 'dark' : null);
        const xLabels = data.map(d => { const s=d.date; return s.length===8?`${s.slice(4,6)}/${s.slice(6,8)}`:s; });
        const toEok = v => Math.round(v/1e8);
        const fData = data.map(d => toEok(d.foreigner));
        const iData = data.map(d => toEok(d.institution));
        const barWidth = data.length<=5 ? 20 : 'auto';
        trendChart.setOption({
            backgroundColor:'transparent',
            tooltip:{ trigger:'axis', axisPointer:{type:'shadow'}, formatter: params => { let s=`<b>${params[0].axisValue}</b><br/>`; params.forEach(p=>{ const sign=p.value>=0?'+':''; s+=`<span style="display:inline-block;width:8px;height:8px;background:${p.color};border-radius:2px;margin-right:5px;"></span>${p.seriesName}: <b>${sign}${p.value.toLocaleString()}억</b><br/>`; }); return s; } },
            legend:{ data:['외국인','기관'], bottom:4, textStyle:{fontSize:12}, itemWidth:14, itemHeight:10 },
            grid:{ top:16, right:16, bottom:44, left:56 },
            xAxis:{ type:'category', data:xLabels, axisLabel:{fontSize:11, rotate:data.length>15?30:0}, axisTick:{alignWithLabel:true} },
            yAxis:{ type:'value', name:'억원', nameTextStyle:{fontSize:10}, axisLabel:{fontSize:10, formatter:v=>v>=10000?`${(v/10000).toFixed(0)}조`:v.toLocaleString()}, splitLine:{lineStyle:{type:'dashed',opacity:0.4}} },
            series:[
                { name:'외국인', type:'bar', barWidth, barGap:'10%', data:fData.map(v=>({value:v,itemStyle:{color:v>=0?'#2563eb':'#93c5fd'}})) },
                { name:'기관',   type:'bar', barWidth, barGap:'10%', data:iData.map(v=>({value:v,itemStyle:{color:v>=0?'#f59e0b':'#fcd34d'}})) }
            ]
        }, true);
        window.addEventListener('resize', () => trendChart && trendChart.resize());
    }

    // ─────────────────────────────────────────────
    // ===== HEATMAP =====
    // ─────────────────────────────────────────────
    let heatmapChart  = null;
    let _heatmapPollTimer = null;
    let _heatmapPollKey   = null;

    async function loadHeatmap(market, period, isRetry) {
        const pollKey = `${market}_${period}`;
        _heatmapPollKey = pollKey;
        const loadEl       = document.getElementById('loading-heatmap');
        const tableSection = document.getElementById('flow-table-section');
        const chartEl      = document.getElementById('heatmap-chart');
        loadEl.classList.remove('hidden');
        tableSection.classList.add('hidden');
        if (!isRetry) { chartEl.innerHTML=''; if(heatmapChart){heatmapChart.dispose();heatmapChart=null;} }
        try {
            const res  = await fetch(`/api/market-flow?market=${market}&period=${period}`);
            const json = await res.json();
            if (json.status==='loading') {
                const pEl = loadEl.querySelector('p');
                if (pEl) pEl.textContent='수급 데이터 집계 중... (최대 2분 소요)';
                _heatmapPollTimer = setTimeout(()=>{ if(_heatmapPollKey===pollKey) loadHeatmap(market,period,true); },8000);
                return;
            }
            loadEl.classList.add('hidden');
            if (json.status==='success') { renderHeatmap(json.data); if(json.data?.length>0) renderFlowTable(json.data); }
            else renderHeatmap([]);
        } catch (e) { loadEl.classList.add('hidden'); renderHeatmap([]); }
    }

    function isMobile() { return window.innerWidth < 560; }

    function renderHeatmap(data) {
        const container = document.getElementById('heatmap-chart');
        if (!data || data.length===0) {
            container.style.height='';
            container.innerHTML=`<div class="heatmap-empty"><span style="font-size:2rem">📊</span><span>수급 데이터를 불러오지 못했습니다.</span><small>장 마감 후 또는 잠시 후 다시 시도해 주세요.</small></div>`;
            return;
        }
        if (isMobile()) renderHeatmapMobile(data, container);
        else renderHeatmapDesktop(data, container);
    }

    function renderHeatmapMobile(data, container) {
        if (heatmapChart) { heatmapChart.dispose(); heatmapChart=null; }
        container.style.height='auto'; container.style.minHeight='';
        const list = document.createElement('div');
        list.className = 'hm-list';
        data.forEach((item,i) => {
            const cls = item.total>0?'hm-buy':item.total<0?'hm-sell':'hm-neutral';
            const row = document.createElement('div');
            row.className=`hm-row ${cls}`;
            row.style.cursor='pointer';
            row.innerHTML=`<span class="hm-rank">${i+1}</span><div class="hm-info"><span class="hm-name">${item.name}</span><span class="hm-code">${item.code}</span></div><div class="hm-nums"><span class="hm-total ${item.total>=0?'pos':'neg'}">${item.total>0?'+':''}${fmtShares(item.total)}</span><span class="hm-sub">외 ${item.foreigner>0?'+':''}${fmtShares(item.foreigner)} / 기 ${item.institution>0?'+':''}${fmtShares(item.institution)}</span></div>`;
            row.addEventListener('click', () => openStockPanel(item.code, item.name));
            list.appendChild(row);
        });
        container.innerHTML='';
        container.appendChild(list);
    }

    function renderHeatmapDesktop(data, container) {
        container.style.height='500px';
        if (!heatmapChart) heatmapChart=echarts.init(container, document.body.classList.contains('dark')?'dark':null);
        const maxAbs = Math.max(...data.map(d=>Math.abs(d.total)),1);
        const treeData = data.map(item => {
            const ratio=Math.abs(item.total)/maxAbs, alpha=Math.min(ratio*0.8+0.2,1);
            const color=item.total>0?`rgba(16,185,129,${alpha})`:item.total<0?`rgba(239,68,68,${alpha})`:'rgba(148,163,184,0.3)';
            return { name:item.name, value:Math.max(Math.abs(item.total),1), itemStyle:{color},
                label:{formatter:`{b}\n${item.total>0?'+':''}${fmtShares(item.total)}`}, _raw:item };
        });
        heatmapChart.setOption({
            tooltip:{ formatter:p=>{ const r=p.data._raw; return `<b>${r.name}</b><br/>외국인: ${r.foreigner>0?'+':''}${fmtShares(r.foreigner)}<br/>기관: ${r.institution>0?'+':''}${fmtShares(r.institution)}`; } },
            series:[{ type:'treemap', data:treeData, roam:false, nodeClick:false,
                breadcrumb:{show:false}, label:{show:true,color:'#fff',fontWeight:700,fontSize:13},
                levels:[{itemStyle:{borderColor:'#fff',borderWidth:2,gapWidth:2}}] }]
        }, true);
        heatmapChart.on('click', params => {
            const r = params.data?._raw;
            if (r) openStockPanel(r.code, r.name);
        });
        window.addEventListener('resize', () => heatmapChart && heatmapChart.resize());
    }

    function fmtShares(val) {
        const abs=Math.abs(val);
        if (abs>=1e8)    return (val/1e8).toFixed(1)+'억';
        if (abs>=10000)  return (val/10000).toFixed(1)+'만';
        return val.toLocaleString();
    }

    function renderFlowTable(data) {
        const section=document.getElementById('flow-table-section'), tbody=document.querySelector('#flow-table tbody');
        tbody.innerHTML='';
        data.forEach(item => {
            const tr=document.createElement('tr');
            tr.style.cursor='pointer';
            tr.innerHTML=`<td><strong>${item.name}</strong> <small style="color:var(--text-3)">${item.code}</small></td><td class="${item.foreigner>=0?'pos':'neg'}">${item.foreigner>0?'+':''}${fmtShares(item.foreigner)}</td><td class="${item.institution>=0?'pos':'neg'}">${item.institution>0?'+':''}${fmtShares(item.institution)}</td><td class="${item.total>=0?'pos':'neg'}"><strong>${item.total>0?'+':''}${fmtShares(item.total)}</strong></td>`;
            tr.addEventListener('click', () => openStockPanel(item.code, item.name));
            tbody.appendChild(tr);
        });
        section.classList.remove('hidden');
    }

    // ===== INIT =====
    fetchNews();
});
