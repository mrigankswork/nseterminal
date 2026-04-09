/**
 * NSE Options Trading Bot — Main Frontend Logic
 * 
 * Features:
 * - TradingView Lightweight Charts (zoomable, expandable)
 * - Live data from NSE via Flask backend
 * - Recommendation cards (Top 5 Buy/Sell)
 * - Spread strategy panels (Bull Call, Bear Call, Bull Put, Bear Put)
 * - Backtesting with equity curve visualization
 */

const API_BASE = '/api';

// ============================================================
// State
// ============================================================
let mainChart = null;
let mainCandleSeries = null;
let mainVolumeSeries = null;
let modalChart = null;
let modalCandleSeries = null;
let currentSymbol = 'RELIANCE';
let currentChartData = [];
let recommendationsData = null;
let miniCharts = {};

// Chart customization state
let chartType = 'candlestick'; // candlestick | line | area
let chartTimeframe = '6M';
let chartHeight = 480;
let activeIndicators = {}; // { sma20: lineSeries, sma50: lineSeries, ... }
let indicatorOverlays = {};
let panelSymbol = null;
let livePollingTimer = null;
let isMarketOpen = false;

// ============================================================
// Init
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initChart();
    initModal();
    initBacktest();
    initChartToolbar();
    initStockPanel();
    initPaperTrading();
    initLivePolling();
    initStrategy();
    initGlobalSearch();
    loadDashboard();
    loadRecommendations();
    loadNewsFeed();

    // Auto-refresh: dashboard every 30s, recommendations + news every 5 min
    setInterval(() => { loadDashboard(); }, 30000);
    setInterval(() => {
        loadRecommendations();
        loadNewsFeed();
    }, 300000); // 5 minutes

    setTimeout(() => {
        document.getElementById('loading-overlay').classList.add('hidden');
    }, 1500);
});


// ============================================================
// Tabs
// ============================================================
function initTabs() {
    const navBtns = document.querySelectorAll('.nav-btn');
    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            navBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.getElementById(`tab-${tab}`).classList.add('active');

            // Resize charts when switching tabs
            if (tab === 'dashboard' && mainChart) {
                setTimeout(() => mainChart.resize(
                    document.getElementById('main-chart').clientWidth,
                    480
                ), 50);
            }
        });
    });

    // Refresh button
    document.getElementById('refresh-btn').addEventListener('click', () => {
        const btn = document.getElementById('refresh-btn');
        btn.classList.add('spinning');
        Promise.all([loadDashboard(), loadRecommendations()])
            .finally(() => setTimeout(() => btn.classList.remove('spinning'), 800));
    });
}

// ============================================================
// TradingView Lightweight Charts
// ============================================================
function initChart() {
    const container = document.getElementById('main-chart');

    mainChart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: chartHeight,
        layout: {
            background: { type: 'solid', color: '#1a1f2e' },
            textColor: '#94a3b8',
            fontFamily: "'Inter', sans-serif",
            fontSize: 12,
        },
        grid: {
            vertLines: { color: 'rgba(255,255,255,0.03)' },
            horzLines: { color: 'rgba(255,255,255,0.03)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: 'rgba(6,182,212,0.3)', width: 1, style: 2 },
            horzLine: { color: 'rgba(6,182,212,0.3)', width: 1, style: 2 },
        },
        rightPriceScale: {
            borderColor: 'rgba(255,255,255,0.06)',
            scaleMargins: { top: 0.1, bottom: 0.2 },
        },
        timeScale: {
            borderColor: 'rgba(255,255,255,0.06)',
            timeVisible: true,
            secondsVisible: false,
            barSpacing: 8,
        },
        handleScroll: { vertTouchDrag: false },
    });

    // Note: Series are created by applyChartData() based on chart type

    // Crosshair move handler for OHLC display
    mainChart.subscribeCrosshairMove(param => {
        if (!param || !param.time || !mainCandleSeries) {
            document.getElementById('chart-ohlc').textContent = '';
            return;
        }
        const data = param.seriesData.get(mainCandleSeries);
        if (data) {
            if (data.open !== undefined) {
                const { open, high, low, close } = data;
                const color = close >= open ? '#10b981' : '#ef4444';
                document.getElementById('chart-ohlc').innerHTML =
                    `O: <span style="color:${color}">${open.toFixed(2)}</span> ` +
                    `H: <span style="color:${color}">${high.toFixed(2)}</span> ` +
                    `L: <span style="color:${color}">${low.toFixed(2)}</span> ` +
                    `C: <span style="color:${color}">${close.toFixed(2)}</span>`;
            } else if (data.value !== undefined) {
                document.getElementById('chart-ohlc').innerHTML =
                    `Price: <span style="color:#06b6d4">${data.value.toFixed(2)}</span>`;
            }
        }
    });

    // Symbol selector
    document.getElementById('chart-symbol-select').addEventListener('change', (e) => {
        currentSymbol = e.target.value;
        loadChartData(currentSymbol);
    });

    // Responsive resize
    const resizeObserver = new ResizeObserver(() => {
        if (mainChart) {
            mainChart.resize(container.clientWidth, 480);
        }
    });
    resizeObserver.observe(container);

    // Load initial chart
    loadChartData(currentSymbol);
}

function initModal() {
    const modal = document.getElementById('chart-modal');

    document.getElementById('chart-expand-btn').addEventListener('click', () => {
        modal.classList.add('open');
        createModalChart();
    });

    document.getElementById('close-modal-btn').addEventListener('click', () => {
        modal.classList.remove('open');
        if (modalChart) {
            modalChart.remove();
            modalChart = null;
        }
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('open');
            if (modalChart) {
                modalChart.remove();
                modalChart = null;
            }
        }
    });

    // ESC key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('open')) {
            modal.classList.remove('open');
            if (modalChart) {
                modalChart.remove();
                modalChart = null;
            }
        }
    });
}

function createModalChart() {
    const container = document.getElementById('modal-chart');
    container.innerHTML = '';

    document.getElementById('modal-chart-title').textContent = `${currentSymbol} — Expanded View`;

    modalChart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        layout: {
            background: { type: 'solid', color: '#1a1f2e' },
            textColor: '#94a3b8',
            fontFamily: "'Inter', sans-serif",
            fontSize: 12,
        },
        grid: {
            vertLines: { color: 'rgba(255,255,255,0.03)' },
            horzLines: { color: 'rgba(255,255,255,0.03)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: 'rgba(6,182,212,0.3)', width: 1, style: 2 },
            horzLine: { color: 'rgba(6,182,212,0.3)', width: 1, style: 2 },
        },
        rightPriceScale: {
            borderColor: 'rgba(255,255,255,0.06)',
        },
        timeScale: {
            borderColor: 'rgba(255,255,255,0.06)',
            timeVisible: true,
            barSpacing: 10,
        },
    });

    modalCandleSeries = modalChart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    const volSeries = modalChart.addHistogramSeries({
        color: '#8b5cf6',
        priceFormat: { type: 'volume' },
        priceScaleId: '',
    });
    volSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
    });

    if (currentChartData.length > 0) {
        const candles = currentChartData.map(d => ({
            time: d.date,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
        }));
        const volumes = currentChartData.map(d => ({
            time: d.date,
            value: d.volume,
            color: d.close >= d.open ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)',
        }));
        modalCandleSeries.setData(candles);
        volSeries.setData(volumes);
        modalChart.timeScale().fitContent();
    }

    // Resize observer for modal
    const resizeObserver = new ResizeObserver(() => {
        if (modalChart) {
            modalChart.resize(container.clientWidth, container.clientHeight);
        }
    });
    resizeObserver.observe(container);
}

// ============================================================
// API Calls
// ============================================================
async function fetchAPI(endpoint, options = {}) {
    try {
        const resp = await fetch(`${API_BASE}${endpoint}`, options);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.warn(`API call failed: ${endpoint}`, err);
        return null;
    }
}

// ============================================================
// Dashboard
// ============================================================
async function loadDashboard() {
    const data = await fetchAPI('/stocks/top');
    if (!data) {
        renderDemoMovers();
        return;
    }

    // Update market strip
    if (data.all && data.all.length > 0) {
        const strip = document.getElementById('market-strip');
        strip.innerHTML = data.all.slice(0, 8).map(s => `
            <div class="strip-card">
                <span class="strip-label">${s.symbol}</span>
                <span class="strip-value">₹${formatNumber(s.lastPrice)}</span>
                <span class="strip-change ${s.pChange >= 0 ? 'up' : 'down'}">
                    ${s.pChange >= 0 ? '+' : ''}${s.pChange.toFixed(2)}%
                </span>
            </div>
        `).join('');
    }

    // Gainers
    renderMovers('gainers-list', data.gainers || [], true);
    // Losers
    renderMovers('losers-list', data.losers || [], false);

    // Update market status
    updateMarketStatus();
}

function renderMovers(containerId, stocks, isGainer) {
    const container = document.getElementById(containerId);
    if (!stocks.length) {
        container.innerHTML = '<div class="mover-row"><span class="mover-symbol" style="color:var(--text-muted)">No data available</span></div>';
        return;
    }
    container.innerHTML = stocks.slice(0, 5).map(s => `
        <div class="mover-row" onclick="loadChartForSymbol('${s.symbol}')">
            <span class="mover-symbol">${s.symbol}</span>
            <span class="mover-price">₹${formatNumber(s.lastPrice)}</span>
            <span class="mover-change ${s.pChange >= 0 ? 'up' : 'down'}">
                ${s.pChange >= 0 ? '+' : ''}${s.pChange.toFixed(2)}%
            </span>
        </div>
    `).join('');
}

function renderDemoMovers() {
    const demoGainers = [
        { symbol: 'RELIANCE', lastPrice: 2456.75, pChange: 3.21 },
        { symbol: 'TCS', lastPrice: 3890.50, pChange: 2.87 },
        { symbol: 'INFY', lastPrice: 1567.30, pChange: 2.45 },
        { symbol: 'HDFCBANK', lastPrice: 1678.90, pChange: 1.98 },
        { symbol: 'ICICIBANK', lastPrice: 1234.60, pChange: 1.76 },
    ];
    const demoLosers = [
        { symbol: 'TATAMOTORS', lastPrice: 678.45, pChange: -2.34 },
        { symbol: 'BAJFINANCE', lastPrice: 6789.30, pChange: -1.89 },
        { symbol: 'SBIN', lastPrice: 567.80, pChange: -1.56 },
        { symbol: 'WIPRO', lastPrice: 456.25, pChange: -1.23 },
        { symbol: 'SUNPHARMA', lastPrice: 1234.50, pChange: -0.98 },
    ];
    renderMovers('gainers-list', demoGainers, true);
    renderMovers('losers-list', demoLosers, false);

    // Demo strip
    const strip = document.getElementById('market-strip');
    strip.innerHTML = demoGainers.concat(demoLosers.slice(0, 3)).map(s => `
        <div class="strip-card">
            <span class="strip-label">${s.symbol}</span>
            <span class="strip-value">₹${formatNumber(s.lastPrice)}</span>
            <span class="strip-change ${s.pChange >= 0 ? 'up' : 'down'}">
                ${s.pChange >= 0 ? '+' : ''}${s.pChange.toFixed(2)}%
            </span>
        </div>
    `).join('');
}

async function updateMarketStatus() {
    const statusEl = document.getElementById('market-status');
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('.status-text');

    const now = new Date();
    const hours = now.getHours();
    const minutes = now.getMinutes();
    const day = now.getDay();

    const isWeekday = day >= 1 && day <= 5;
    const isMarketHours = hours >= 9 && (hours < 15 || (hours === 15 && minutes <= 30));

    if (isWeekday && isMarketHours) {
        dot.classList.add('open');
        dot.classList.remove('closed');
        text.textContent = 'Market Open';
    } else {
        dot.classList.add('closed');
        dot.classList.remove('open');
        text.textContent = 'Market Closed';
    }
}

// ============================================================
// Chart Data
// ============================================================
async function loadChartData(symbol) {
    document.getElementById('chart-stock-name').textContent = symbol;

    const data = await fetchAPI(`/stock/${symbol}/history`);

    if (data && data.data && data.data.length > 0) {
        currentChartData = data.data;
    } else {
        currentChartData = generateDemoChartData();
    }

    applyChartData();
}

function applyChartData() {
    // Filter by timeframe
    const filtered = filterByTimeframe(currentChartData, chartTimeframe);

    // Remove old series
    clearChartSeries();

    // Create series based on chart type
    if (chartType === 'candlestick') {
        mainCandleSeries = mainChart.addCandlestickSeries({
            upColor: '#10b981', downColor: '#ef4444',
            borderUpColor: '#10b981', borderDownColor: '#ef4444',
            wickUpColor: '#10b981', wickDownColor: '#ef4444',
        });
        mainCandleSeries.setData(filtered.map(d => ({
            time: d.date, open: d.open, high: d.high, low: d.low, close: d.close,
        })));
    } else if (chartType === 'line') {
        mainCandleSeries = mainChart.addLineSeries({
            color: '#06b6d4', lineWidth: 2,
        });
        mainCandleSeries.setData(filtered.map(d => ({ time: d.date, value: d.close })));
    } else {
        mainCandleSeries = mainChart.addAreaSeries({
            lineColor: '#06b6d4', topColor: 'rgba(6,182,212,0.2)',
            bottomColor: 'rgba(6,182,212,0)', lineWidth: 2,
        });
        mainCandleSeries.setData(filtered.map(d => ({ time: d.date, value: d.close })));
    }

    // Volume
    mainVolumeSeries = mainChart.addHistogramSeries({
        color: '#8b5cf6', priceFormat: { type: 'volume' }, priceScaleId: '',
    });
    mainVolumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    mainVolumeSeries.setData(filtered.map(d => ({
        time: d.date,
        value: d.volume || Math.floor(Math.random() * 5000000),
        color: d.close >= d.open ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)',
    })));

    // Apply indicators
    applyIndicators(filtered);

    // Scroll to latest
    mainChart.timeScale().scrollToRealTime();
}

function clearChartSeries() {
    try {
        if (mainCandleSeries) { mainChart.removeSeries(mainCandleSeries); mainCandleSeries = null; }
        if (mainVolumeSeries) { mainChart.removeSeries(mainVolumeSeries); mainVolumeSeries = null; }
        // Remove indicator overlays
        Object.values(indicatorOverlays).forEach(s => {
            try { mainChart.removeSeries(s); } catch (e) { }
        });
        indicatorOverlays = {};
    } catch (e) { }
}

function filterByTimeframe(data, tf) {
    if (tf === 'ALL' || !data.length) return data;
    const now = new Date();
    let cutoff = new Date();
    switch (tf) {
        case '1W': cutoff.setDate(now.getDate() - 7); break;
        case '1M': cutoff.setMonth(now.getMonth() - 1); break;
        case '3M': cutoff.setMonth(now.getMonth() - 3); break;
        case '6M': cutoff.setMonth(now.getMonth() - 6); break;
        case '1Y': cutoff.setFullYear(now.getFullYear() - 1); break;
        default: return data;
    }
    const cutoffStr = cutoff.toISOString().split('T')[0];
    const result = data.filter(d => d.date >= cutoffStr);
    return result.length > 5 ? result : data;
}

