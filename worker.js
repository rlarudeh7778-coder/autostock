// 주식 시세 프록시 (Cloudflare Worker)
// 배포: dash.cloudflare.com → Workers & Pages → Create Worker → 이 코드 붙여넣기 → Deploy
// 배포 후 나오는 URL(https://xxx.workers.dev)을 split.html 맨 위 WORKER_URL에 넣으세요.

export default {
  async fetch(req) {
    const url = new URL(req.url);
    // 허용 경로: /chart/티커  (예: /chart/005930.KS?range=1y&interval=1d)
    const m = url.pathname.match(/^\/chart\/([A-Za-z0-9.\-]{1,20})$/);
    if (!m) {
      return new Response(JSON.stringify({ error: 'not found' }), {
        status: 404,
        headers: { 'Access-Control-Allow-Origin': '*' }
      });
    }
    const range = /^[0-9]+(d|mo|y)$/.test(url.searchParams.get('range') || '') ? url.searchParams.get('range') : '1y';
    const target = `https://query1.finance.yahoo.com/v8/finance/chart/${m[1]}?range=${range}&interval=1d`;
    const r = await fetch(target, {
      headers: { 'User-Agent': 'Mozilla/5.0' },
      cf: { cacheTtl: 600, cacheEverything: true } // 10분 캐시(야후 부담 줄임)
    });
    const body = await r.text();
    return new Response(body, {
      status: r.status,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=600'
      }
    });
  }
};
