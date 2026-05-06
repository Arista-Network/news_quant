document.addEventListener('DOMContentLoaded', () => {

    // ===== Tab Navigation =====
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    let heatmapLoaded = false;
    let etfLoaded = false;

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');

            if (btn.dataset.tab === 'heatmap' && !heatmapLoaded) {
                loadHeatmap('KOSPI');
                heatmapLoaded = true;
            }
            if (btn.dataset.tab === 'etf' && !etfLoaded) {
                loadETFTab();
                etfLoaded = true;
            }
        });
    });

    // ===== Market toggle (heatmap) =====
    document.querySelectorAll('.market-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.market-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            loadHeatmap(btn.dataset.market);
        });
    });

    // ===== Refresh buttons =====
    document.getElementById('refresh-rebal')?.addEventListener('click', () => {
        loadRebalancing();
    });

    // ─────────────────────────────────────────────
    // ===== NEWS FEED =====
    // ─────────────────────────────────────────────
    const newsFeed = document.getElementById('news-feed');
    const loadFeed = document.getElementById('loading-feed');
    const newsTpl = document.getElementById('news-tpl');
    const quantTpl = document.getElementById('quant-tpl');

    const CATEGORY_COLORS = {
        '실적':   { bg:'#dbeafe', fg:'#1d4ed8' },
        'M&A':    { bg:'#ede9fe', fg:'#6d28d9' },
        '수급':   { bg:'#d1fae5', fg:'#065f46' },
        'ETF':    { bg:'#fef3c7', fg:'#92400e' },
        '거시경제': { bg:'#f1f5f9', fg:'#334155' },
        '규제':   { bg:'#fee2e2', fg:'#991b1b' },
        '일반':   { bg:'#f8fafc', fg:'#64748b' },
    };

    async function fetchNews() {
        try {
            const res = await fetch('/api/news');
            const json = await res.json();
            if (json.status === 'success') renderFeed(json.data);
            else throw new Error('API error');
        } catch (e) {
            loadFeed.innerHTML = '<p style="color:var(--red)">데이터 로딩 실패. 새로고침 해주세요.</p>';
        }
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

            // 카테고리 태그
            const catTag = card.querySelector('.category-tag');
            if (item.category && item.category !== '일반') {
                const c = CATEGORY_COLORS[item.category] || CATEGORY_COLORS['일반'];
                catTag.textContent = item.is_etf_rebal ? '🔄 ETF' : item.category;
                catTag.style.background = c.bg;
                catTag.style.color = c.fg;
            } else {
                catTag.style.display = 'none';
            }

            // 감성 태그
            const sentTag = card.querySelector('.sentiment-tag');
            if (item.sentiment) {
                const s = item.sentiment;
                sentTag.textContent = s.label === 'POSITIVE' ? `긍정 +${s.score}` : s.label === 'NEGATIVE' ? `부정 ${s.score}` : '중립';
                sentTag.setAttribute('data-s', s.label);
            } else {
                sentTag.style.display = 'none';
            }

            // 제목 & 요약
            const linkEl = card.querySelector('.news-title a');
            linkEl.textContent = item.title;
            linkEl.href = item.link;
            card.querySelector('.news-summary').textContent = item.summary;

            // 퀀트 카드
            const qSection = card.querySelector('.quant-section');
            if (item.quant_data && item.quant_data.length > 0) {
                item.quant_data.forEach(q => {
                    const qc = quantTpl.content.cloneNode(true);
                    qc.querySelector('.qc-name').textContent = q.name;
                    qc.querySelector('.qc-ticker').textContent = q.ticker;
                    qc.querySelector('.qc-price').textContent = q.current_price.toLocaleString() + '원';

                    const chEl = qc.querySelector('.qc-change');
                    const chVal = q.change_rate;
                    chEl.textContent = (chVal > 0 ? '+' : '') + chVal + '%';
                    chEl.classList.add(chVal >= 0 ? 'up' : 'down');

                    const sigLabels = { STRONG_BUY:'강력 매수', BUY:'매수 관점', SELL:'매도 관점', STRONG_SELL:'강력 매도', NEUTRAL:'중립' };
                    const sigBadge = qc.querySelector('.qc-signal-badge');
                    sigBadge.textContent = sigLabels[q.signal] || '중립';
                    sigBadge.setAttribute('data-sig', q.signal);
                    qc.querySelector('.qc-score-badge').textContent = `Score ${q.score > 0 ? '+' : ''}${q.score}`;

                    qc.querySelector('.rsi-bar').style.width = `${Math.min(q.rsi, 100)}%`;
                    qc.querySelector('.ind-item:nth-child(1) .ind-val').textContent = q.rsi;

                    const macdEl = qc.querySelector('.macd-val');
                    macdEl.textContent = q.macd > 0 ? `+${q.macd}` : q.macd;
                    macdEl.classList.add(q.macd >= 0 ? 'up' : 'down');

                    qc.querySelector('.stoch-bar').style.width = `${Math.min(q.stoch_k, 100)}%`;
                    qc.querySelector('.stoch-val').textContent = q.stoch_k;

                    setSmVal(qc.querySelector('.foreigner-val'), q.foreigner_net);
                    setSmVal(qc.querySelector('.institution-val'), q.institution_net);

                    const maEl = qc.querySelector('.ma-status');
                    if (q.ma5 > q.ma20 && q.ma20 > q.ma60 && q.ma60 > 0) {
                        maEl.textContent = '정배열 ↑'; maEl.classList.add('pos');
                    } else if (q.ma5 < q.ma20 && q.ma20 < q.ma60 && q.ma5 > 0) {
                        maEl.textContent = '역배열 ↓'; maEl.classList.add('neg');
                    } else {
                        maEl.textContent = '혼조';
                    }

                    const ul = qc.querySelector('.qc-reasons');
                    (q.reason || []).forEach(r => {
                        const li = document.createElement('li');
                        li.textContent = r;
                        ul.appendChild(li);
                    });

                    qSection.appendChild(qc);
                });
            } else {
                qSection.style.display = 'none';
            }

            newsFeed.appendChild(card);
        });
    }

    function setSmVal(el, val) {
        if (val === 0) {
            el.textContent = '0주';
            el.classList.add('neutral');
            return;
        }
        const absVal = Math.abs(val);
        let display;
        if (absVal >= 10000000) {
            display = (val / 10000000).toFixed(1) + '천만주';
        } else if (absVal >= 10000) {
            display = (val / 10000).toFixed(1) + '만주';
        } else {
            display = val.toLocaleString() + '주';
        }
        el.textContent = (val > 0 ? '+' : '') + display;
        el.classList.add(val > 0 ? 'pos' : 'neg');
    }

    function formatTime(d) {
        const diff = Math.floor((Date.now() - d) / 60000);
        if (diff < 1) return '방금 전';
        if (diff < 60) return `${diff}분 전`;
        if (diff < 1440) return `${Math.floor(diff / 60)}시간 전`;
        return d.toLocaleDateString('ko-KR');
    }

    // ─────────────────────────────────────────────
    // ===== ETF 리밸런싱 TAB =====
    // ─────────────────────────────────────────────
    async function loadETFTab() {
        loadRebalancing();
        loadETFPerformance();
    }

    async function loadRebalancing() {
        const loadEl = document.getElementById('loading-rebal');
        const eventsEl = document.getElementById('rebal-events');
        const emptyEl = document.getElementById('rebal-empty');

        loadEl.classList.remove('hidden');
        eventsEl.innerHTML = '';
        emptyEl.classList.add('hidden');

        try {
            const res = await fetch('/api/etf-rebalancing');
            const json = await res.json();
            loadEl.classList.add('hidden');

            if (json.status === 'success' && json.data.length > 0) {
                renderRebalEvents(json.data, eventsEl);
            } else {
                emptyEl.classList.remove('hidden');
            }
        } catch (e) {
            loadEl.classList.add('hidden');
            eventsEl.innerHTML = '<p style="color:var(--red);padding:1rem">리밸런싱 데이터 조회 실패.</p>';
        }
    }

    function renderRebalEvents(events, container) {
        events.forEach(ev => {
            const card = document.createElement('div');
            card.className = 'rebal-card';

            const badgeClass = ev.category === '레버리지' ? 'badge-lev' :
                               ev.category === '인버스' ? 'badge-inv' :
                               ev.category === '섹터' ? 'badge-sec' :
                               ev.category === '테마' ? 'badge-theme' : 'badge-idx';

            let changesHtml = '';

            if (ev.added.length > 0) {
                changesHtml += `<div class="rebal-group">
                    <span class="rebal-group-label added">▲ 신규편입</span>
                    <div class="rebal-chips">
                        ${ev.added.map(s => `<span class="chip chip-added">${s.name} <em>${s.weight}%</em></span>`).join('')}
                    </div>
                </div>`;
            }

            if (ev.removed.length > 0) {
                changesHtml += `<div class="rebal-group">
                    <span class="rebal-group-label removed">▼ 편출</span>
                    <div class="rebal-chips">
                        ${ev.removed.map(s => `<span class="chip chip-removed">${s.name}</span>`).join('')}
                    </div>
                </div>`;
            }

            if (ev.reweighted.length > 0) {
                const topItems = ev.reweighted.slice(0, 5);
                changesHtml += `<div class="rebal-group">
                    <span class="rebal-group-label reweight">⇄ 비중 변경</span>
                    <div class="rebal-table-wrap">
                        <table class="rebal-mini-table">
                            <thead><tr><th>종목</th><th>변경 전</th><th>변경 후</th><th>변화</th></tr></thead>
                            <tbody>
                                ${topItems.map(s => `
                                <tr>
                                    <td>${s.name}</td>
                                    <td>${s.prev_weight}%</td>
                                    <td>${s.curr_weight}%</td>
                                    <td class="${s.change > 0 ? 'pos' : 'neg'}">${s.change > 0 ? '+' : ''}${s.change}%p</td>
                                </tr>`).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>`;
            }

            card.innerHTML = `
                <div class="rebal-card-header">
                    <div class="rebal-etf-info">
                        <span class="rebal-etf-name">${ev.etf_name}</span>
                        <span class="rebal-ticker">${ev.etf_ticker}</span>
                        <span class="rebal-category-badge ${badgeClass}">${ev.category}</span>
                    </div>
                    <div class="rebal-date">${formatDate(ev.date)} 기준</div>
                </div>
                <p class="rebal-summary">${ev.summary}</p>
                <div class="rebal-changes">${changesHtml}</div>
            `;
            container.appendChild(card);
        });
    }

    function formatDate(dateStr) {
        if (!dateStr || dateStr.length < 8) return dateStr;
        return `${dateStr.slice(0,4)}.${dateStr.slice(4,6)}.${dateStr.slice(6,8)}`;
    }

    async function loadETFPerformance() {
        const loadEl = document.getElementById('loading-perf');
        const tableEl = document.getElementById('etf-perf-table');
        const tbody = document.getElementById('perf-tbody');

        loadEl.classList.remove('hidden');
        tableEl.classList.add('hidden');

        try {
            const res = await fetch('/api/etf-performance');
            const json = await res.json();
            loadEl.classList.add('hidden');

            if (json.status === 'success' && json.data.length > 0) {
                tbody.innerHTML = '';
                json.data.forEach(etf => {
                    const tr = document.createElement('tr');
                    const d1Class = etf.change_1d >= 0 ? 'pos' : 'neg';
                    const m1Class = etf.change_1m >= 0 ? 'pos' : 'neg';
                    tr.innerHTML = `
                        <td><strong>${etf.name}</strong> <small style="color:var(--text-3)">${etf.ticker}</small></td>
                        <td><span class="etf-cat-tag">${etf.category}</span></td>
                        <td>${etf.price.toLocaleString()}원</td>
                        <td class="${d1Class}">${etf.change_1d > 0 ? '+' : ''}${etf.change_1d}%</td>
                        <td class="${m1Class}">${etf.change_1m > 0 ? '+' : ''}${etf.change_1m}%</td>
                    `;
                    tbody.appendChild(tr);
                });
                tableEl.classList.remove('hidden');
            }
        } catch (e) {
            loadEl.classList.add('hidden');
            console.error('ETF performance error:', e);
        }
    }

    // ─────────────────────────────────────────────
    // ===== HEATMAP =====
    // ─────────────────────────────────────────────
    let heatmapChart = null;

    async function loadHeatmap(market) {
        const loadEl = document.getElementById('loading-heatmap');
        const tableSection = document.getElementById('flow-table-section');
        loadEl.classList.remove('hidden');
        tableSection.classList.add('hidden');

        try {
            const res = await fetch(`/api/market-flow?market=${market}`);
            const json = await res.json();
            if (json.status === 'success') {
                renderHeatmap(json.data);
                renderFlowTable(json.data);
            }
        } catch (e) {
            console.error(e);
        } finally {
            loadEl.classList.add('hidden');
        }
    }

    function renderHeatmap(data) {
        const container = document.getElementById('heatmap-chart');
        if (!heatmapChart) {
            heatmapChart = echarts.init(container);
        }

        const maxAbs = Math.max(...data.map(d => Math.abs(d.total)), 1);

        const treeData = data.map(item => ({
            name: item.name,
            value: Math.max(Math.abs(item.total), 1),
            itemStyle: {
                color: item.total > 0
                    ? `rgba(16,185,129,${Math.min(Math.abs(item.total) / maxAbs * 0.8 + 0.2, 1)})`
                    : `rgba(239,68,68,${Math.min(Math.abs(item.total) / maxAbs * 0.8 + 0.2, 1)})`
            },
            label: {
                formatter: `{b}\n${item.total > 0 ? '+' : ''}${fmtShares(item.total)}`
            },
            _raw: item
        }));

        const option = {
            tooltip: {
                formatter: p => {
                    const r = p.data._raw;
                    return `<b>${r.name}</b><br/>외국인: ${r.foreigner > 0 ? '+' : ''}${fmtShares(r.foreigner)}<br/>기관: ${r.institution > 0 ? '+' : ''}${fmtShares(r.institution)}`;
                }
            },
            series: [{
                type: 'treemap',
                data: treeData,
                roam: false,
                nodeClick: false,
                breadcrumb: { show: false },
                label: { show: true, color: '#fff', fontWeight: 700, fontSize: 13 },
                levels: [{ itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 } }]
            }]
        };

        heatmapChart.setOption(option, true);
        window.addEventListener('resize', () => heatmapChart.resize());
    }

    function fmtShares(val) {
        const abs = Math.abs(val);
        if (abs >= 10000000) return (val / 10000000).toFixed(1) + '천만';
        if (abs >= 10000) return (val / 10000).toFixed(1) + '만';
        return val.toLocaleString();
    }

    function renderFlowTable(data) {
        const section = document.getElementById('flow-table-section');
        const tbody = document.querySelector('#flow-table tbody');
        tbody.innerHTML = '';

        data.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${item.name}</strong> <small style="color:var(--text-3)">${item.code}</small></td>
                <td class="${item.foreigner >= 0 ? 'pos' : 'neg'}">${item.foreigner > 0 ? '+' : ''}${fmtShares(item.foreigner)}</td>
                <td class="${item.institution >= 0 ? 'pos' : 'neg'}">${item.institution > 0 ? '+' : ''}${fmtShares(item.institution)}</td>
                <td class="${item.total >= 0 ? 'pos' : 'neg'}"><strong>${item.total > 0 ? '+' : ''}${fmtShares(item.total)}</strong></td>
            `;
            tbody.appendChild(tr);
        });
        section.classList.remove('hidden');
    }

    // ===== INIT =====
    fetchNews();
});
