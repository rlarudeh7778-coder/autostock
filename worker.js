// 통합 프록시 (Cloudflare Worker) — 주식 시세 + 종목 검색 + 코인 우회
// 배포: dash.cloudflare.com → Workers & Pages → 기존 Worker 열기 → Edit Code → 전체 교체 → Deploy

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Content-Type': 'application/json',
  'Cache-Control': 'public, max-age=300'
};

export default {
  async fetch(req) {
    const url = new URL(req.url);
    const p = url.pathname;

    // 1) 주식 일봉: /chart/005930.KS?range=1y
    let m = p.match(/^\/chart\/([A-Za-z0-9.\-]{1,20})$/);
    if (m) {
      const range = /^[0-9]+(d|mo|y)$/.test(url.searchParams.get('range')||'') ? url.searchParams.get('range') : '1y';
      const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${m[1]}?range=${range}&interval=1d`,
        { headers: { 'User-Agent': 'Mozilla/5.0' }, cf: { cacheTtl: 600, cacheEverything: true } });
      return new Response(await r.text(), { status: r.status, headers: CORS });
    }

    // 2) 종목 이름 검색 (네이버 자동완성): /search?q=한진칼
    if (p === '/search') {
      const q = (url.searchParams.get('q')||'').slice(0, 30);
      if (!q) return new Response('[]', { headers: CORS });
      try {
        const r = await fetch('https://ac.stock.naver.com/ac?q=' + encodeURIComponent(q) + '&target=stock,ipo',
          { headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com' }, cf: { cacheTtl: 3600, cacheEverything: true } });
        const j = await r.json();
        // 응답에서 6자리 코드 + 이름만 추출 (형태 방어적으로 처리)
        const out = [];
        const walk = o => {
          if (Array.isArray(o)) { o.forEach(walk); return; }
          if (o && typeof o === 'object') {
            const code = o.code || o.cd || o.itemCode;
            const name = o.name || o.nm || o.itemName;
            if (code && name && /^[0-9]{6}$/.test(String(code))) out.push({ code: String(code), name: String(name) });
            else Object.values(o).forEach(walk);
          }
        };
        walk(j);
        const seen = new Set();
        return new Response(JSON.stringify(out.filter(x => !seen.has(x.code) && seen.add(x.code)).slice(0, 8)), { headers: CORS });
      } catch (e) {
        return new Response('[]', { headers: CORS });
      }
    }

    // 3.5) 네이버 재무지표 우회: /fin/005930  → PER/PBR/ROE/배당 등 (실패해도 앱은 수동입력으로 폴백)
    let f = p.match(/^\/fin\/([0-9]{6})$/);
    if (f) {
      const code = f[1];
      const tries = [
        'https://m.stock.naver.com/api/stock/' + code + '/integration',
        'https://m.stock.naver.com/api/stock/' + code + '/basic'
      ];
      for (const u of tries) {
        try {
          const r = await fetch(u, {
            headers: {
              'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
              'Referer': 'https://m.stock.naver.com/',
              'Accept': 'application/json'
            },
            cf: { cacheTtl: 3600, cacheEverything: true }
          });
          if (!r.ok) continue;
          const j = await r.json();
          // 지표 추출 (네이버 응답 구조가 자주 바뀌므로 방어적으로 탐색)
          const out = {};
          const pick = (obj, keys) => {
            for (const k of keys) {
              if (obj && obj[k] != null && obj[k] !== '') { const n = parseFloat(String(obj[k]).replace(/,/g,'')); if (isFinite(n)) return n; }
            }
            return null;
          };
          const scan = o => {
            if (!o || typeof o !== 'object') return;
            if (out.per == null)  out.per  = pick(o, ['per','PER']);
            if (out.pbr == null)  out.pbr  = pick(o, ['pbr','PBR']);
            if (out.roe == null)  out.roe  = pick(o, ['roe','ROE']);
            if (out.eps == null)  out.eps  = pick(o, ['eps','EPS']);
            if (out.div == null)  out.div  = pick(o, ['dividendRatio','dvr','dividendYield']);
            if (out.name == null && o.stockName) out.name = o.stockName;
            for (const v of Object.values(o)) if (v && typeof v === 'object') scan(v);
          };
          scan(j);
          if (out.per != null || out.pbr != null) {
            return new Response(JSON.stringify(out), { headers: CORS });
          }
        } catch (e) {}
      }
      return new Response(JSON.stringify({ error: 'no-fin' }), { headers: CORS });
    }

    // 3) 업비트 코인 우회: /upbit/candles/days?market=KRW-BTC&count=200&to=...
    if (p === '/upbit/candles/days') {
      const market = url.searchParams.get('market')||'';
      if (!/^KRW-[A-Z0-9]{2,10}$/.test(market)) return new Response('[]', { headers: CORS });
      const count = Math.min(200, parseInt(url.searchParams.get('count')||'200'));
      const to = url.searchParams.get('to')||'';
      const target = `https://api.upbit.com/v1/candles/days?market=${market}&count=${count}${to?'&to='+encodeURIComponent(to):''}`;
      const r = await fetch(target, { headers: { 'Accept': 'application/json' }, cf: { cacheTtl: 120, cacheEverything: true } });
      return new Response(await r.text(), { status: r.status, headers: CORS });
    }

    return new Response(JSON.stringify({ error: 'not found' }), { status: 404, headers: CORS });
  }
};
