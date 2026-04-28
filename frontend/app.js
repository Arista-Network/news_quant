document.addEventListener('DOMContentLoaded', () => {
    // ===== Tab Navigation =====
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    let heatmapLoaded = false;

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
        });
    });

    // ===== Market toggle =====
    document.querySelectorAll('.market-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.market-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            loadHeatmap(btn.dataset.market);
        });
    });

    // ===== NEWS FEED =====
    const newsFeed = document.getElementById('news-feed');
    const loadFeed = document.getElementById('loading-feed');
    const newsTpl = document.getElementById('news-tpl');
    const quantTpl = document.getElementById('quant-tpl');

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

            // Meta
            card.querySelector('.news-source').textContent = item.source || '뉴스';
            const pubDate = new Date(item.published);
            card.querySelector('.news-time').textContent = isNaN(pubDate) ? item.published : formatTime(pubDate);

            // Sentiment
            const sentTag = card.querySelector('.sentiment-tag');
            if (item.sentiment) {
                const s = item.sentiment;
                sentTag.textContent = s.label === 'POSITIVE' ? `긍정 +${s.score}` : s.label === 'NEGATIVE' ? `부정 ${s.score}` : '중립';
                sentTag.setAttribute('data-s', s.label);
            } else {
                sentTag.style.display = 'none';
            }

            // Title & Summary
            const linkEl = card.querySelector('.news-title a');
            linkEl.textContent = item.title;
            linkEl.href = item.link;
            card.querySelector('.news-summary').textContent = item.summary;

            // Quant Cards
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

                    // Signal
                    const sigLabels = { STRONG_BUY:'강력 매수', BUY:'매수 관점', SELL:'매도 관점', STRONG_SELL:'강력 매도', NEUTRAL:'중립' };
                    const sigBadge = qc.querySelector('.qc-signal-badge');
                    sigBadge.textContent = sigLabels[q.signal] || '중립';
                    sigBadge.setAttribute('data-sig', q.signal);
                    qc.querySelector('.qc-score-badge').textContent = `Score ${q.score > 0 ? '+' : ''}${q.score}`;

                    // RSI bar
                    qc.querySelector('.rsi-bar').style.width = `${Math.min(q.rsi, 100)}%`;
                    qc.querySelector('.ind-item:nth-child(1) .ind-val').textContent = q.rsi;

                    // MACD
                    const macdEl = qc.querySelector('.macd-val');
                    macdEl.textContent = q.macd > 0 ? `+${q.macd}` : q.macd;
                    macdEl.classList.add(q.macd >= 0 ? 'up' : 'down');

                    // Stochastic
                    qc.querySelector('.stoch-bar').style.width = `${Math.min(q.stoch_k, 100)}%`;
                    qc.querySelector('.stoch-val').textContent = q.stoch_k;

                    // Smart Money
                    setSmVal(qc.querySelector('.foreigner-val'), q.foreigner_net);
                    setSmVal(qc.querySelector('.institution-val'), q.institution_net);

                    // MA Status
                    const maEl = qc.querySelector('.ma-status');
                    if (q.ma5 > q.ma20 && q.ma20 > q.ma60 && q.ma60 > 0) {
                        maEl.textContent = '정배열 ↑'; maEl.classList.add('pos');
                    } else if (q.ma5 < q.ma20 && q.ma20 < q.ma60 && q.ma5 > 0) {
                        maEl.textContent = '역배열 ↓'; maEl.classList.add('neg');
                    } else {
                        maEl.textContent = '혼조';
                    }

                    // Reasons
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
        el.textContent = (val > 0 ? '+' : '') + val.toLocaleString() + '주';
        el.classList.add(val >= 0 ? 'pos' : 'neg');
    }

    function formatTime(d) {
        const diff = Math.floor((Date.now() - d) / 60000);
        if (diff < 1) return '방금 전';
        if (diff < 60) return `${diff}분 전`;
        if (diff < 1440) return `${Math.floor(diff/60)}시간 전`;
        return d.toLocaleDateString('ko-KR');
    }

    // ===== HEATMAP =====
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

        const treeData = data.map(item => ({
            name: item.name,
            value: Math.abs(item.total),
            itemStyle: {
                color: item.total > 0 ? `rgba(16,185,129,${Math.min(Math.abs(item.total)/500000 + 0.3, 1)})` :
                       `rgba(239,68,68,${Math.min(Math.abs(item.total)/500000 + 0.3, 1)})`
            },
            label: {
                formatter: `{b}\n${item.total > 0 ? '+' : ''}${(item.total/1000).toFixed(0)}K`
            },
            _raw: item
        }));

        const option = {
            tooltip: {
                formatter: p => {
                    const r = p.data._raw;
                    return `<b>${r.name}</b><br/>외국인: ${r.foreigner > 0 ? '+' : ''}${r.foreigner.toLocaleString()}주<br/>기관: ${r.institution > 0 ? '+' : ''}${r.institution.toLocaleString()}주`;
                }
            },
            series: [{
                type: 'treemap',
                data: treeData,
                roam: false,
                nodeClick: false,
                breadcrumb: { show: false },
                label: { show: true, color: '#fff', fontWeight: 700, fontSize: 13 },
                levels: [{
                    itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 }
                }]
            }]
        };

        heatmapChart.setOption(option, true);
        window.addEventListener('resize', () => heatmapChart.resize());
    }

    function renderFlowTable(data) {
        const section = document.getElementById('flow-table-section');
        const tbody = document.querySelector('#flow-table tbody');
        tbody.innerHTML = '';

        data.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${item.name}</strong> <small style="color:var(--text-3)">${item.code}</small></td>
                <td class="${item.foreigner >= 0 ? 'pos' : 'neg'}">${item.foreigner > 0 ? '+' : ''}${item.foreigner.toLocaleString()}</td>
                <td class="${item.institution >= 0 ? 'pos' : 'neg'}">${item.institution > 0 ? '+' : ''}${item.institution.toLocaleString()}</td>
                <td class="${item.total >= 0 ? 'pos' : 'neg'}"><strong>${item.total > 0 ? '+' : ''}${item.total.toLocaleString()}</strong></td>
            `;
            tbody.appendChild(tr);
        });
        section.classList.remove('hidden');
    }

    // ===== INIT =====
    fetchNews();
});
