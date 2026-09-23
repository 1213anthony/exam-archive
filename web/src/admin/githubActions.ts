// GitHub Actions로 원격 재크롤링을 트리거한다. 이 토큰은 번들에 절대 넣지 않는다 -
// 관리자가 매번(또는 이 브라우저 세션 동안만) 직접 입력한 값을 그대로 API 호출에만 쓴다.
const REPO = '1213anthony/exam-archive';
const WORKFLOW = 'crawl.yml';

export async function dispatchRecrawl(pat: string): Promise<void> {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${pat}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: 'main' }),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error(`재크롤링 요청 실패 (${r.status}) ${t.slice(0, 150)}`);
  }
}
