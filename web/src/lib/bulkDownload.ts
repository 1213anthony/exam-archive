// 여러 파일을 zip 하나로 묶어 한 번에 받는다. 드라이브 링크를 새 탭으로 여러 개 열면
// 두 번째부터 팝업으로 막히고, 숨긴 iframe은 구글의 로그인 확인 화면을 띄울 수 없어
// 조용히 실패한다 — 그래서 구글 로그인 후 API로 파일 내용을 직접 받아 묶는다.
import { requestToken } from './gis';
import type { Rec } from './archive';

const SCOPE = 'https://www.googleapis.com/auth/drive.readonly';
let cachedToken: { token: string; expiresAt: number } | null = null;

async function getToken(): Promise<string> {
  if (cachedToken && cachedToken.expiresAt > Date.now() + 30_000) return cachedToken.token;
  const token = await requestToken(SCOPE);
  cachedToken = { token, expiresAt: Date.now() + 55 * 60_000 };
  return token;
}

async function fetchFile(token: string, r: Rec): Promise<Blob> {
  const res = await fetch(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(r.id)}?alt=media`, {
    headers: { Authorization: 'Bearer ' + token },
  });
  if (!res.ok) throw new Error(`${r.filename}: ${res.status}`);
  return res.blob();
}

export interface BulkProgress { done: number; total: number }

export async function downloadAsZip(recs: Rec[], onProgress?: (p: BulkProgress) => void): Promise<{ failed: string[] }> {
  const jszipMod = await import('jszip');
  const token = await getToken();
  const zip = new jszipMod.default();
  const failed: string[] = [];
  let done = 0;
  onProgress?.({ done, total: recs.length });
  for (const r of recs) {
    try {
      const blob = await fetchFile(token, r);
      zip.file(r.filename, blob);
    } catch {
      failed.push(r.filename);
    }
    done++;
    onProgress?.({ done, total: recs.length });
  }
  if (done - failed.length > 0) {
    const blob = await zip.generateAsync({ type: 'blob' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = recs.length === 1 ? recs[0].filename.replace(/\.pdf$/i, '') + '.zip' : `기출문제_${recs.length}개.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
  }
  return { failed };
}