function applyIndicators(data) {
    const closes = data.map(d => d.close);
    const checkboxes = document.querySelectorAll('#indicator-toggles input[type="checkbox"]');

    checkboxes.forEach(cb => {
        const key = cb.dataset.indicator;
        if (!cb.checked) return;

        let values = [];
        let color = '#06b6d4';
        let lineWidth = 1;

        if (key === 'sma20') {
            values = calcSMA(closes, 20);
            color = '#f59e0b';
        } else if (key === 'sma50') {
            values = calcSMA(closes, 50);
            color = '#8b5cf6';
        } else if (key === 'ema20') {
            values = calcEMA(closes, 20);
            color = '#ec4899';
        } else if (key === 'bollinger') {
            const bb = calcBollinger(closes, 20);
            // Upper band
            const upperSeries = mainChart.addLineSeries({ color: 'rgba(239,68,68,0.5)', lineWidth: 1, lineStyle: 2 });
            upperSeries.setData(bb.upper.map((v, i) => v !== null ? { time: data[i].date, value: v } : null).filter(Boolean));
            indicatorOverlays['bb_upper'] = upperSeries;
            // Lower band
            const lowerSeries = mainChart.addLineSeries({ color: 'rgba(16,185,129,0.5)', lineWidth: 1, lineStyle: 2 });
            lowerSeries.setData(bb.lower.map((v, i) => v !== null ? { time: data[i].date, value: v } : null).filter(Boolean));
            indicatorOverlays['bb_lower'] = lowerSeries;
            // Middle
            values = bb.middle;
            color = 'rgba(148,163,184,0.5)';
        }

        if (values.length > 0 && key !== 'bollinger') {
            const series = mainChart.addLineSeries({ color, lineWidth });
            series.setData(values.map((v, i) => v !== null ? { time: data[i].date, value: v } : null).filter(Boolean));
            indicatorOverlays[key] = series;
        }
    });
}

function calcSMA(data, period) {
    const result = new Array(data.length).fill(null);
    for (let i = period - 1; i < data.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += data[j];
        result[i] = +(sum / period).toFixed(2);
    }
    return result;
}

function calcEMA(data, period) {
    const result = new Array(data.length).fill(null);
    const k = 2 / (period + 1);
    let prev = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
    result[period - 1] = +prev.toFixed(2);
    for (let i = period; i < data.length; i++) {
        prev = data[i] * k + prev * (1 - k);
        result[i] = +prev.toFixed(2);
    }
    return result;
}

function calcBollinger(data, period) {
    const middle = calcSMA(data, period);
    const upper = new Array(data.length).fill(null);
    const lower = new Array(data.length).fill(null);
    for (let i = period - 1; i < data.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += (data[j] - middle[i]) ** 2;
        const std = Math.sqrt(sum / period);
        upper[i] = +(middle[i] + 2 * std).toFixed(2);
        lower[i] = +(middle[i] - 2 * std).toFixed(2);
    }
    return { middle, upper, lower };
}

function generateDemoChartData() {
    const data = [];
    let price = 1500 + Math.random() * 1500;
    const startDate = new Date('2025-03-01');
    for (let i = 0; i < 250; i++) {
        const date = new Date(startDate);
        date.setDate(startDate.getDate() + i);
        if (date.getDay() === 0 || date.getDay() === 6) continue;
        const change = (Math.random() - 0.48) * price * 0.025;
        const open = price;
        price += change;
        const high = Math.max(open, price) + Math.random() * price * 0.008;
        const low = Math.min(open, price) - Math.random() * price * 0.008;
        data.push({
            date: date.toISOString().split('T')[0],
            open: Math.round(open * 100) / 100,
            high: Math.round(high * 100) / 100,
            low: Math.round(low * 100) / 100,
            close: Math.round(price * 100) / 100,
            volume: Math.floor(Math.random() * 5000000) + 500000,
        });
    }
    return data;
}

// Global function for mover row clicks — also opens stock panel
window.loadChartForSymbol = function (symbol) {
    currentSymbol = symbol;
    document.getElementById('chart-symbol-select').value = symbol;
    loadChartData(symbol);
    openStockPanel(symbol);
};

// ============================================================
// Recommendations
// ============================================================
async function loadRecommendations() {
    const resp = await fetchAPI('/recommendations');
    if (resp && resp.data) {
        recommendationsData = resp.data;
    } else {
        recommendationsData = generateDemoRecommendations();
    }

    renderBuyRecommendations(recommendationsData.topBuy || []);
    renderSellRecommendations(recommendationsData.topSell || []);
    renderSpreads(recommendationsData);
}

function renderBuyRecommendations(stocks) {
    const container = document.getElementById('buy-recommendations');
    if (!stocks.length) {
        container.innerHTML = '<div class="empty-state" style="min-height:200px"><div class="empty-icon">&mdash;</div><p>No buy signals available</p></div>';
        return;
    }
    container.innerHTML = stocks.map((s, i) => createRecCard(s, i + 1, 'buy')).join('');

    // Create mini charts
    stocks.forEach((s, i) => {
        const chartEl = document.getElementById(`rec-chart-buy-${i}`);
        if (chartEl) createMiniChart(chartEl, s.symbol, true);
    });
}

function renderSellRecommendations(stocks) {
    const container = document.getElementById('sell-recommendations');
    if (!stocks.length) {
        container.innerHTML = '<div class="empty-state" style="min-height:200px"><div class="empty-icon">&mdash;</div><p>No sell signals available</p></div>';
        return;
    }
    container.innerHTML = stocks.map((s, i) => createRecCard(s, i + 1, 'sell')).join('');

    stocks.forEach((s, i) => {
        const chartEl = document.getElementById(`rec-chart-sell-${i}`);
        if (chartEl) createMiniChart(chartEl, s.symbol, false);
    });
}

function createRecCard(stock, rank, type) {
    const isUp = stock.changePct >= 0;
    return `
        <div class="rec-card ${type}-card" onclick="loadChartForSymbol('${stock.symbol}')">
            <span class="rec-rank">#${rank}</span>
            <div class="rec-header">
                <span class="rec-symbol">${stock.symbol}</span>
                <span class="rec-signal ${type}">${type === 'buy' ? 'BUY' : 'SELL'}</span>
            </div>
            <div class="rec-price-row">
                <span class="rec-price">₹${formatNumber(stock.price)}</span>
                <span class="rec-change ${isUp ? 'up' : 'down'}">
                    ${isUp ? '▲' : '▼'} ${Math.abs(stock.changePct).toFixed(2)}%
                </span>
            </div>
            <div class="rec-metrics">
                <div class="rec-metric">
                    <div class="rec-metric-label">${type === 'buy' ? 'Buy' : 'Sell'} Score</div>
                    <div class="rec-metric-value" style="color:${type === 'buy' ? 'var(--green)' : 'var(--red)'}">${type === 'buy' ? stock.buyScore : stock.sellScore}/100</div>
                </div>
                <div class="rec-metric">
                    <div class="rec-metric-label">PCR (OI)</div>
                    <div class="rec-metric-value">${stock.pcrOI}</div>
                </div>
                <div class="rec-metric">
                    <div class="rec-metric-label">CE IV</div>
                    <div class="rec-metric-value">${stock.avgCeIV}%</div>
                </div>
                <div class="rec-metric">
                    <div class="rec-metric-label">PE IV</div>
                    <div class="rec-metric-value">${stock.avgPeIV}%</div>
                </div>
            </div>
            <div class="rec-chart" id="rec-chart-${type}-${rank - 1}"></div>
        </div>
    `;
}

function createMiniChart(container, symbol, bullish) {
    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 80,
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: 'transparent',
        },
        grid: {
            vertLines: { visible: false },
            horzLines: { visible: false },
        },
        rightPriceScale: { visible: false },
        timeScale: { visible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Hidden },
        handleScroll: false,
        handleScale: false,
    });

    const color = bullish ? 'rgba(16,185,129,0.6)' : 'rgba(239,68,68,0.6)';
    const topColor = bullish ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)';

    const series = chart.addAreaSeries({
        lineColor: color,
        topColor: topColor,
        bottomColor: 'transparent',
        lineWidth: 2,
    });

    // Generate mini sparkline data
    const data = [];
    let price = 100;
    const trend = bullish ? 0.002 : -0.002;
    const baseDate = new Date('2025-06-01');

    for (let i = 0; i < 30; i++) {
        const d = new Date(baseDate);
        d.setDate(baseDate.getDate() + i);
        if (d.getDay() === 0 || d.getDay() === 6) continue;
        price += price * (trend + (Math.random() - 0.5) * 0.02);
        data.push({ time: d.toISOString().split('T')[0], value: price });
    }

    series.setData(data);
    chart.timeScale().fitContent();
}

// ============================================================
// Spreads
// ============================================================
function renderSpreads(data) {
    renderSpreadCategory('bull-call-spreads', data.bestBullCallSpread || [], 'bullCallSpread');
    renderSpreadCategory('bear-call-spreads', data.bestBearCallSpread || [], 'bearCallSpread');
    renderSpreadCategory('bull-put-spreads', data.bestBullPutSpread || [], 'bullPutSpread');
    renderSpreadCategory('bear-put-spreads', data.bestBearPutSpread || [], 'bearPutSpread');
}

function renderSpreadCategory(containerId, stocks, spreadKey) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!stocks || stocks.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="min-height:100px; font-size: 0.75rem;">
                <div class="empty-icon">&mdash;</div>
                <p>Live options pricing unavailable.</p>
                <p style="color:var(--text-muted); margin-top:4px;">(Market is closed or NSE API is rate-limiting)</p>
            </div>
        `;
        return;
    }

    container.innerHTML = stocks.map(stock => {
        const spread = stock.spreads && stock.spreads[spreadKey];
        if (!spread) return '';

        const rr = spread.riskReward || 0;
        const rrClass = rr >= 1.5 ? 'good' : rr >= 1 ? 'neutral' : 'bad';

        const isCall = spreadKey.includes('Call');
        const isBull = spreadKey.includes('bull') || spreadKey.includes('Bull');

        // Determine leg labels based on spread type
        let longLeg, shortLeg;
        if (spreadKey === 'bullCallSpread') {
            longLeg = { label: 'BUY CALL', strike: spread.longStrike, prem: spread.longPremium };
            shortLeg = { label: 'SELL CALL', strike: spread.shortStrike, prem: spread.shortPremium };
        } else if (spreadKey === 'bearCallSpread') {
            longLeg = { label: 'BUY CALL', strike: spread.longStrike, prem: spread.longPremium };
            shortLeg = { label: 'SELL CALL', strike: spread.shortStrike, prem: spread.shortPremium };
        } else if (spreadKey === 'bullPutSpread') {
            longLeg = { label: 'BUY PUT', strike: spread.longStrike, prem: spread.longPremium };
            shortLeg = { label: 'SELL PUT', strike: spread.shortStrike, prem: spread.shortPremium };
        } else {
            longLeg = { label: 'BUY PUT', strike: spread.longStrike, prem: spread.longPremium };
            shortLeg = { label: 'SELL PUT', strike: spread.shortStrike, prem: spread.shortPremium };
        }

        const costLabel = spread.netDebit !== undefined ? 'Net Debit' : 'Net Credit';
        const costValue = spread.netDebit !== undefined ? spread.netDebit : spread.netCredit;

        return `
            <div class="spread-card">
                <div class="spread-card-header">
                    <span class="spread-symbol">${stock.symbol} — ₹${formatNumber(stock.price)}</span>
                    <span class="spread-rr ${rrClass}">R:R ${rr}x</span>
                </div>
                <div class="spread-legs">
                    <div class="spread-leg">
                        <div class="spread-leg-label long">${longLeg.label}</div>
                        <div class="spread-leg-strike">₹${formatNumber(longLeg.strike)}</div>
                        <div class="spread-leg-prem">Premium: ₹${longLeg.prem}</div>
                    </div>
                    <div class="spread-leg">
                        <div class="spread-leg-label short">${shortLeg.label}</div>
                        <div class="spread-leg-strike">₹${formatNumber(shortLeg.strike)}</div>
                        <div class="spread-leg-prem">Premium: ₹${shortLeg.prem}</div>
                    </div>
                </div>
                <div class="spread-metrics">
                    <div class="spread-metric">
                        <div class="spread-metric-label">${costLabel}</div>
                        <div class="spread-metric-value">₹${formatNumber(costValue)}</div>
                    </div>
                    <div class="spread-metric">
                        <div class="spread-metric-label">Max Profit</div>
                        <div class="spread-metric-value" style="color:var(--green)">₹${formatNumber(spread.maxProfit)}</div>
                    </div>
                    <div class="spread-metric">
                        <div class="spread-metric-label">Max Loss</div>
                        <div class="spread-metric-value" style="color:var(--red)">₹${formatNumber(spread.maxLoss)}</div>
                    </div>
                    <div class="spread-metric">
                        <div class="spread-metric-label">Breakeven</div>
                        <div class="spread-metric-value">₹${formatNumber(spread.breakeven)}</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================================
// Backtest
// ============================================================
function initBacktest() {
    document.getElementById('bt-run-btn').addEventListener('click', runBacktest);
}

