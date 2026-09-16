import type { Rec } from '../lib/archive';

declare global {
  interface Window { EXAM_DATA?: Rec[]; EXAM_DATA_VERSION?: string }
}

// data.js(5MB)는 번들에 넣지 않고 그때그때 읽는다. 크롤러가 새로 만들어 올리면
// 프론트를 다시 빌드하지 않아도 갱신되게 하려는 것.
export function loadData(): Promise<{ data: Rec[]; version: string }> {
  return new Promise((resolve, reject) => {
    if (window.EXAM_DATA) {
      resolve({ data: window.EXAM_DATA, version: window.EXAM_DATA_VERSION || '' });
      return;
    }
    const s = document.createElement('script');
    // 캐시된 옛 데이터를 보는 일이 없도록 버전 대신 시각을 붙인다(10분 단위)
    s.src = import.meta.env.BASE_URL + 'data.js?v=' + Math.floor(Date.now() / 600000);
    s.onload = () => {
      if (!window.EXAM_DATA) { reject(new Error('data.js에 EXAM_DATA가 없음')); return; }
      resolve({ data: window.EXAM_DATA, version: window.EXAM_DATA_VERSION || '' });
    };
    s.onerror = () => reject(new Error('data.js를 불러오지 못함'));
    document.head.appendChild(s);
  });
}
