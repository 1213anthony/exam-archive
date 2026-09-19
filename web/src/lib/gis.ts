// Google Identity Services 스크립트를 필요할 때만 불러온다 (관리자 로그인, 일괄 다운로드 둘 다 씀).
declare global {
  interface Window { google?: any }
}

export function loadGis(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) { resolve(); return; }
    const s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('구글 로그인 스크립트를 못 불러옴'));
    document.head.appendChild(s);
  });
}

export function requestToken(scope: string): Promise<string> {
  return loadGis().then(() => new Promise<string>((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID || '',
      scope,
      callback: (resp: any) => {
        if (resp && resp.access_token) resolve(resp.access_token);
        else reject(new Error('토큰을 못 받음'));
      },
      error_callback: (e: any) => reject(new Error('구글 로그인 실패: ' + (e?.message || '로그인 취소 또는 팝업 차단'))),
    });
    client.requestAccessToken({ prompt: '' });
  }));
}