async function runBacktest() {
    const btn = document.getElementById('bt-run-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> Running...';

    const symbol = document.getElementById('bt-symbol').value;
    const strategy = document.getElementById('bt-strategy').value;
    const capital = parseInt(document.getElementById('bt-capital').value) || 100000;
    const fromDate = document.getElementById('bt-from').value;
    const toDate = document.getElementById('bt-to').value;

    // Convert dates to DD-MM-YYYY
    const fromFormatted = fromDate ? fromDate.split('-').reverse().join('-') : undefined;
    const toFormatted = toDate ? toDate.split('-').reverse().join('-') : undefined;

    const result = await fetchAPI('/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            symbol,
            strategy,
            capital,
            fromDate: fromFormatted,
            toDate: toFormatted,
        }),
    });

    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">&gt;</span> Run Backtest';

    if (result) {
        renderBacktestResults(result);
    } else {
        document.getElementById('backtest-results').innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">⚠️</div>
                <p>Failed to run backtest. Please try again.</p>
            </div>
        `;
    }
}

function renderBacktestResults(result) {
    const container = document.getElementById('backtest-results');
    const m = result.metrics || {};
    const strategyNames = {
        sma_crossover: 'SMA Crossover (9/21)',
        rsi: 'RSI Overbought/Oversold',
        macd: 'MACD Signal Crossover',
        bollinger: 'Bollinger Band Breakout',
    };

    const totalPnLClass = m.totalPnL >= 0 ? 'positive' : 'negative';
    const returnClass = m.totalReturnPct >= 0 ? 'positive' : 'negative';

    container.innerHTML = `
        <div style="margin-bottom:16px">
            <span style="font-size:0.85rem;color:var(--text-muted);">${result.symbol} — ${strategyNames[result.strategy] || result.strategy}</span>
            ${result.demo ? '<span class="badge" style="margin-left:8px;">Demo Data</span>' : ''}
        </div>
        <div class="bt-metrics-grid">
            <div class="bt-metric-card highlight">
                <div class="bt-metric-label">Total P&L</div>
                <div class="bt-metric-value ${totalPnLClass}">₹${formatNumber(m.totalPnL)}</div>
            </div>
            <div class="bt-metric-card highlight">
                <div class="bt-metric-label">Return</div>
                <div class="bt-metric-value ${returnClass}">${m.totalReturnPct}%</div>
            </div>
            <div class="bt-metric-card">
                <div class="bt-metric-label">Win Rate</div>
                <div class="bt-metric-value">${m.winRate}%</div>
            </div>
            <div class="bt-metric-card">
                <div class="bt-metric-label">Sharpe Ratio</div>
                <div class="bt-metric-value">${m.sharpeRatio}</div>
            </div>
            <div class="bt-metric-card">
                <div class="bt-metric-label">Total Trades</div>
                <div class="bt-metric-value">${m.totalTrades}</div>
            </div>
            <div class="bt-metric-card">
                <div class="bt-metric-label">Winners</div>
                <div class="bt-metric-value positive">${m.winningTrades}</div>
            </div>
            <div class="bt-metric-card">
                <div class="bt-metric-label">Losers</div>
                <div class="bt-metric-value negative">${m.losingTrades}</div>
            </div>
            <div class="bt-metric-card">
                <div class="bt-metric-label">Max Drawdown</div>
                <div class="bt-metric-value negative">${m.maxDrawdownPct}%</div>
            </div>
        </div>
        <div class="bt-chart-container" id="bt-equity-chart"></div>
        <h4 class="bt-trades-title">📋 Trade Log</h4>
        <div style="overflow-x:auto">
            <table class="bt-trades-table">
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Date</th>
                        <th>Price</th>
                        <th>Shares</th>
                        <th>P&L</th>
                        <th>P&L %</th>
                    </tr>
                </thead>
                <tbody>
                    ${(result.trades || []).map(t => `
                        <tr class="${t.type.includes('BUY') ? 'buy-row' : 'sell-row'}">
                            <td>${t.type}</td>
                            <td>${t.date}</td>
                            <td>₹${formatNumber(t.price)}</td>
                            <td>${t.shares}</td>
                            <td style="color:${(t.pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${t.pnl !== undefined ? '₹' + formatNumber(t.pnl) : '—'}</td>
                            <td style="color:${(t.pnlPct || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${t.pnlPct !== undefined ? t.pnlPct + '%' : '—'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    // Render equity curve chart
    if (result.equityCurve && result.equityCurve.length > 0) {
        const chartContainer = document.getElementById('bt-equity-chart');
        const chart = LightweightCharts.createChart(chartContainer, {
            width: chartContainer.clientWidth,
            height: 350,
            layout: {
                background: { type: 'solid', color: '#1a1f2e' },
                textColor: '#94a3b8',
                fontFamily: "'Inter', sans-serif",
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.03)' },
                horzLines: { color: 'rgba(255,255,255,0.03)' },
            },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.06)' },
        });

        const equitySeries = chart.addAreaSeries({
            lineColor: '#06b6d4',
            topColor: 'rgba(6,182,212,0.2)',
            bottomColor: 'rgba(6,182,212,0.0)',
            lineWidth: 2,
        });

        equitySeries.setData(result.equityCurve.map(d => ({
            time: d.date,
            value: d.value,
        })));

        chart.timeScale().fitContent();

        // Resize
        const ro = new ResizeObserver(() => {
            chart.resize(chartContainer.clientWidth, 350);
        });
        ro.observe(chartContainer);
    }
}

// ============================================================
// Demo Data Generator
// ============================================================
function generateDemoRecommendations() {
    const stocks = [
        ['RELIANCE', 2456.75, 3.21], ['TCS', 3890.50, 2.87], ['INFY', 1567.30, 2.45],
        ['HDFCBANK', 1678.90, 1.98], ['ICICIBANK', 1234.60, 1.76],
        ['TATAMOTORS', 678.45, -2.34], ['BAJFINANCE', 6789.30, -1.89],
        ['SBIN', 567.80, -1.56], ['WIPRO', 456.25, -1.23], ['SUNPHARMA', 1234.50, -0.98],
    ];

    const analyses = stocks.map(([symbol, price, change]) => {
        const buyScore = change > 0 ? 50 + Math.floor(Math.random() * 45) : Math.floor(Math.random() * 40);
        const sellScore = change < 0 ? 50 + Math.floor(Math.random() * 45) : Math.floor(Math.random() * 40);
        const atm = Math.round(price / 50) * 50;

        return {
            symbol, price, changePct: change, buyScore, sellScore,
            pcrOI: +(0.5 + Math.random() * 1.3).toFixed(2),
            pcrVol: +(0.4 + Math.random() * 1.6).toFixed(2),
            avgCeIV: +(15 + Math.random() * 25).toFixed(2),
            avgPeIV: +(15 + Math.random() * 25).toFixed(2),
            totalCeOI: Math.floor(100000 + Math.random() * 5000000),
            totalPeOI: Math.floor(100000 + Math.random() * 5000000),
            atmStrike: atm,
            spreads: {
                bullCallSpread: makeSpread('Bull Call Spread', 'Moderately Bullish', atm, atm + 100),
                bearCallSpread: makeSpread('Bear Call Spread', 'Moderately Bearish', atm, atm + 100),
                bullPutSpread: makeSpread('Bull Put Spread', 'Moderately Bullish', atm - 100, atm),
                bearPutSpread: makeSpread('Bear Put Spread', 'Moderately Bearish', atm - 100, atm),
            },
        };
    });

    // Sort for recommendations
    const topBuy = [...analyses].sort((a, b) => b.buyScore - a.buyScore).slice(0, 5);
    const topSell = [...analyses].sort((a, b) => b.sellScore - a.sellScore).slice(0, 5);

    return {
        topBuy, topSell,
        bestBullCallSpread: topBuy.slice(0, 5),
        bestBearCallSpread: topSell.slice(0, 5),
        bestBullPutSpread: topBuy.slice(0, 5),
        bestBearPutSpread: topSell.slice(0, 5),
    };
}

function makeSpread(strategy, outlook, strike1, strike2) {
    const prem1 = +(20 + Math.random() * 60).toFixed(2);
    const prem2 = +(5 + Math.random() * 35).toFixed(2);
    const net = +(prem1 - prem2).toFixed(2);
    const maxProfit = +((strike2 - strike1) - net).toFixed(2);
    const rr = +(maxProfit / Math.max(net, 0.01)).toFixed(2);

    const isDebit = strategy.includes('Bull Call') || strategy.includes('Bear Put');
    const result = {
        strategy, outlook, riskReward: rr,
        longStrike: isDebit ? strike1 : strike2,
        shortStrike: isDebit ? strike2 : strike1,
        longPremium: prem1, shortPremium: prem2,
        maxProfit: Math.abs(maxProfit), maxLoss: Math.abs(net),
        breakeven: +(strike1 + net).toFixed(2),
        longIV: +(15 + Math.random() * 20).toFixed(2),
        shortIV: +(15 + Math.random() * 20).toFixed(2),
    };
    if (isDebit) result.netDebit = Math.abs(net);
    else result.netCredit = Math.abs(net);
    return result;
}

// ============================================================
// Chart Toolbar
// ============================================================
function initChartToolbar() {
    // Chart type buttons
    document.querySelectorAll('#chart-type-group .tool-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#chart-type-group .tool-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            chartType = btn.dataset.type;
            applyChartData();
        });
    });

    // Timeframe buttons
    document.querySelectorAll('#timeframe-group .tool-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#timeframe-group .tool-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            chartTimeframe = btn.dataset.tf;
            applyChartData();
        });
    });

    // Indicator checkboxes
    document.querySelectorAll('#indicator-toggles input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => { applyChartData(); });
    });

    // Height slider
    const slider = document.getElementById('chart-height-slider');
    const valueLabel = document.getElementById('chart-height-value');
    slider.addEventListener('input', () => {
        chartHeight = parseInt(slider.value);
        valueLabel.textContent = chartHeight + 'px';
        document.querySelector('.chart-area').style.height = chartHeight + 'px';
        if (mainChart) mainChart.resize(document.getElementById('main-chart').clientWidth, chartHeight);
    });

    // Stock info button
    document.getElementById('stock-info-btn').addEventListener('click', () => {
        openStockPanel(currentSymbol);
    });
}

// ============================================================
// Stock Detail Side Panel
// ============================================================
function initStockPanel() {
    document.getElementById('close-panel-btn').addEventListener('click', closeStockPanel);
    document.getElementById('stock-panel-backdrop').addEventListener('click', closeStockPanel);

    document.getElementById('panel-view-chart').addEventListener('click', () => {
        closeStockPanel();
        document.getElementById('nav-dashboard').click();
        loadChartData(panelSymbol);
        document.getElementById('chart-symbol-select').value = panelSymbol;
        currentSymbol = panelSymbol;
    });

    document.getElementById('panel-run-backtest').addEventListener('click', () => {
        closeStockPanel();
        document.getElementById('nav-backtest').click();
        document.getElementById('bt-symbol').value = panelSymbol;
    });

    document.getElementById('panel-view-options').addEventListener('click', () => {
        closeStockPanel();
        window.open(`https://www.nseindia.com/option-chain?symbolCode=-10009&symbol=${panelSymbol}&type=equity`, '_blank');
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.getElementById('stock-panel').classList.contains('open')) {
            closeStockPanel();
        }
    });
}

async function openStockPanel(symbol) {
    panelSymbol = symbol;
    const panel = document.getElementById('stock-panel');
    const backdrop = document.getElementById('stock-panel-backdrop');
    panel.classList.add('open');
    backdrop.style.opacity = '1';
    backdrop.style.pointerEvents = 'all';

    document.getElementById('panel-stock-name').textContent = symbol;
    document.getElementById('panel-price').textContent = '...';
    document.getElementById('panel-change').textContent = '...';
    document.getElementById('panel-change').className = 'panel-change';
    document.getElementById('panel-news-badge').textContent = 'LOADING';
    document.getElementById('panel-news-list').innerHTML = '<div class="panel-loading">Fetching news...</div>';

    const quote = await fetchAPI(`/stock/${symbol}/quote`);
    if (quote) {
        document.getElementById('panel-price').textContent = `${formatNumber(quote.lastPrice)}`;
        const isUp = quote.pChange >= 0;
        document.getElementById('panel-change').textContent = `${isUp ? '+' : ''}${quote.pChange.toFixed(2)}%`;
        document.getElementById('panel-change').className = `panel-change ${isUp ? 'up' : 'down'}`;
    } else {
        document.getElementById('panel-price').textContent = '--';
        document.getElementById('panel-change').textContent = 'N/A';
    }

    const newsResp = await fetchAPI(`/stock/${symbol}/news`);
    const articles = newsResp?.articles || [];
    document.getElementById('panel-news-badge').textContent = `${articles.length}`;

    if (articles.length > 0) {
        document.getElementById('panel-news-list').innerHTML = articles.map(a => {
            const tagsHtml = (a.tags || []).map(t =>
                `<span class="news-badge-tag ${t}">${t.toUpperCase()}</span>`
            ).join('');
            return `
                <a class="news-card" href="${a.link}" target="_blank" rel="noopener noreferrer">
                    <div class="news-card-title">${a.title}${tagsHtml}</div>
                    <div class="news-card-meta">
                        <span class="news-source">${a.source}</span>
                        <span class="news-time">${a.timeAgo}</span>
                    </div>
                    ${a.description ? `<div class="news-card-desc">${a.description}</div>` : ''}
                </a>
            `;
        }).join('');
    } else {
        document.getElementById('panel-news-list').innerHTML = '<div class="panel-loading">No news articles found</div>';
    }
}

function closeStockPanel() {
    document.getElementById('stock-panel').classList.remove('open');
    const backdrop = document.getElementById('stock-panel-backdrop');
    backdrop.style.opacity = '0';
    backdrop.style.pointerEvents = 'none';
}

// ============================================================
// Global Stock Search
// ============================================================
function initGlobalSearch() {
    const input = document.getElementById('global-search-input');
    const btn = document.getElementById('global-search-btn');
    if (!input || !btn) return;

    btn.addEventListener('click', () => performGlobalSearch(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') performGlobalSearch(input.value);
    });
}

async function performGlobalSearch(symbol) {
    if (!symbol) return;
    symbol = symbol.toUpperCase().trim();
    showToast(`Analyzing ${symbol} using AI Advisor...`, 'info', 2000);
    
    try {
        const data = await fetchAPI(`/advisor/analyze/${symbol}`);
        if (data && !data.error) {
            openPickDetailModal(data);
        } else if (data && data.error) {
            showToast(data.error, 'error');
        }
    } catch (err) {
        showToast('Analysis request failed.', 'error');
    }
}

// ============================================================
// Market News Feed
// ============================================================
async function loadNewsFeed() {
    const ticker = document.getElementById('news-ticker');
    const badge = document.getElementById('news-feed-badge');
    if (!ticker) return;

    const data = await fetchAPI('/market/news');
    if (!data || !data.articles || data.articles.length === 0) {
        ticker.innerHTML = '<div class="panel-loading">No news available</div>';
        badge.textContent = '--';
        return;
    }

    badge.textContent = `${data.articles.length}`;
    ticker.innerHTML = data.articles.map(a => {
        const tagsHtml = (a.tags || []).map(t =>
            `<span class="news-badge-tag ${t}">${t.toUpperCase()}</span>`
        ).join('');
        return `
            <a class="news-ticker-item" href="${a.link}" target="_blank" rel="noopener noreferrer">
                <span class="news-time">${a.timeAgo}</span>
                <span class="news-headline">${a.title}${tagsHtml}</span>
                <span class="news-source-tag">${a.source}</span>
            </a>
        `;
    }).join('');
}

// ============================================================
// Live Data Polling
// ============================================================
async function initLivePolling() {
    await checkMarketStatus();
    // Check market status every 60 seconds
    setInterval(checkMarketStatus, 60000);
}

async function checkMarketStatus() {
    const status = await fetchAPI('/market/status');
    if (status) {
        isMarketOpen = status.isOpen;
        const statusDot = document.querySelector('.status-dot');
        const statusText = document.querySelector('.status-text');
        if (isMarketOpen) {
            statusDot?.classList.add('open');
            statusDot?.classList.remove('closed');
            if (statusText) statusText.textContent = 'Market Open';
            startLivePolling();
        } else {
            statusDot?.classList.remove('open');
            statusDot?.classList.add('closed');
            if (statusText) statusText.textContent = 'Market Closed';
            stopLivePolling();
        }
    }
}

