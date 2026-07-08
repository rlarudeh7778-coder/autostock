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
