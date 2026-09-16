import { useEffect, useState } from 'react';
import { useStore } from '../store';
import { useAdmin, ALLOWED_ADMINS, CLIENT_ID } from './adminStore';
import { trash, untrash, whoAmI } from './drive';

declare global {
  interface Window { google?: any }
}

// Google Identity Services는 구글이 배포하는 스크립트라 번들에 넣을 수 없다.
// 로그인 버튼을 눌렀을 때만 읽어온다.
function loadGis(): Promise<void> {
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

const SCOPES = 'https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/userinfo.email';

export default function AdminGate() {
  const admin = useStore((s) => s.admin);
  const setAdmin = useStore((s) => s.setAdmin);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const log = useAdmin((s) => s.log);
  const addLog = useAdmin((s) => s.addLog);
  const pending = useAdmin((s) => s.pending);
  const cancel = useAdmin((s) => s.cancel);
  const [typed, setTyped] = useState('');
  const configured = !!CLIENT_ID && ALLOWED_ADMINS.length > 0;

  const signIn = async () => {
    setErr(null); setBusy(true);
    try {
      await loadGis();
      const client = window.google.accounts.oauth2.initTokenClient({
        client_id: CLIENT_ID, scope: SCOPES,
        callback: async (resp: any) => {
          try {
            if (!resp || !resp.access_token) throw new Error('토큰을 못 받음');
            const email = (await whoAmI(resp.access_token)).toLowerCase();
            if (!ALLOWED_ADMINS.includes(email)) {
              setErr(`${email} 은(는) 관리자 목록에 없습니다.`);
              return;
            }
            setAdmin({ email, token: resp.access_token });
          } catch (e: any) { setErr(e.message || String(e)); }
          finally { setBusy(false); }
        },
        error_callback: (e: any) => { setErr(e?.message || '로그인 취소'); setBusy(false); },
      });
      client.requestAccessToken({ prompt: 'select_account' });
    } catch (e: any) { setErr(e.message || String(e)); setBusy(false); }
  };

  const signOut = () => { setAdmin(null); setOpen(false); };

  const doTrash = async () => {
    if (!admin || !pending) return;
    const r = pending;
    cancel(); setTyped('');
    try {
      await trash(admin.token, r.id);
      addLog({ at: new Date().toISOString(), action: 'trash', id: r.id, name: r.filename });
    } catch (e: any) {
      addLog({ at: new Date().toISOString(), action: 'error', id: r.id, name: r.filename, note: e.message });
    }
  };
  const doUntrash = async (id: string, name: string) => {
    if (!admin) return;
    try { await untrash(admin.token, id); addLog({ at: new Date().toISOString(), action: 'untrash', id, name }); }
    catch (e: any) { addLog({ at: new Date().toISOString(), action: 'error', id, name, note: e.message }); }
  };
  const saveLog = () => {
    const blob = new Blob([JSON.stringify(log, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'trash_log.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  useEffect(() => { if (!pending) setTyped(''); }, [pending]);

  return (
    <>
      <button className="lock glass" onClick={() => setOpen((v) => !v)} title={admin ? `관리 모드: ${admin.email}` : '관리자 로그인'}
        aria-label="관리자">{admin ? '🔓' : '🔒'}</button>
      {open && (
        <div className="adminbox glass">
          {!configured ? (
            <>
              <h3>관리 기능 설정 필요</h3>
              <p className="muted">web/.env 에 <code>VITE_GOOGLE_CLIENT_ID</code> 와 <code>VITE_ALLOWED_ADMINS</code> 를 넣고 다시 빌드하세요. (.env.example 참고)</p>
            </>
          ) : !admin ? (
            <>
              <h3>관리자 로그인</h3>
              <p className="muted">파일을 드라이브 휴지통으로 보낼 수 있습니다. 파일 <b>소유자 계정</b>으로 로그인해야 실제로 지워집니다.</p>
              <div className="row">
                <button className="btn sm on" onClick={signIn} disabled={busy}>{busy ? '로그인 중…' : 'Google로 로그인'}</button>
                <button className="btn sm" onClick={() => setOpen(false)}>닫기</button>
              </div>
              {err && <p style={{ color: 'var(--danger)' }}>{err}</p>}
            </>
          ) : (
            <>
              <h3>관리 모드 <span className="muted">· {admin.email}</span></h3>
              <p className="muted">파일 옆 <b>×</b>를 누르면 휴지통으로 보냅니다. 회색 ×는 이 계정에 권한이 없는 파일입니다(마우스를 올리면 소유자가 보임).</p>
              <div className="row">
                <button className="btn sm" onClick={saveLog} disabled={!log.length}>기록 저장 ({log.length})</button>
                <button className="btn sm" onClick={signOut}>로그아웃</button>
              </div>
              {log.length > 0 && (
                <div className="log">
                  {log.map((e, i) => (
                    <div key={i}>
                      [{e.at.slice(11, 19)}] {e.action === 'trash' ? '휴지통 →' : e.action === 'untrash' ? '복구 ←' : '실패'} {e.name}
                      {e.note ? ` (${e.note})` : ''}
                      {e.action === 'trash' && <button className="reviewbtn" onClick={() => doUntrash(e.id, e.name)}>되돌리기</button>}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
      {pending && admin && (
        <div className="modal-bg" onClick={cancel}>
          <div className="modal glass" onClick={(e) => e.stopPropagation()}>
            <h3>휴지통으로 보낼까요?</h3>
            <ul><li>{pending.filename}</li></ul>
            <p className="muted" style={{ fontSize: 12.5 }}>완전 삭제가 아니라 드라이브 휴지통으로 갑니다. 30일 안에 되돌릴 수 있고 이 화면의 기록에서도 되돌릴 수 있습니다.</p>
            <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} placeholder='진행하려면 "삭제" 라고 입력' />
            <div className="row">
              <button className="btn sm" onClick={cancel}>취소</button>
              <button className="btn sm danger" disabled={typed !== '삭제'} onClick={doTrash}>휴지통으로</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