function startLivePolling() {
    if (livePollingTimer) return; // Already polling
    console.log('Starting live data polling (10s intervals)');
    livePollingTimer = setInterval(async () => {
        // Update current chart with latest tick
        const quote = await fetchAPI(`/stock/${currentSymbol}/live`);
        if (quote && quote.lastPrice) {
            // Update chart info bar
            document.getElementById('chart-stock-name').textContent =
                `${currentSymbol} • ₹${formatNumber(quote.lastPrice)}`;

            // Update latest candle or add a new tick
            if (mainCandleSeries && currentChartData.length > 0) {
                const today = new Date().toISOString().split('T')[0];
                const lastCandle = currentChartData[currentChartData.length - 1];

                if (lastCandle.date === today) {
                    // Update today's candle
                    lastCandle.close = quote.lastPrice;
                    lastCandle.high = Math.max(lastCandle.high, quote.lastPrice);
                    lastCandle.low = Math.min(lastCandle.low, quote.lastPrice);
                    lastCandle.volume = quote.volume || lastCandle.volume;
                } else {
                    // New day — add new candle
                    currentChartData.push({
                        date: today,
                        open: quote.lastPrice,
                        high: quote.lastPrice,
                        low: quote.lastPrice,
                        close: quote.lastPrice,
                        volume: quote.volume || 0,
                    });
                }
                applyChartData();
            }
        }
    }, 10000);
}

function stopLivePolling() {
    if (livePollingTimer) {
        clearInterval(livePollingTimer);
        livePollingTimer = null;
        console.log('Stopped live data polling');
    }
}

// ============================================================
// Paper Trading
// ============================================================
function initPaperTrading() {
    document.getElementById('paper-buy-btn').addEventListener('click', () => executePaperTrade('buy'));
    document.getElementById('paper-sell-btn').addEventListener('click', () => executePaperTrade('sell'));
    document.getElementById('paper-reset-btn').addEventListener('click', resetPaperPortfolio);
    loadPaperPortfolio();
    loadPaperTrades();
    // Auto-refresh portfolio every 15s when on Paper Trade tab
    setInterval(() => {
        const tab = document.getElementById('tab-paper-trade');
        if (tab && tab.classList.contains('active')) {
            loadPaperPortfolio();
        }
    }, 15000);
}

async function loadPaperPortfolio() {
    const data = await fetchAPI('/paper/portfolio');
    if (!data) return;

    // Update summary cards
    document.getElementById('paper-cash').textContent = `₹${formatNumber(data.cash)}`;
    document.getElementById('paper-invested').textContent = `₹${formatNumber(data.invested)}`;
    document.getElementById('paper-current').textContent = `₹${formatNumber(data.currentValue)}`;
    document.getElementById('paper-total').textContent = `₹${formatNumber(data.totalValue)}`;

    const pnlEl = document.getElementById('paper-pnl');
    pnlEl.textContent = `${data.totalPnl >= 0 ? '+' : ''}₹${formatNumber(data.totalPnl)} (${data.totalPnlPct}%)`;
    pnlEl.className = `portfolio-value ${data.totalPnl >= 0 ? 'positive' : 'negative'}`;

    // Update positions table
    const posEl = document.getElementById('paper-positions');
    if (data.positions.length === 0) {
        posEl.innerHTML = '<div class="empty-state" style="min-height:150px"><div class="empty-icon">&mdash;</div><p>No open positions</p></div>';
    } else {
        posEl.innerHTML = `
            <table class="bt-trades-table">
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Qty</th>
                        <th>Avg Price</th>
                        <th>Current</th>
                        <th>Invested</th>
                        <th>Value</th>
                        <th>P&L</th>
                        <th>P&L %</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.positions.map(p => `
                        <tr>
                            <td>
                                <div style="font-weight:700;color:var(--accent-cyan);cursor:pointer;" onclick="performGlobalSearch('${p.symbol}')">${p.symbol}</div>
                                ${p.latestNews && p.latestNews.length > 0 ? 
                                    `<div class="port-news-alert">
                                        📰 ${p.latestNews[0].title.substring(0, 30)}...
                                    </div>` : ''}
                            </td>
                            <td>${p.qty}</td>
                            <td>₹${formatNumber(p.avgPrice)}</td>
                            <td>₹${formatNumber(p.currentPrice)}</td>
                            <td>₹${formatNumber(p.investedValue)}</td>
                            <td>₹${formatNumber(p.currentValue)}</td>
                            <td style="color:${p.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">
                                ${p.pnl >= 0 ? '+' : ''}₹${formatNumber(p.pnl)}
                            </td>
                            <td style="color:${p.pnlPct >= 0 ? 'var(--green)' : 'var(--red)'}">
                                ${p.pnlPct >= 0 ? '+' : ''}${p.pnlPct}%
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }
}

async function loadPaperTrades() {
    const data = await fetchAPI('/paper/trades');
    if (!data || !data.trades || data.trades.length === 0) return;

    const el = document.getElementById('paper-trades');
    el.innerHTML = `
        <table class="bt-trades-table">
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Amount</th>
                    <th>P&L</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
                ${data.trades.map(t => `
                    <tr class="${t.type === 'BUY' ? 'buy-row' : 'sell-row'}">
                        <td>${t.type}</td>
                        <td>${t.symbol}</td>
                        <td>${t.qty}</td>
                        <td>₹${formatNumber(t.price)}</td>
                        <td>₹${formatNumber(t.cost || t.proceeds)}</td>
                        <td style="color:${(t.pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">
                            ${t.pnl !== undefined ? (t.pnl >= 0 ? '+' : '') + '₹' + formatNumber(t.pnl) : '—'}
                        </td>
                        <td style="font-size:0.75rem;color:var(--text-muted)">
                            ${new Date(t.timestamp).toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' })}
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

async function executePaperTrade(type) {
    const symbol = document.getElementById('paper-symbol').value;
    const qty = parseInt(document.getElementById('paper-qty').value);
    const price = parseFloat(document.getElementById('paper-price').value) || 0;
    const statusEl = document.getElementById('paper-order-status');

    // Disable buttons during execution
    const buyBtn = document.getElementById('paper-buy-btn');
    const sellBtn = document.getElementById('paper-sell-btn');
    buyBtn.disabled = true;
    sellBtn.disabled = true;

    const body = { symbol, qty };
    if (price > 0) body.price = price;

    try {
        const resp = await fetch(`/api/paper/${type}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();

        if (data.error) {
            statusEl.textContent = `[ERR] ${data.error}`;
            statusEl.className = 'paper-order-status error';
        } else {
            const trade = data.trade;
            statusEl.textContent = `[OK] ${trade.type} ${trade.qty}x ${trade.symbol} @ ${formatNumber(trade.price)}`;
            statusEl.className = 'paper-order-status success';
            loadPaperPortfolio();
            loadPaperTrades();
        }
    } catch (e) {
        statusEl.textContent = `[ERR] Trade failed: ${e.message}`;
        statusEl.className = 'paper-order-status error';
    }

    buyBtn.disabled = false;
    sellBtn.disabled = false;
    setTimeout(() => { statusEl.className = 'paper-order-status'; }, 5000);
}

async function resetPaperPortfolio() {
    if (!confirm('Reset portfolio to 10,00,000? All positions and trades will be cleared.')) return;
    await fetch('/api/paper/reset', { method: 'POST' });
    loadPaperPortfolio();
    loadPaperTrades();
    document.getElementById('paper-positions').innerHTML =
        '<div class="empty-state" style="min-height:150px"><div class="empty-icon">&mdash;</div><p>No open positions</p></div>';
    document.getElementById('paper-trades').innerHTML =
        '<div class="empty-state" style="min-height:150px"><div class="empty-icon">&mdash;</div><p>No trades yet</p></div>';
    const statusEl = document.getElementById('paper-order-status');
    statusEl.textContent = '[OK] Portfolio reset successfully';
    statusEl.className = 'paper-order-status success';
    setTimeout(() => { statusEl.className = 'paper-order-status'; }, 3000);
}

// ============================================================
// Utilities
// ============================================================
function formatNumber(num) {
    if (num === undefined || num === null) return '0';
    const n = parseFloat(num);
    if (isNaN(n)) return '0';
    if (Math.abs(n) >= 10000000) return (n / 10000000).toFixed(2) + ' Cr';
    if (Math.abs(n) >= 100000) return (n / 100000).toFixed(2) + ' L';
    return n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

// ============================================================
// AI STRATEGY ENGINE
// ============================================================
let strategyRiskLevel = 'moderate';
let strategyData = null;
let strategyTimerInterval = null;
let strategyTimerSeconds = 300; // 5 minutes
let strategyPollInterval = null;

function initStrategy() {
    // Risk level selector
    document.querySelectorAll('.risk-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.risk-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            strategyRiskLevel = btn.dataset.risk;
        });
    });

    // Generate strategy button
    document.getElementById('strategy-generate-btn').addEventListener('click', () => {
        const budget = parseInt(document.getElementById('advisor-budget').value) || 100000;
        loadStrategy(budget, strategyRiskLevel);
    });
}

async function loadStrategy(budget, riskLevel) {
    const btn = document.getElementById('strategy-generate-btn');
    btn.classList.add('loading');
    btn.innerHTML = '<span class="btn-icon">⏳</span> ANALYZING MARKET...';

    // Show loading state
    document.getElementById('strategy-empty').style.display = 'none';
    document.getElementById('strategy-loading').style.display = 'block';
    document.getElementById('strategy-dashboard').style.display = 'none';

    try {
        const data = await fetchAPI('/strategy/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ budget, riskLevel }),
        });

        btn.classList.remove('loading');
        btn.innerHTML = '<span class="btn-icon">⚡</span> REGENERATE STRATEGY';
        document.getElementById('strategy-loading').style.display = 'none';

        if (!data || data.status === 'loading') {
            // AI engine still scanning
            document.getElementById('strategy-loading').style.display = 'block';
            document.querySelector('.strategy-loading-content h3').textContent =
                'AI Engine Scanning Stocks...';
            document.querySelector('.strategy-loading-content p').textContent =
                data?.message || 'Please wait 30–60 seconds and try again.';

            // Auto-retry after 15 seconds
            setTimeout(() => loadStrategy(budget, riskLevel), 15000);
            return;
        }

        // Unwrap strategy from response
        const strategy = data.strategy || data;
        strategyData = strategy;
        renderStrategyDashboard(strategy);

        // Show dashboard
        document.getElementById('strategy-dashboard').style.display = 'block';

        // Start timer
        startStrategyTimer();

        // Start auto-polling for live updates
        startStrategyPolling();

    } catch (e) {
        btn.classList.remove('loading');
        btn.innerHTML = '<span class="btn-icon">⚡</span> GENERATE TODAY\'S STRATEGY';
        document.getElementById('strategy-loading').style.display = 'none';
        document.getElementById('strategy-empty').style.display = 'block';
        console.error('Strategy generation failed:', e);
    }
}

function renderStrategyDashboard(data) {
    // ── Market Pulse ──
    const pulse = data.marketPulse;
    if (pulse) {
        const badge = document.getElementById('pulse-badge');
        const outlookKey = pulse.outlook.toLowerCase().replace(/\s+/g, '-');
        badge.textContent = pulse.outlook;
        badge.className = 'pulse-badge ' + outlookKey;

        document.getElementById('pulse-buy-count').textContent =
            (pulse.strongBuyCount || 0) + (pulse.buyCount || 0);
        document.getElementById('pulse-hold-count').textContent = pulse.holdCount || 0;
        document.getElementById('pulse-sell-count').textContent =
            (pulse.sellCount || 0) + (pulse.strongSellCount || 0);
        document.getElementById('pulse-stocks-count').textContent =
            pulse.stocksAnalyzed || 0;

        document.getElementById('pulse-text').textContent = pulse.outlookText || '';

        // Sector chips
        const sectorEl = document.getElementById('pulse-sectors');
        let sectorHtml = '';
        if (pulse.topSectors && pulse.topSectors.length > 0) {
            sectorHtml += pulse.topSectors.map(s =>
                `<div class="pulse-sector-chip top">
                    <span>${s.sector}</span>
                    <span class="sector-score" style="color:var(--green)">${s.avgScore}</span>
                </div>`
            ).join('');
        }
        if (pulse.bottomSectors && pulse.bottomSectors.length > 0) {
            sectorHtml += pulse.bottomSectors.map(s =>
                `<div class="pulse-sector-chip bottom">
                    <span>${s.sector}</span>
                    <span class="sector-score" style="color:var(--red)">${s.avgScore}</span>
                </div>`
            ).join('');
        }
        sectorEl.innerHTML = sectorHtml;
    }

    // ── Portfolio Health ──
    const port = data.portfolioHealth;
    if (port) {
        const badge = document.getElementById('portfolio-badge');
        if (port.hasPositions) {
            const pnlClass = port.overallPnl >= 0 ? 'green' : 'red';
            badge.textContent = `${port.positionCount} POSITION${port.positionCount > 1 ? 'S' : ''}`;
            badge.className = 'strat-badge ' + pnlClass;
        } else {
            badge.textContent = 'NO POSITIONS';
            badge.className = 'strat-badge';
        }

        // Summary strip
        const stripEl = document.getElementById('portfolio-summary-strip');
        const pnlCls = port.overallPnl >= 0 ? 'positive' : 'negative';
        stripEl.innerHTML = `
            <div class="pss-card">
                <span class="pss-label">Cash</span>
                <span class="pss-value">₹${formatNumber(port.cash)}</span>
            </div>
            <div class="pss-card">
                <span class="pss-label">Invested</span>
                <span class="pss-value">₹${formatNumber(port.invested || 0)}</span>
            </div>
            <div class="pss-card">
                <span class="pss-label">Current Value</span>
                <span class="pss-value">₹${formatNumber(port.currentValue || 0)}</span>
            </div>
            <div class="pss-card">
                <span class="pss-label">Total P&L</span>
                <span class="pss-value ${pnlCls}">${port.overallPnl >= 0 ? '+' : ''}₹${formatNumber(port.overallPnl)} (${port.overallPnlPct}%)</span>
            </div>
            <div class="pss-card">
                <span class="pss-label">Portfolio Value</span>
                <span class="pss-value">₹${formatNumber(port.totalValue)}</span>
            </div>
        `;

        // Positions
        const posEl = document.getElementById('portfolio-positions');
        if (port.positions && port.positions.length > 0) {
            posEl.innerHTML = port.positions.map(p => {
                const pnlDir = p.pnl >= 0 ? 'up' : 'down';
                const actionCls = p.action.toLowerCase().replace(' ', '-');
                return `
                    <div class="port-pos-row">
                        <span class="port-sym">${p.symbol}</span>
                        <span class="port-qty">${p.qty} qty</span>
                        <span class="port-pnl ${pnlDir}">${p.pnl >= 0 ? '+' : ''}₹${formatNumber(p.pnl)} (${p.pnlPct}%)</span>
                        <span class="port-reason">${p.actionReason}</span>
                        <span class="port-action-badge ${actionCls}">${p.action}</span>
                    </div>`;
            }).join('');
        } else {
            posEl.innerHTML = '<div style="padding:10px 14px;font-size:0.72rem;color:var(--text-muted)">No open positions in paper portfolio.</div>';
        }
    }

    // ── Recommendations ──
    const recs = data.recommendations || [];
    document.getElementById('recs-count-badge').textContent = `${recs.length} ACTION${recs.length !== 1 ? 'S' : ''}`;

    const recsGrid = document.getElementById('strat-recs-grid');
    if (recs.length === 0) {
        recsGrid.innerHTML = `
            <div class="empty-state" style="min-height:120px;grid-column:1/-1">
                <p>No strong buy opportunities match your risk profile right now. Try adjusting risk level or wait for next refresh.</p>
            </div>`;
    } else {
        recsGrid.innerHTML = recs.map((rec, i) => renderRecCard(rec, i)).join('');

        // Animate score bars
        requestAnimationFrame(() => {
            recsGrid.querySelectorAll('.src-score-fill').forEach(bar => {
                const w = bar.dataset.width;
                if (w) bar.style.width = w + '%';
            });
        });
    }

    // ── News Digest ──
    const news = data.newsDigest || [];
    const newsEl = document.getElementById('strat-news-list');
    if (news.length > 0) {
        newsEl.innerHTML = news.map(n => `
            <a class="strat-news-item" href="${n.link}" target="_blank" rel="noopener">
                <div class="strat-news-impact ${n.impact}"></div>
                <div class="sni-body">
                    <div class="sni-title">${n.title}</div>
                    <div class="sni-meta">${n.source} ${n.timeAgo ? '• ' + n.timeAgo : ''}</div>
                </div>
            </a>
        `).join('');
    } else {
        newsEl.innerHTML = '<div style="padding:14px;font-size:0.72rem;color:var(--text-muted)">No market news available.</div>';
    }

    // ── Risk Alerts ──
    const alerts = data.riskAlerts || [];
    const alertsSection = document.getElementById('strat-alerts');
    const alertsEl = document.getElementById('strat-alerts-list');
    if (alerts.length > 0) {
        alertsSection.style.display = 'block';
        alertsEl.innerHTML = alerts.map(a => {
            const icon = a.type === 'warning' ? '⚠️' : 'ℹ️';
            return `
                <div class="strat-alert-item ${a.severity || 'low'}">
                    <span class="alert-icon">${icon}</span>
                    <div class="alert-body">
                        <div class="alert-title">${a.title}</div>
                        <div class="alert-msg">${a.message}</div>
                    </div>
                </div>`;
        }).join('');
    } else {
        alertsSection.style.display = 'none';
    }
}

function renderRecCard(rec, index) {
    const signalClass = rec.signal.toLowerCase().replace(' ', '-');
    const changeClass = rec.changePct >= 0 ? 'up' : 'down';
    const changePrefix = rec.changePct >= 0 ? '+' : '';

    return `
        <div class="strat-rec-card" onclick="openStrategyPickDetail(${index})">
            <div class="src-header">
                <div>
                    <span class="src-symbol">${rec.symbol}</span>
                    <span class="src-sector">${rec.sector}</span>
                </div>
                <span class="src-signal ${signalClass}">${rec.signal}</span>
            </div>

            <div class="src-price-row">
                <span class="src-price">₹${formatNumber(rec.price)}</span>
                <span class="src-change ${changeClass}">${changePrefix}${rec.changePct}%</span>
                <span style="font-family:var(--font-mono);font-size:0.7rem;color:var(--accent-cyan);margin-left:auto">AI: ${rec.aiScore}/100</span>
            </div>

            <div class="src-levels">
                <div class="src-level">
                    <span class="src-level-lbl">Entry</span>
                    <span class="src-level-val">₹${formatNumber(rec.entryPrice)}</span>
                </div>
                <div class="src-level">
                    <span class="src-level-lbl">Stop Loss</span>
                    <span class="src-level-val red">₹${formatNumber(rec.stopLoss)} (-${rec.stopLossPct}%)</span>
                </div>
                <div class="src-level">
                    <span class="src-level-lbl">Target</span>
                    <span class="src-level-val green">₹${formatNumber(rec.target)} (+${rec.targetPct}%)</span>
                </div>
            </div>

            <div class="src-scores">
                <div class="src-score-item">
                    <div class="src-score-lbl"><span>MARKET</span><span>${rec.marketScore}</span></div>
                    <div class="src-score-bar"><div class="src-score-fill market" data-width="${rec.marketScore}" style="width:0%"></div></div>
                </div>
                <div class="src-score-item">
                    <div class="src-score-lbl"><span>NEWS</span><span>${rec.newsScore}</span></div>
                    <div class="src-score-bar"><div class="src-score-fill news" data-width="${rec.newsScore}" style="width:0%"></div></div>
                </div>
                <div class="src-score-item">
                    <div class="src-score-lbl"><span>TECH</span><span>${rec.techScore}</span></div>
                    <div class="src-score-bar"><div class="src-score-fill tech" data-width="${rec.techScore}" style="width:0%"></div></div>
                </div>
                <div class="src-score-item">
                    <div class="src-score-lbl"><span>GREEKS</span><span>${rec.greeksScore || 50}</span></div>
                    <div class="src-score-bar"><div class="src-score-fill greeks" data-width="${rec.greeksScore || 50}" style="width:0%"></div></div>
                </div>
            </div>

            <div class="src-greeks-row">
                <div class="src-greek-chip ${(rec.alpha || 0) >= 0 ? 'green' : 'red'}">
                    <span class="src-greek-label">α Alpha</span>
                    <span class="src-greek-value">${(rec.alpha || 0) >= 0 ? '+' : ''}${(rec.alpha || 0).toFixed(1)}%</span>
                </div>
                <div class="src-greek-chip">
                    <span class="src-greek-label">θ Theta</span>
                    <span class="src-greek-value">${(rec.theta || 0).toFixed(2)}%/d</span>
                </div>
                <div class="src-greek-chip ${(rec.ivPercentile || 50) < 40 ? 'green' : (rec.ivPercentile || 50) > 70 ? 'red' : ''}">
                    <span class="src-greek-label">IV %ile</span>
                    <span class="src-greek-value">${(rec.ivPercentile || 50).toFixed(0)}%</span>
                </div>
                ${rec.maxPain ? `<div class="src-greek-chip">
                    <span class="src-greek-label">Max Pain</span>
                    <span class="src-greek-value">₹${formatNumber(rec.maxPain)}</span>
                </div>` : ''}
            </div>

            <div class="src-reasoning">${rec.reasoning}</div>

            <div class="src-footer">
                <div class="src-alloc">
                    <span class="src-alloc-label">ALLOCATION</span>
                    <span class="src-alloc-value">₹${formatNumber(rec.allocation)}</span>
                    <span class="src-alloc-qty">(${rec.qty} shares)</span>
                </div>
                <button class="src-execute-btn" id="exec-btn-${index}" onclick="event.stopPropagation(); executeStrategyTrade('${rec.symbol}', ${rec.qty}, ${index})">
                    ⚡ EXECUTE TRADE
                </button>
            </div>
        </div>`;
}

async function executeStrategyTrade(symbol, qty, index) {
    const btn = document.getElementById(`exec-btn-${index}`);
    if (!btn || btn.classList.contains('executed')) return;

    btn.textContent = 'EXECUTING...';
    btn.style.opacity = '0.7';

    try {
        const resp = await fetch('/api/paper/buy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, qty }),
        });
        const result = await resp.json();

        if (result.error) {
            btn.textContent = '✕ FAILED';
            btn.style.opacity = '1';
            showToast('sell', `TRADE FAILED: ${symbol}`, result.error, 5000);
            setTimeout(() => {
                btn.textContent = '⚡ EXECUTE TRADE';
            }, 3000);
        } else {
            btn.textContent = '✓ EXECUTED';
            btn.classList.add('executed');
            btn.style.opacity = '1';
            showToast('hold', `TRADE EXECUTED: ${symbol}`,
                `Bought ${qty}x ${symbol} @ ₹${formatNumber(result.trade.price)}`, 6000);
        }
    } catch (e) {
        btn.textContent = '✕ ERROR';
        btn.style.opacity = '1';
        setTimeout(() => {
            btn.textContent = '⚡ EXECUTE TRADE';
        }, 3000);
    }
}

function openStrategyPickDetail(index) {
    if (!strategyData || !strategyData.recommendations) return;
    const rec = strategyData.recommendations[index];
    if (!rec) return;

    // Reuse the existing pick detail modal
    const modal = document.getElementById('pick-detail-modal');
    const f = rec.fundamentals || {};
    const md = rec.marketDetail || {};
    const nd = rec.newsDetail || {};
    const td = rec.techDetail || {};

    document.getElementById('pd-symbol').textContent = rec.symbol;
    document.getElementById('pd-company').textContent = f.companyName || rec.symbol;
    const signalBadge = document.getElementById('pd-signal');
    signalBadge.textContent = rec.signal;
    signalBadge.className = 'pd-signal-badge ' + rec.signal.toLowerCase().replace(' ', '-');

    document.getElementById('pd-price').textContent = '₹' + formatNumber(rec.price);
    const changeEl = document.getElementById('pd-change');
    const prefix = rec.changePct >= 0 ? '+' : '';
    changeEl.textContent = `${prefix}${rec.changePct}%`;
    changeEl.className = 'pd-change ' + (rec.changePct >= 0 ? 'positive' : 'negative');

    const ring = document.getElementById('pd-score-ring');
    const ringColor = rec.aiScore >= 60 ? '#00c896' : (rec.aiScore >= 40 ? '#ffc107' : '#ff5252');
    ring.style.setProperty('--ring-pct', rec.aiScore + '%');
    ring.style.setProperty('--ring-color', ringColor);
    document.getElementById('pd-score-num').textContent = rec.aiScore;

    document.getElementById('pd-narrative').textContent = rec.narrative || rec.reasoning;

    // Fundamentals
    const fundItems = [
        { label: 'Industry', value: f.industry || 'N/A' },
        { label: 'Sector', value: rec.sector },
        { label: 'Stop Loss', value: '₹' + formatNumber(rec.stopLoss) + ` (-${rec.stopLossPct}%)` },
        { label: 'Target', value: '₹' + formatNumber(rec.target) + ` (+${rec.targetPct}%)` },
        { label: 'Open', value: f.open ? '₹' + formatNumber(f.open) : '—' },
        { label: 'Previous Close', value: f.previousClose ? '₹' + formatNumber(f.previousClose) : '—' },
        { label: 'Day High', value: f.dayHigh ? '₹' + formatNumber(f.dayHigh) : '—' },
        { label: 'Day Low', value: f.dayLow ? '₹' + formatNumber(f.dayLow) : '—' },
        { label: '52W High', value: f.high52 ? '₹' + formatNumber(f.high52) : '—' },
        { label: '52W Low', value: f.low52 ? '₹' + formatNumber(f.low52) : '—' },
    ];
    document.getElementById('pd-fundamentals').innerHTML = fundItems.map(item =>
        `<div class="pd-fund-item"><span class="pd-fund-label">${item.label}</span><span class="pd-fund-value">${item.value}</span></div>`
    ).join('');

    // Technical Analysis
    const pos52 = td.pos52wk || 50;
    const scoreBarColor = (val) => val >= 60 ? 'green' : (val >= 40 ? 'yellow' : 'red');
    document.getElementById('pd-tech').innerHTML = `
        <div class="pd-score-row">
            <span class="pd-score-row-label">Technical Score</span>
            <div class="pd-score-bar-track"><div class="pd-score-bar-fill ${scoreBarColor(rec.techScore)}" style="width:${rec.techScore}%"></div></div>
            <span class="pd-score-value">${rec.techScore}/100</span>
        </div>
        <div class="pd-detail-reason">${td.topReason || 'Within normal range'}</div>
        <div class="pd-52wk-bar">
            <div style="font-size:0.78rem; color:rgba(255,255,255,0.6); margin-bottom:4px;">52-Week Position</div>
            <div class="pd-52wk-bar-track">
                <div class="pd-52wk-marker" style="left:${Math.min(100, Math.max(0, pos52))}%"></div>
            </div>
            <div class="pd-52wk-labels">
                <span>₹${f.low52 ? formatNumber(f.low52) : '—'}</span>
                <span>Current: ${pos52.toFixed ? pos52.toFixed(0) : pos52}%</span>
                <span>₹${f.high52 ? formatNumber(f.high52) : '—'}</span>
            </div>
        </div>
    `;

    // Market Sentiment
    const pcr = md.pcrOI || 0;
    document.getElementById('pd-market').innerHTML = `
        <div class="pd-score-row">
            <span class="pd-score-row-label">Market Score</span>
            <div class="pd-score-bar-track"><div class="pd-score-bar-fill ${scoreBarColor(rec.marketScore)}" style="width:${rec.marketScore}%"></div></div>
            <span class="pd-score-value">${rec.marketScore}/100</span>
        </div>
        <div class="pd-detail-reason">${md.topReason || 'No options data'}</div>
        ${pcr > 0 ? `
        <div class="pd-fundamentals-grid" style="margin-top:14px">
            <div class="pd-fund-item"><span class="pd-fund-label">PCR (OI)</span><span class="pd-fund-value">${pcr.toFixed(2)}</span></div>
            <div class="pd-fund-item"><span class="pd-fund-label">Avg CE IV</span><span class="pd-fund-value">${(md.avgCeIV || 0).toFixed(1)}%</span></div>
            <div class="pd-fund-item"><span class="pd-fund-label">Avg PE IV</span><span class="pd-fund-value">${(md.avgPeIV || 0).toFixed(1)}%</span></div>
        </div>` : ''}
    `;

    // News Sentiment
    const bull = nd.bullish || 0;
    const bear = nd.bearish || 0;
    const neut = nd.neutral || 0;
    const newsTotal = bull + bear + neut;
    const sentEl = document.getElementById('pd-news-sentiment');
    if (newsTotal > 0) {
        sentEl.innerHTML = `
            <span class="pd-sent-count" style="color:#00c896">${bull} 🐂</span>
            <div class="pd-sent-bar">
                <div class="pd-sent-bull" style="width:${(bull/newsTotal*100).toFixed(0)}%"></div>
                <div class="pd-sent-neutral" style="width:${(neut/newsTotal*100).toFixed(0)}%"></div>
                <div class="pd-sent-bear" style="width:${(bear/newsTotal*100).toFixed(0)}%"></div>
            </div>
            <span class="pd-sent-count" style="color:#ff5252">${bear} 🐻</span>`;
    } else {
        sentEl.innerHTML = '<span style="font-size:0.82rem; color:rgba(255,255,255,0.5)">No articles analyzed</span>';
    }

    // News Articles
    const articles = rec.newsArticles || [];
    const newsListEl = document.getElementById('pd-news-list');
    if (articles.length > 0) {
        newsListEl.innerHTML = articles.map(a => `
            <a href="${a.link}" target="_blank" rel="noopener" class="pd-news-article">
                <div class="pd-news-title">${a.title}</div>
                <div class="pd-news-meta">
                    <span class="pd-news-source">${a.source}</span>
                    <span>•</span>
                    <span>${a.timeAgo}</span>
                </div>
            </a>
        `).join('');
    } else {
        newsListEl.innerHTML = '<div style="font-size:0.82rem; color:rgba(255,255,255,0.5)">No news</div>';
    }

    // Allocation
    document.getElementById('pd-alloc').innerHTML = `
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">₹${formatNumber(rec.allocation)}</span>
            <span class="pd-alloc-label">Allocated</span>
        </div>
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">${rec.qty}</span>
            <span class="pd-alloc-label">Shares</span>
        </div>
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">₹${formatNumber(rec.stopLoss)}</span>
            <span class="pd-alloc-label">Stop Loss</span>
        </div>
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">₹${formatNumber(rec.target)}</span>
            <span class="pd-alloc-label">Target</span>
        </div>
    `;

    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

// ── Strategy Timer ──

function startStrategyTimer() {
    stopStrategyTimer();
    strategyTimerSeconds = 300;

    document.getElementById('strategy-timer-bar').style.display = 'flex';
    updateTimerDisplay();

    strategyTimerInterval = setInterval(() => {
        strategyTimerSeconds--;
        if (strategyTimerSeconds <= 0) {
            strategyTimerSeconds = 300;
            // Trigger visual refresh indication
            const countEl = document.getElementById('timer-refresh-count');
            const refreshCount = (strategyData?.meta?.refreshCount || 0) + 1;
            countEl.textContent = `Refresh #${refreshCount}`;
        }
        updateTimerDisplay();
    }, 1000);
}

function stopStrategyTimer() {
    if (strategyTimerInterval) {
        clearInterval(strategyTimerInterval);
        strategyTimerInterval = null;
    }
}

function updateTimerDisplay() {
    const mins = Math.floor(strategyTimerSeconds / 60);
    const secs = strategyTimerSeconds % 60;
    document.getElementById('timer-countdown').textContent =
        `${mins}:${secs.toString().padStart(2, '0')}`;

    const pct = (strategyTimerSeconds / 300) * 100;
    document.getElementById('timer-progress-fill').style.width = pct + '%';
}

// ── Strategy Polling (auto-refresh from backend) ──

function startStrategyPolling() {
    stopStrategyPolling();

    // Poll every 5 minutes for updated strategy from backend
    strategyPollInterval = setInterval(async () => {
        try {
            const data = await fetchAPI('/strategy/live');
            if (data && !data.status) {
                strategyData = data;
                renderStrategyDashboard(data);

                // Update refresh count display
                const count = data.meta?.refreshCount || 0;
                if (count > 0) {
                    document.getElementById('timer-refresh-count').textContent =
                        `Refresh #${count}`;
                }

                // Reset timer
                strategyTimerSeconds = 300;
            }
        } catch (e) {
            console.log('Strategy poll failed, will retry:', e);
        }
    }, 300000); // 5 minutes
}

function stopStrategyPolling() {
    if (strategyPollInterval) {
        clearInterval(strategyPollInterval);
        strategyPollInterval = null;
    }
}

// Expose functions to global scope for inline onclick handlers
window.openStrategyPickDetail = openStrategyPickDetail;
window.executeStrategyTrade = executeStrategyTrade;

async function loadAdvisorPicks(budget, riskLevel) {
    const btn = document.getElementById('advisor-generate-btn');
    btn.classList.add('loading');
    btn.innerHTML = '<span class="btn-icon">⏳</span> ANALYZING...';

    const data = await fetchAPI('/advisor/picks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ budget, riskLevel }),
    });

    btn.classList.remove('loading');
    btn.innerHTML = '<span class="btn-icon">⚡</span> GENERATE PICKS';
    advisorHasGenerated = true;

    if (!data) {
        document.getElementById('advisor-picks').innerHTML =
            '<div class="empty-state"><div class="empty-icon">⚠️</div><p>Failed to fetch picks. Server may be scanning stocks — try again in 30 seconds.</p></div>';
        return;
    }

    const { picks, summary } = data;

    // Update summary strip
    if (summary && picks && picks.length > 0) {
        const sumEl = document.getElementById('advisor-summary');
        sumEl.style.display = 'block';
        document.getElementById('summary-invested').textContent = '₹' + formatNumber(summary.totalInvested);
        document.getElementById('summary-remaining').textContent = '₹' + formatNumber(summary.cashRemaining);
        document.getElementById('summary-picks').textContent = summary.numPicks;
        document.getElementById('summary-avg-score').textContent = summary.avgScore;
        document.getElementById('summary-sectors').textContent =
            (summary.sectors || []).length;
    } else {
        document.getElementById('advisor-summary').style.display = 'none';
    }

    // Render picks
    const picksEl = document.getElementById('advisor-picks');
    if (!picks || picks.length === 0) {
        picksEl.innerHTML = `
            <div class="empty-state" style="min-height:200px">
                <div class="empty-icon">🔍</div>
                <p>${summary?.message || 'No strong picks for this risk level. Try a different risk setting or increase your budget.'}</p>
            </div>`;
        return;
    }

    // Store picks data globally for detail panel access
    advisorPicksData = picks;

    picksEl.innerHTML = '<div class="advisor-picks-grid">' +
        picks.map((p, i) => renderPickCard(p, i)).join('') + '</div>';

    // Animate score bars after render
    requestAnimationFrame(() => {
        document.querySelectorAll('.score-bar-fill').forEach(bar => {
            const w = bar.dataset.width;
            if (w) bar.style.width = w + '%';
        });
        document.querySelectorAll('.combined-score-fill').forEach(bar => {
            const w = bar.dataset.width;
            if (w) bar.style.width = w + '%';
        });
    });
}

function renderPickCard(pick, index) {
    const signalClass = pick.signal.toLowerCase().replace(' ', '-');
    const scoreLevel = pick.combinedScore >= 60 ? 'high' : (pick.combinedScore >= 40 ? 'mid' : 'low');
    const changeClass = pick.changePct >= 0 ? 'up' : 'down';
    const changePrefix = pick.changePct >= 0 ? '+' : '';

    return `
        <div class="pick-card ${signalClass}" onclick="openPickDetail(${index})">
            <div class="pick-header">
                <div>
                    <div class="pick-symbol">${pick.symbol}</div>
                    <span class="pick-sector">${pick.sector}</span>
                </div>
                <span class="pick-signal ${signalClass}">${pick.signal}</span>
            </div>

            <div class="pick-price-row">
                <span class="pick-price">₹${formatNumber(pick.price)}</span>
                <span class="pick-change ${changeClass}">${changePrefix}${pick.changePct}%</span>
            </div>

            <div class="pick-combined-score">
                <div class="combined-score-value ${scoreLevel}">${pick.combinedScore}</div>
                <div style="flex:1">
                    <div class="combined-score-bar">
                        <div class="combined-score-fill ${scoreLevel}" data-width="${pick.combinedScore}" style="width:0%"></div>
                    </div>
                    <div class="combined-score-label">AI SCORE</div>
                </div>
            </div>

            <div class="pick-scores">
                <div class="score-bar-item">
                    <div class="score-bar-label">MARKET</div>
                    <div class="score-bar-track">
                        <div class="score-bar-fill market" data-width="${pick.marketScore}" style="width:0%"></div>
                    </div>
                    <div class="score-bar-value">${pick.marketScore}</div>
                </div>
                <div class="score-bar-item">
                    <div class="score-bar-label">NEWS</div>
                    <div class="score-bar-track">
                        <div class="score-bar-fill news" data-width="${pick.newsScore}" style="width:0%"></div>
                    </div>
                    <div class="score-bar-value">${pick.newsScore}</div>
                </div>
                <div class="score-bar-item">
                    <div class="score-bar-label">TECH</div>
                    <div class="score-bar-track">
                        <div class="score-bar-fill tech" data-width="${pick.techScore}" style="width:0%"></div>
                    </div>
                    <div class="score-bar-value">${pick.techScore}</div>
                </div>
            </div>

            <div class="pick-reasoning">${pick.reasoning}</div>

            <div class="pick-allocation">
                <div>
                    <div class="alloc-label">ALLOCATION</div>
                    <div class="alloc-value">₹${formatNumber(pick.allocation)}</div>
                    <div class="alloc-qty">${pick.qty} shares</div>
                </div>
                <button class="pick-add-trade-btn" onclick="event.stopPropagation(); addPickToPaperTrade('${pick.symbol}', ${pick.qty})">+ PAPER TRADE</button>
            </div>
        </div>
    `;
}

function addPickToPaperTrade(symbol, qty) {
    // Switch to Paper Trade tab and populate fields
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('nav-paper-trade').classList.add('active');
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-paper-trade').classList.add('active');

    document.getElementById('paper-symbol').value = symbol;
    document.getElementById('paper-qty').value = qty;
}

// ============================================================
// PICK DETAIL PANEL
// ============================================================
function openPickDetail(index) {
    const pick = advisorPicksData[index];
    if (!pick) return;

    const modal = document.getElementById('pick-detail-modal');
    const f = pick.fundamentals || {};
    const md = pick.marketDetail || {};
    const nd = pick.newsDetail || {};
    const td = pick.techDetail || {};

    // Header
    document.getElementById('pd-symbol').textContent = pick.symbol;
    document.getElementById('pd-company').textContent = f.companyName || pick.symbol;
    const signalBadge = document.getElementById('pd-signal');
    signalBadge.textContent = pick.signal;
    signalBadge.className = 'pd-signal-badge ' + pick.signal.toLowerCase().replace(' ', '-');

    // Price + Change
    document.getElementById('pd-price').textContent = '₹' + formatNumber(pick.price);
    const changeEl = document.getElementById('pd-change');
    const prefix = pick.changePct >= 0 ? '+' : '';
    changeEl.textContent = `${prefix}${pick.changePct}% (₹${(pick.changePct >= 0 ? '+' : '') + formatNumber(Math.abs(f.change || 0))})`;
    changeEl.className = 'pd-change ' + (pick.changePct >= 0 ? 'positive' : 'negative');

    // Score Ring
    const ring = document.getElementById('pd-score-ring');
    const ringColor = pick.combinedScore >= 60 ? '#00c896' : (pick.combinedScore >= 40 ? '#ffc107' : '#ff5252');
    ring.style.setProperty('--ring-pct', pick.combinedScore + '%');
    ring.style.setProperty('--ring-color', ringColor);
    document.getElementById('pd-score-num').textContent = pick.combinedScore;

    // Narrative
    document.getElementById('pd-narrative').textContent = pick.narrative || pick.reasoning;

    // Fundamentals
    const fundItems = [
        { label: 'Industry', value: f.industry || 'N/A' },
        { label: 'Sector', value: pick.sector },
        { label: 'Open', value: f.open ? '₹' + formatNumber(f.open) : '—' },
        { label: 'Previous Close', value: f.previousClose ? '₹' + formatNumber(f.previousClose) : '—' },
        { label: 'Day High', value: f.dayHigh ? '₹' + formatNumber(f.dayHigh) : '—' },
        { label: 'Day Low', value: f.dayLow ? '₹' + formatNumber(f.dayLow) : '—' },
        { label: '52W High', value: f.high52 ? '₹' + formatNumber(f.high52) : '—' },
        { label: '52W Low', value: f.low52 ? '₹' + formatNumber(f.low52) : '—' },
        { label: 'Upper Band', value: f.upperBand && f.upperBand !== '—' ? '₹' + f.upperBand : '—' },
        { label: 'Lower Band', value: f.lowerBand && f.lowerBand !== '—' ? '₹' + f.lowerBand : '—' },
    ];
    document.getElementById('pd-fundamentals').innerHTML = fundItems.map(item =>
        `<div class="pd-fund-item"><span class="pd-fund-label">${item.label}</span><span class="pd-fund-value">${item.value}</span></div>`
    ).join('');

    // Technical Analysis
    const pos52 = td.pos52wk || 50;
    const scoreBarColor = (val) => val >= 60 ? 'green' : (val >= 40 ? 'yellow' : 'red');
    document.getElementById('pd-tech').innerHTML = `
        <div class="pd-score-row">
            <span class="pd-score-row-label">Technical Score</span>
            <div class="pd-score-bar-track"><div class="pd-score-bar-fill ${scoreBarColor(pick.techScore)}" style="width:${pick.techScore}%"></div></div>
            <span class="pd-score-value">${pick.techScore}/100</span>
        </div>
        <div class="pd-detail-reason">${td.topReason || 'Within normal range'}</div>
        <div class="pd-52wk-bar">
            <div style="font-size:0.78rem; color:rgba(255,255,255,0.6); margin-bottom:4px;">52-Week Position</div>
            <div class="pd-52wk-bar-track">
                <div class="pd-52wk-marker" style="left:${Math.min(100, Math.max(0, pos52))}%"></div>
            </div>
            <div class="pd-52wk-labels">
                <span>₹${f.low52 ? formatNumber(f.low52) : '—'}</span>
                <span>Current: ${pos52.toFixed(0)}%</span>
                <span>₹${f.high52 ? formatNumber(f.high52) : '—'}</span>
            </div>
        </div>
    `;

    // Market Sentiment
    const pcr = md.pcrOI || 0;
    document.getElementById('pd-market').innerHTML = `
        <div class="pd-score-row">
            <span class="pd-score-row-label">Market Score</span>
            <div class="pd-score-bar-track"><div class="pd-score-bar-fill ${scoreBarColor(pick.marketScore)}" style="width:${pick.marketScore}%"></div></div>
            <span class="pd-score-value">${pick.marketScore}/100</span>
        </div>
        <div class="pd-detail-reason">${md.topReason || 'No options data'}</div>
        ${pcr > 0 ? `
        <div class="pd-fundamentals-grid" style="margin-top:14px">
            <div class="pd-fund-item"><span class="pd-fund-label">Put-Call Ratio (OI)</span><span class="pd-fund-value">${pcr.toFixed(2)}</span></div>
            <div class="pd-fund-item"><span class="pd-fund-label">Avg CE IV</span><span class="pd-fund-value">${(md.avgCeIV || 0).toFixed(1)}%</span></div>
            <div class="pd-fund-item"><span class="pd-fund-label">Avg PE IV</span><span class="pd-fund-value">${(md.avgPeIV || 0).toFixed(1)}%</span></div>
            <div class="pd-fund-item"><span class="pd-fund-label">CE OI Change</span><span class="pd-fund-value">${formatNumber(md.ceOIChange || 0)}</span></div>
        </div>
        ` : '<div style="font-size:0.82rem; color:rgba(255,255,255,0.5); margin-top:8px;">No options chain data available for this stock.</div>'}
    `;

    // News Sentiment Bar
    const bull = nd.bullish || 0;
    const bear = nd.bearish || 0;
    const neut = nd.neutral || 0;
    const newsTotal = bull + bear + neut;
    const sentEl = document.getElementById('pd-news-sentiment');
    if (newsTotal > 0) {
        const bullPct = (bull / newsTotal * 100).toFixed(0);
        const bearPct = (bear / newsTotal * 100).toFixed(0);
        const neutPct = (neut / newsTotal * 100).toFixed(0);
        sentEl.innerHTML = `
            <span class="pd-sent-count" style="color:#00c896">${bull} 🐂</span>
            <div class="pd-sent-bar">
                <div class="pd-sent-bull" style="width:${bullPct}%"></div>
                <div class="pd-sent-neutral" style="width:${neutPct}%"></div>
                <div class="pd-sent-bear" style="width:${bearPct}%"></div>
            </div>
            <span class="pd-sent-count" style="color:#ff5252">${bear} 🐻</span>
        `;
    } else {
        sentEl.innerHTML = '<span style="font-size:0.82rem; color:rgba(255,255,255,0.5)">No recent articles analyzed</span>';
    }

    // News Articles
    const articles = pick.newsArticles || [];
    const newsListEl = document.getElementById('pd-news-list');
    if (articles.length > 0) {
        newsListEl.innerHTML = articles.map(a => {
            const tags = (a.tags || []).map(t =>
                `<span class="pd-news-tag ${t}">${t}</span>`
            ).join('');
            return `
                <a href="${a.link}" target="_blank" rel="noopener" class="pd-news-article">
                    <div class="pd-news-title">${a.title}</div>
                    <div class="pd-news-meta">
                        <span class="pd-news-source">${a.source}</span>
                        <span>•</span>
                        <span>${a.timeAgo}</span>
                    </div>
                    ${tags ? '<div class="pd-news-tags">' + tags + '</div>' : ''}
                </a>
            `;
        }).join('');
    } else {
        newsListEl.innerHTML = '<div style="font-size:0.82rem; color:rgba(255,255,255,0.5)">No news articles available.</div>';
    }

    // Allocation
    document.getElementById('pd-alloc').innerHTML = `
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">₹${formatNumber(pick.allocation)}</span>
            <span class="pd-alloc-label">Amount Allocated</span>
        </div>
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">${pick.qty}</span>
            <span class="pd-alloc-label">Shares to Buy</span>
        </div>
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">₹${formatNumber(pick.price)}</span>
            <span class="pd-alloc-label">Price Per Share</span>
        </div>
        <div class="pd-alloc-item">
            <span class="pd-alloc-value">${((pick.allocation / (parseInt(document.getElementById('advisor-budget').value) || 100000)) * 100).toFixed(1)}%</span>
            <span class="pd-alloc-label">Of Total Budget</span>
        </div>
    `;

    // Show modal
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closePickDetail() {
    const modal = document.getElementById('pick-detail-modal');
    modal.classList.remove('active');
    document.body.style.overflow = '';
}

// Close button + overlay click + Escape key
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('pd-close-btn')?.addEventListener('click', closePickDetail);
    document.getElementById('pick-detail-modal')?.addEventListener('click', (e) => {
        if (e.target === document.getElementById('pick-detail-modal')) closePickDetail();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closePickDetail();
    });
});

// Expose to global scope for inline onclick handlers (module script)
window.openPickDetail = openPickDetail;
window.closePickDetail = closePickDetail;
window.addPickToPaperTrade = addPickToPaperTrade;

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================
let toastIdCounter = 0;

function showToast(type, title, msg, duration = 8000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const id = ++toastIdCounter;
    const icons = {
        sell: '🔴',
        hold: '🟢',
        'take-profit': '🟡',
        info: 'ℹ️',
    };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.id = `toast-${id}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || '📢'}</span>
        <div class="toast-body">
            <div class="toast-title">${title}</div>
            <div class="toast-msg">${msg}</div>
        </div>
        <button class="toast-close" onclick="dismissToast(${id})">✕</button>
    `;

    // Play notification sound (subtle beep via AudioContext)
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = type === 'sell' ? 440 : 660;
        gain.gain.value = 0.08;
        osc.start();
        osc.stop(ctx.currentTime + 0.15);
    } catch (e) { /* silent */ }

    container.appendChild(toast);

    // Auto-dismiss
    if (duration > 0) {
        setTimeout(() => dismissToast(id), duration);
    }
}

function dismissToast(id) {
    const toast = document.getElementById(`toast-${id}`);
    if (!toast) return;
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
}

window.dismissToast = dismissToast;

// ============================================================
// PICK MONITORING — REAL-TIME UPDATES
// ============================================================
let pickMonitorTimer = null;
let monitoredPicks = [];   // { symbol, entryPrice, entryScore }
let lastSignals = {};      // Track signals to avoid duplicate toasts
const MONITOR_INTERVAL = 30000; // 30 seconds

function startPickMonitoring() {
    if (pickMonitorTimer) stopPickMonitoring();

    // Build monitored picks from the generated picks
    monitoredPicks = advisorPicksData.map(p => ({
        symbol: p.symbol,
        entryPrice: p.price,
        entryScore: p.combinedScore,
    }));
    lastSignals = {};

    if (monitoredPicks.length === 0) return;

    // Update status indicator
    updateMonitoringStatus(true);

    // Initial fetch
    fetchPickMonitorData();

    // Start polling
    pickMonitorTimer = setInterval(fetchPickMonitorData, MONITOR_INTERVAL);

    showToast('info', 'MONITORING ACTIVE',
        `Tracking ${monitoredPicks.length} picks — updates every 30s`, 5000);
}

function stopPickMonitoring() {
    if (pickMonitorTimer) {
        clearInterval(pickMonitorTimer);
        pickMonitorTimer = null;
    }
    monitoredPicks = [];
    lastSignals = {};
    updateMonitoringStatus(false);
}

function updateMonitoringStatus(active) {
    const statusEl = document.getElementById('monitoring-status');
    const textEl = document.getElementById('monitoring-status-text');
    if (!statusEl || !textEl) return;

    if (active) {
        statusEl.className = 'monitoring-status active';
        textEl.textContent = `MONITORING ${monitoredPicks.length} PICKS`;
    } else {
        statusEl.className = 'monitoring-status inactive';
        textEl.textContent = 'NOT MONITORING';
    }
}

async function fetchPickMonitorData() {
    if (monitoredPicks.length === 0) return;

    const data = await fetchAPI('/advisor/monitor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ picks: monitoredPicks }),
    });

    if (!data || !data.picks) return;

    data.picks.forEach(result => {
        updatePickCardLive(result);
        checkAndNotify(result);
    });
}

function updatePickCardLive(result) {
    // Find the pick card by symbol
    const pickIndex = advisorPicksData.findIndex(p => p.symbol === result.symbol);
    if (pickIndex === -1) return;

    const card = document.querySelectorAll('.pick-card')[pickIndex];
    if (!card) return;

    // Remove previous alert classes
    card.classList.remove('sell-alert', 'profit-alert');
    card.classList.add('monitoring');

    // Add alert class
    if (result.signal === 'SELL') {
        card.classList.add('sell-alert');
    } else if (result.signal === 'TAKE PROFIT') {
        card.classList.add('profit-alert');
    }

    // Add or update the live strip at the top of the card
    let liveStrip = card.querySelector('.pick-live-strip');
    if (!liveStrip) {
        liveStrip = document.createElement('div');
        liveStrip.className = 'pick-live-strip';
        card.insertBefore(liveStrip, card.firstChild);
    }

    const priceClass = result.pnl >= 0 ? 'up' : 'down';
    const pnlClass = result.pnl >= 0 ? 'positive' : 'negative';
    const pnlPrefix = result.pnlPct >= 0 ? '+' : '';

    let signalBadgeClass = 'hold-signal';
    let signalText = '✓ HOLD';
    if (result.signal === 'SELL') {
        signalBadgeClass = 'sell-signal';
        signalText = '⚠ SELL';
    } else if (result.signal === 'TAKE PROFIT') {
        signalBadgeClass = 'take-profit-signal';
        signalText = '💰 TAKE PROFIT';
    }

    liveStrip.innerHTML = `
        <span class="pick-live-price ${priceClass}">₹${formatNumber(result.currentPrice)}</span>
        <span class="pick-live-pnl ${pnlClass}">${pnlPrefix}${result.pnlPct}%</span>
        <span class="pick-signal-live ${signalBadgeClass}">${signalText}</span>
    `;

    // Update the price displayed in the card body too
    const priceEl = card.querySelector('.pick-price');
    if (priceEl) {
        priceEl.textContent = `₹${formatNumber(result.currentPrice)}`;
    }

    const changeEl = card.querySelector('.pick-change');
    if (changeEl) {
        changeEl.textContent = `${pnlPrefix}${result.pnlPct}%`;
        changeEl.className = `pick-change ${priceClass}`;
    }
}

function checkAndNotify(result) {
    const prevSignal = lastSignals[result.symbol];
    const currentSignal = result.signal;

    // Only notify on signal change (or first time seeing a non-HOLD)
    if (currentSignal === prevSignal) return;
    lastSignals[result.symbol] = currentSignal;

    if (currentSignal === 'SELL') {
        showToast('sell',
            `SELL ▸ ${result.symbol}`,
            result.signalReason,
            12000);
    } else if (currentSignal === 'TAKE PROFIT') {
        showToast('take-profit',
            `TAKE PROFIT ▸ ${result.symbol}`,
            result.signalReason,
            10000);
    }
    // Don't toast for HOLD (too noisy)
}

// Wire monitoring lifecycle into tab switches
function hookMonitoringToTabs() {
    const tabBtns = document.querySelectorAll('.nav-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // If leaving advisor tab, we keep the monitoring running
            // (user may want notifications even on other tabs)
        });
    });
}

// Start monitoring automatically after picks are generated
// (hooked into loadAdvisorPicks)
const _originalLoadAdvisorPicks = loadAdvisorPicks;

// Override loadAdvisorPicks to start monitoring after picks load
loadAdvisorPicks = async function (budget, riskLevel) {
    // Stop any previous monitoring
    stopPickMonitoring();

    // Call original
    await _originalLoadAdvisorPicks(budget, riskLevel);

    // Start monitoring if picks were generated
    if (advisorPicksData && advisorPicksData.length > 0) {
        // Small delay to let DOM settle
        setTimeout(() => startPickMonitoring(), 500);
    }
};

// Initialize monitoring hooks
document.addEventListener('DOMContentLoaded', () => {
    hookMonitoringToTabs();
});

// ============================================================
// AUTONOMOUS TRADER MODULE
// ============================================================

let autoPollingInterval = null;
let autoPreviousTradeCount = 0;

// Initialization — check bot status on load and when tab switches
document.addEventListener('DOMContentLoaded', () => {
    // Check auto trader status on page load
    setTimeout(checkAutoTraderStatus, 1500);

    // Presets
    document.querySelectorAll('.auto-preset').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('auto-invest-amount').value = btn.dataset.amount;
        });
    });

    // Deploy button
    document.getElementById('auto-deploy-btn')?.addEventListener('click', deployAutoTrader);

    // Halt button
    document.getElementById('auto-halt-btn')?.addEventListener('click', haltAutoTrader);

    // Reset button
    document.getElementById('auto-reset-btn')?.addEventListener('click', resetAutoTrader);
});

async function checkAutoTraderStatus() {
    const data = await fetchAPI('/auto/status');
    if (!data) return;

    if (data.running || data.initialCapital > 0) {
        // Bot is running or has capital — show dashboard
        showAutoDashboard();
        renderAutoStatus(data);
        if (data.running) {
            startAutoPolling();
        }
    }
}

async function deployAutoTrader() {
    const input = document.getElementById('auto-invest-amount');
    const amount = parseFloat(input.value);

    if (!amount || amount < 10000) {
        alert('Minimum investment is ₹10,000');
        return;
    }

    const btn = document.getElementById('auto-deploy-btn');
    btn.textContent = 'DEPLOYING...';
    btn.disabled = true;

    const result = await fetchAPI('/auto/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount }),
    });

    btn.innerHTML = '<span class="deploy-pulse"></span>DEPLOY CAPITAL';
    btn.disabled = false;

    if (!result || result.error) {
        alert(result?.error || 'Failed to start bot');
        return;
    }

    // Switch to dashboard
    showAutoDashboard();
    startAutoPolling();
}

async function haltAutoTrader() {
    if (!confirm('Stop the autonomous trader? Open positions will remain.')) return;

    const btn = document.getElementById('auto-halt-btn');
    btn.textContent = 'STOPPING...';
    btn.disabled = true;

    const result = await fetchAPI('/auto/stop', { method: 'POST' });

    btn.textContent = '⏹ HALT TRADING';
    btn.disabled = false;

    if (result?.success) {
        stopAutoPolling();
        // Refresh status
        const data = await fetchAPI('/auto/status');
        if (data) renderAutoStatus(data);
    }
}

async function resetAutoTrader() {
    if (!confirm('RESET the autonomous trader? This will delete ALL positions and trade history!')) return;

    await fetchAPI('/auto/reset', { method: 'POST' });
    stopAutoPolling();
    showAutoSetup();
}

function showAutoDashboard() {
    const setup = document.getElementById('auto-setup');
    const dash = document.getElementById('auto-dashboard');
    if (setup) setup.style.display = 'none';
    if (dash) dash.style.display = 'block';
}

function showAutoSetup() {
    const setup = document.getElementById('auto-setup');
    const dash = document.getElementById('auto-dashboard');
    if (setup) setup.style.display = '';
    if (dash) dash.style.display = 'none';
}

function startAutoPolling() {
    stopAutoPolling();
    autoPreviousTradeCount = 0;
    autoPollingInterval = setInterval(pollAutoTrader, 5000);
    // Immediate first poll
    pollAutoTrader();
}

function stopAutoPolling() {
    if (autoPollingInterval) {
        clearInterval(autoPollingInterval);
        autoPollingInterval = null;
    }
}

async function pollAutoTrader() {
    const data = await fetchAPI('/auto/status');
    if (!data) return;
    renderAutoStatus(data);
}

function renderAutoStatus(data) {
    // -- P&L --
    const pnlEl = document.getElementById('auto-total-pnl');
    const pnlVal = data.overallPnl || 0;
    pnlEl.textContent = `₹${formatNumberSigned(pnlVal)}`;
    pnlEl.className = 'auto-stat-value ' + (pnlVal >= 0 ? 'green' : 'red');

    const pnlPctEl = document.getElementById('auto-pnl-pct');
    pnlPctEl.textContent = `${pnlVal >= 0 ? '+' : ''}${data.overallPnlPct || 0}%`;

    // -- Portfolio value --
    document.getElementById('auto-portfolio-value').textContent = `₹${formatNumber(data.totalValue || 0)}`;
    document.getElementById('auto-cash-left').textContent = `Cash: ₹${formatNumber(data.cash || 0)}`;

    // -- Trades --
    document.getElementById('auto-trade-count').textContent = data.tradeCountToday || 0;
    const dailyPnl = data.dailyPnl || 0;
    const dailyEl = document.getElementById('auto-daily-pnl');
    dailyEl.textContent = `Daily: ₹${formatNumberSigned(dailyPnl)}`;
    dailyEl.style.color = dailyPnl >= 0 ? 'var(--green)' : 'var(--red)';

    // -- Win Rate --
    document.getElementById('auto-win-rate').textContent = `${data.winRate || 0}%`;
    document.getElementById('auto-wl-count').textContent = `W: ${data.winningTrades || 0} / L: ${data.losingTrades || 0}`;

    // -- Status --
    const dot = document.getElementById('auto-status-dot');
    const statusText = document.getElementById('auto-status-text');
    const statusMsg = document.getElementById('auto-status-msg');

    if (data.running) {
        dot.className = 'auto-status-dot running';
        statusText.textContent = 'ACTIVE';
        statusText.style.color = 'var(--green)';
    } else {
        dot.className = 'auto-status-dot stopped';
        statusText.textContent = 'STOPPED';
        statusText.style.color = 'var(--red)';
    }
    statusMsg.textContent = data.statusMessage || '—';

    // -- Badges --
    document.getElementById('auto-scores-badge').textContent = `${data.scoresLoaded || 0} stocks scanned`;
    const marketBadge = document.getElementById('auto-market-badge');
    if (data.marketOpen) {
        marketBadge.textContent = 'MARKET OPEN';
        marketBadge.className = 'auto-market-badge open';
    } else {
        marketBadge.textContent = 'MARKET CLOSED';
        marketBadge.className = 'auto-market-badge';
    }

    // -- Positions --
    renderAutoPositions(data.positions || []);

    // -- Trade Feed --
    renderAutoFeed(data);

    // -- Strategy Stats --
    renderAutoStrategies(data.strategyStats || {});

    // -- Sectors --
    renderAutoSectors(data.sectors || {}, data.totalValue || 1);

    // -- Best/Worst --
    const bestEl = document.getElementById('auto-best-trade');
    if (data.bestTrade) {
        bestEl.textContent = `${data.bestTrade.symbol} ₹${formatNumberSigned(data.bestTrade.pnl)}`;
        bestEl.className = 'auto-hl-value green';
    }
    const worstEl = document.getElementById('auto-worst-trade');
    if (data.worstTrade) {
        worstEl.textContent = `${data.worstTrade.symbol} ₹${formatNumberSigned(data.worstTrade.pnl)}`;
        worstEl.className = 'auto-hl-value red';
    }

    // -- Position count --
    document.getElementById('auto-pos-count').textContent = data.positionCount || 0;

    // -- Update halt button state --
    const haltBtn = document.getElementById('auto-halt-btn');
    if (data.running) {
        haltBtn.textContent = '⏹ HALT TRADING';
        haltBtn.disabled = false;
    } else {
        haltBtn.textContent = '▶ RESUME TRADING';
        haltBtn.disabled = false;
        // Re-wire button to restart
        haltBtn.onclick = async () => {
            const result = await fetchAPI('/auto/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: 0 }), // 0 = resume, no new capital
            });
            if (result?.success) {
                startAutoPolling();
            } else if (result?.error) {
                // If error (e.g. min investment), just inform
                alert(result.error);
            }
        };
    }
}

function renderAutoPositions(positions) {
    const container = document.getElementById('auto-positions-list');
    if (!positions || positions.length === 0) {
        container.innerHTML = '<div class="auto-empty">No positions yet — bot will start trading when market opens</div>';
        return;
    }

    container.innerHTML = positions.map(p => {
        const pnlClass = p.pnl >= 0 ? 'green' : 'red';
        const pnlPrefix = p.pnl >= 0 ? '+' : '';
        return `
            <div class="auto-pos-item">
                <div class="auto-pos-symbol">${p.symbol}</div>
                <div class="auto-pos-qty">${p.qty} × ₹${formatNumber(p.avgPrice)}</div>
                <div class="auto-pos-price">₹${formatNumber(p.currentPrice)} (${p.pnlPct >= 0 ? '+' : ''}${p.pnlPct}%)</div>
                <div class="auto-pos-pnl ${pnlClass}">${pnlPrefix}₹${formatNumber(Math.abs(p.pnl))}</div>
                <div class="auto-pos-strategy">${formatStrategy(p.strategy)}</div>
            </div>`;
    }).join('');
}

async function renderAutoFeed(statusData) {
    // Use trades from the last API call — check if we have new ones
    const trades = await fetchAPI('/auto/trades?limit=30');
    if (!trades?.trades) return;

    const container = document.getElementById('auto-feed-list');
    if (trades.trades.length === 0) {
        container.innerHTML = '<div class="auto-empty">Waiting for trades...</div>';
        return;
    }

    container.innerHTML = trades.trades.map(t => {
        const isBuy = t.type === 'BUY';
        const time = new Date(t.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

        let pnlHtml = '';
        if (!isBuy && t.pnl !== undefined) {
            const pnlClass = t.pnl >= 0 ? 'green' : 'red';
            pnlHtml = `<span class="auto-feed-pnl ${pnlClass}">₹${formatNumberSigned(t.pnl)}</span>`;
        }

        return `
            <div class="auto-feed-item">
                <span class="auto-feed-type ${isBuy ? 'buy' : 'sell'}">${t.type}</span>
                <span class="auto-feed-info">
                    <span class="auto-feed-symbol">${t.symbol}</span>
                    ${t.qty}× ₹${formatNumber(t.price)}
                    <br><span style="color:var(--accent-purple); font-size:0.6rem">${formatStrategy(t.strategy)}</span>
                </span>
                ${pnlHtml}
                <span class="auto-feed-time">${time}</span>
            </div>`;
    }).join('');
}

function renderAutoStrategies(stats) {
    const container = document.getElementById('auto-strats-list');
    const entries = Object.entries(stats);
    if (entries.length === 0) {
        container.innerHTML = '<div class="auto-empty">No strategy data yet</div>';
        return;
    }

    container.innerHTML = entries.map(([name, data]) => {
        const pnlClass = data.pnl >= 0 ? 'green' : 'red';
        return `
            <div class="auto-strat-row">
                <span class="auto-strat-name">${formatStrategy(name)}</span>
                <span class="auto-strat-count">${data.count} trades</span>
                <span class="auto-strat-pnl ${pnlClass}">₹${formatNumberSigned(data.pnl)}</span>
            </div>`;
    }).join('');
}

function renderAutoSectors(sectors, totalValue) {
    const container = document.getElementById('auto-sectors-list');
    const entries = Object.entries(sectors).sort((a, b) => b[1].value - a[1].value);

    if (entries.length === 0) {
        container.innerHTML = '<div class="auto-empty">No allocations yet</div>';
        return;
    }

    container.innerHTML = entries.map(([name, data]) => {
        const pct = totalValue > 0 ? (data.value / totalValue * 100) : 0;
        const pnlClass = data.pnl >= 0 ? 'green' : 'red';
        return `
            <div class="auto-sector-row">
                <span class="auto-sector-name">${name}</span>
                <div class="auto-sector-bar-wrap">
                    <div class="auto-sector-bar" style="width:${Math.min(100, pct)}%"></div>
                </div>
                <span class="auto-sector-pct">${pct.toFixed(1)}%</span>
                <span class="auto-sector-pnl ${pnlClass}">₹${formatNumberSigned(data.pnl)}</span>
            </div>`;
    }).join('');
}

function formatStrategy(strategy) {
    if (!strategy) return '—';
    return strategy.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatNumberSigned(num) {
    if (num === null || num === undefined) return '0';
    const prefix = num >= 0 ? '+' : '';
    return prefix + formatNumber(Math.abs(num));
}

// Auto-poll when switching to auto-trader tab
const _origNavHandler = document.querySelectorAll('.nav-btn');
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'auto-trader') {
                checkAutoTraderStatus();
            } else if (btn.dataset.tab === 'crypto-trader') {
                checkCryptoTraderStatus();
            }
        });
    });
});

// ============================================================
// CRYPTO TRADER MODULE
// ============================================================

let cryptoPollingInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(checkCryptoTraderStatus, 2000);
    document.getElementById('crypto-deploy-btn')?.addEventListener('click', deployCryptoTrader);
    document.getElementById('crypto-halt-btn')?.addEventListener('click', haltCryptoTrader);
    document.getElementById('crypto-reset-btn')?.addEventListener('click', resetCryptoTrader);
    document.getElementById('crypto-export-btn')?.addEventListener('click', () => {
        window.location.href = '/api/crypto/export';
    });
});

async function checkCryptoTraderStatus() {
    const data = await fetchAPI('/crypto/status');
    if (!data) return;
    
    if (data.running || data.initial > 0) {
        showCryptoDashboard();
        renderCryptoStatus(data);
        if (data.running) {
            startCryptoPolling();
        }
    }
}

async function deployCryptoTrader() {
    const btn = document.getElementById('crypto-deploy-btn');
    btn.textContent = 'DEPLOYING CRYPTO AI...';
    btn.disabled = true;

    const result = await fetchAPI('/crypto/start', { method: 'POST' });
    btn.innerHTML = '<span class="deploy-pulse"></span>DEPLOY ALGORITHM';
    btn.disabled = false;

    if (!result || result.error) {
        alert(result?.error || 'Failed to start Crypto bot');
        return;
    }

    showCryptoDashboard();
    startCryptoPolling();
}

async function haltCryptoTrader() {
    if (!confirm('Stop the Crypto trader? Open positions remain.')) return;

    const btn = document.getElementById('crypto-halt-btn');
    btn.textContent = 'STOPPING...';
    btn.disabled = true;

    const result = await fetchAPI('/crypto/stop', { method: 'POST' });
    btn.textContent = '⏹ HALT TRADING';
    btn.disabled = false;

    if (result?.success) {
        stopCryptoPolling();
        const data = await fetchAPI('/crypto/status');
        if (data) renderCryptoStatus(data);
    }
}

async function resetCryptoTrader() {
    if (!confirm('RESET Crypto trader? Deletes ALL history!')) return;

    await fetchAPI('/crypto/reset', { method: 'POST' });
    stopCryptoPolling();
    const setup = document.getElementById('crypto-setup');
    const dash = document.getElementById('crypto-dashboard');
    if (setup) setup.style.display = 'block';
    if (dash) dash.style.display = 'none';
}

function showCryptoDashboard() {
    const setup = document.getElementById('crypto-setup');
    const dash = document.getElementById('crypto-dashboard');
    if (setup) setup.style.display = 'none';
    if (dash) dash.style.display = 'block';
}

function startCryptoPolling() {
    if (cryptoPollingInterval) return;
    fetchCryptoStatusLoop();
    cryptoPollingInterval = setInterval(fetchCryptoStatusLoop, 5000);
}

function stopCryptoPolling() {
    if (cryptoPollingInterval) {
        clearInterval(cryptoPollingInterval);
        cryptoPollingInterval = null;
    }
}

async function fetchCryptoStatusLoop() {
    const data = await fetchAPI('/crypto/status');
    if (data) renderCryptoStatus(data);
    renderCryptoFeed();
}

function renderCryptoStatus(statusData) {
    document.getElementById('crypto-total-pnl').textContent = '$' + formatNumber(statusData.total_pnl);
    const pnlEl = document.getElementById('crypto-pnl-pct');
    pnlEl.textContent = statusData.pnl_pct.toFixed(2) + '%';
    pnlEl.className = 'auto-stat-sub ' + (statusData.total_pnl >= 0 ? 'green' : 'red');

    document.getElementById('crypto-portfolio-value').textContent = '$' + formatNumber(statusData.total_value);
    document.getElementById('crypto-cash-left').textContent = 'Cash: $' + formatNumber(statusData.cash);
    document.getElementById('crypto-trade-count').textContent = statusData.trade_count_today + ' / 150+';

    const dot = document.getElementById('crypto-status-dot');
    const txt = document.getElementById('crypto-status-text');
    const msg = document.getElementById('crypto-status-msg');

    if (statusData.running) {
        dot.className = 'auto-status-dot active';
        txt.textContent = 'ONLINE (24/7)';
        txt.style.color = '#00e676';
    } else {
        dot.className = 'auto-status-dot';
        txt.textContent = 'OFFLINE';
        txt.style.color = 'rgba(255,255,255,0.5)';
    }
    msg.textContent = statusData.status_message || '—';

    // Positions
    const posList = document.getElementById('crypto-positions-list');
    const posEntries = Object.entries(statusData.positions || {});
        
    if (posEntries.length === 0) {
        posList.innerHTML = '<div class="auto-empty">No active crypto positions</div>';
    } else {
        posList.innerHTML = posEntries.map(([sym, pos]) => {
            const val = pos.qty * pos.avgPrice;
            return `
                <div class="auto-pos-item">
                    <div style="flex:1">
                        <span class="auto-pos-symbol">${sym}</span>
                        <div class="auto-pos-meta">${formatNumber(pos.qty)} × $${formatNumber(pos.avgPrice)}</div>
                    </div>
                    <div style="text-align:right">
                        <div class="auto-pos-val">$${formatNumber(val)}</div>
                    </div>
                </div>`;
        }).join('');
    }
}

async function renderCryptoFeed() {
    const trades = await fetchAPI('/crypto/trades?limit=30');
    if (!trades?.trades) return;

    const container = document.getElementById('crypto-feed-list');
    if (trades.trades.length === 0) {
        container.innerHTML = '<div class="auto-empty">Waiting for crypto trades...</div>';
        return;
    }

    container.innerHTML = trades.trades.reverse().map(t => {
        const isBuy = t.type === 'BUY';
        const time = new Date(t.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        
        let pnlHtml = '';
        if (!isBuy && t.pnl !== undefined) {
            const pnlClass = t.pnl >= 0 ? 'green' : 'red';
            pnlHtml = `<span class="auto-feed-pnl ${pnlClass}">$${formatNumberSigned(t.pnl)}</span>`;
        }

        const tagText = t.tag === 'arbitrage' ? '⚡ ARBTG' : t.strategy;

        return `
            <div class="auto-feed-item">
                <span class="auto-feed-type ${isBuy ? 'buy' : 'sell'}" style="background: ${isBuy ? 'rgba(0,200,150,0.1)' : 'rgba(255,80,80,0.1)'};">${t.type}</span>
                <span class="auto-feed-info">
                    <span class="auto-feed-symbol">${t.symbol}</span>
                    ${formatNumber(t.qty)}× $${formatNumber(t.price)}
                    <br><span style="color:#f7931a; font-size:0.6rem">${tagText}</span>
                    <br><span style="color:rgba(255,255,255,0.4); font-size:0.55rem">${t.reason}</span>
                </span>
                ${pnlHtml}
                <span class="auto-feed-time">${time}</span>
            </div>`;
    }).join('');
}

