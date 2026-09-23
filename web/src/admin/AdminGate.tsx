import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store';
import { useAdmin, ALLOWED_ADMINS, CLIENT_ID } from './adminStore';
import { trash, untrash, moveFile, whoAmI } from './drive';
import { loadGis } from '../lib/gis';
import { catRank } from '../lib/archive';
import { dispatchRecrawl } from './githubActions';

const SCOPES = 'https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/userinfo.email';
const GH_PAT_KEY = 'examArchive.ghpat';

export default function AdminGate() {
  const admin = useStore((s) => s.admin);
  const setAdmin = useStore((s) => s.setAdmin);
  const data = useStore((s) => s.data);
  const patchRecord = useStore((s) => s.patchRecord);
  const open = useAdmin((s) => s.panelOpen);
  const setOpen = useAdmin((s) => s.setPanelOpen);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const log = useAdmin((s) => s.log);
  const addLog = useAdmin((s) => s.addLog);
  const pending = useAdmin((s) => s.pending);
  const cancel = useAdmin((s) => s.cancel);
  const movePending = useAdmin((s) => s.movePending);
  const cancelMove = useAdmin((s) => s.cancelMove);
  const [typed, setTyped] = useState('');
  const [targetCategory, setTargetCategory] = useState('');
  const [targetSubject, setTargetSubject] = useState('');
  const [moveBusy, setMoveBusy] = useState(false);
  const configured = !!CLIENT_ID && ALLOWED_ADMINS.length > 0;

  // GitHub Actions 원격 재크롤링용 토큰. 번들에는 절대 안 들어가고, 이 브라우저에
  // 붙여넣은 값만 이 세션(탭을 닫으면 사라짐) 동안 기억한다.
  const [ghPat, setGhPat] = useState(() => { try { return sessionStorage.getItem(GH_PAT_KEY) || ''; } catch { return ''; } });
  const [ghBusy, setGhBusy] = useState(false);
  const [ghMsg, setGhMsg] = useState<string | null>(null);

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
  useEffect(() => {
    if (movePending) { setTargetCategory(movePending.category || ''); setTargetSubject(movePending.subject || ''); }
  }, [movePending]);

  // 목록 모드/3D에서 이미 쓰고 있는 데이터에서 과목 목록을 그대로 뽑는다 - 새 폴더를
  // 만드는 게 아니라 "이미 있는 과목 중 어디로 옮길지"만 고르게 한다.
  const categories = useMemo(() => {
    const set = new Set(data.map((r) => r.category).filter(Boolean) as string[]);
    return [...set].sort((a, b) => catRank(a) - catRank(b) || a.localeCompare(b, 'ko'));
  }, [data]);
  const subjectsInTarget = useMemo(() => {
    const set = new Set(data.filter((r) => r.category === targetCategory).map((r) => r.subject).filter(Boolean) as string[]);
    return [...set].sort((a, b) => a.localeCompare(b, 'ko'));
  }, [data, targetCategory]);

  const doMove = async () => {
    if (!admin || !movePending) return;
    const r = movePending;
    if (!r.parent_id) return;
    // 옮길 곳의 대표 폴더 = 그 과목에 이미 있는 다른 파일의 부모 폴더
    const dest = data.find((x) => x.category === targetCategory && x.subject === targetSubject && x.parent_id && x.id !== r.id);
    if (!dest || !dest.parent_id) {
      addLog({ at: new Date().toISOString(), action: 'error', id: r.id, name: r.filename, note: '옮길 폴더를 못 찾음' });
      return;
    }
    setMoveBusy(true);
    try {
      await moveFile(admin.token, r.id, dest.parent_id, r.parent_id);
      patchRecord(r.id, { category: targetCategory, subject: targetSubject, parent_id: dest.parent_id });
      addLog({
        at: new Date().toISOString(), action: 'move', id: r.id, name: r.filename,
        note: `${r.category} · ${r.subject} → ${targetCategory} · ${targetSubject}`,
      });
      cancelMove();
    } catch (e: any) {
      addLog({ at: new Date().toISOString(), action: 'error', id: r.id, name: r.filename, note: e.message });
    } finally {
      setMoveBusy(false);
    }
  };
  const unchanged = !!movePending && targetCategory === movePending.category && targetSubject === movePending.subject;

  const saveGhPat = (v: string) => {
    setGhPat(v);
    try { sessionStorage.setItem(GH_PAT_KEY, v); } catch { /* */ }
  };
  const doRecrawl = async () => {
    if (!ghPat.trim()) return;
    setGhBusy(true); setGhMsg(null);
    try {
      await dispatchRecrawl(ghPat.trim());
      setGhMsg('요청 보냄 — GitHub Actions 탭에서 진행 상황을 볼 수 있습니다. 몇 분 걸립니다.');
    } catch (e: any) {
      setGhMsg(e.message || '요청 실패');
    } finally {
      setGhBusy(false);
    }
  };

  return (
    <>
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
              <p className="muted">파일을 휴지통으로 보내거나 다른 과목 폴더로 옮길 수 있습니다. 파일 <b>소유자 계정</b>으로 로그인해야 실제로 됩니다.</p>
              <div className="row">
                <button className="btn sm on" onClick={signIn} disabled={busy}>{busy ? '로그인 중…' : 'Google로 로그인'}</button>
                <button className="btn sm" onClick={() => setOpen(false)}>닫기</button>
              </div>
              {err && <p style={{ color: 'var(--danger)' }}>{err}</p>}
            </>
          ) : (
            <>
              <h3>관리 모드 <span className="muted">· {admin.email}</span></h3>
              <p className="muted">문제/해설 옆 <b>↦</b>는 다른 과목으로 옮기기, <b>×</b>는 휴지통으로 보내기입니다. 회색으로 뜨면 이 계정에 권한이 없는 파일입니다(마우스를 올리면 소유자가 보임).</p>
              <div className="row">
                <button className="btn sm" onClick={saveLog} disabled={!log.length}>기록 저장 ({log.length})</button>
                <button className="btn sm" onClick={signOut}>로그아웃</button>
              </div>
              {log.length > 0 && (
                <div className="log">
                  {log.map((e, i) => (
                    <div key={i}>
                      [{e.at.slice(11, 19)}] {e.action === 'trash' ? '휴지통 →' : e.action === 'untrash' ? '복구 ←' : e.action === 'move' ? '이동 →' : '실패'} {e.name}
                      {e.note ? ` (${e.note})` : ''}
                      {e.action === 'trash' && <button className="reviewbtn" onClick={() => doUntrash(e.id, e.name)}>되돌리기</button>}
                    </div>
                  ))}
                </div>
              )}
              <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '12px 0' }} />
              <h3 style={{ fontSize: 13 }}>재크롤링</h3>
              <p className="muted" style={{ fontSize: 12.5 }}>
                드라이브를 전체 다시 훑어 사이트를 갱신합니다(GitHub Actions에서 실행, 몇 분 걸림).
                레포 Actions 쓰기 권한이 있는 GitHub 토큰이 필요 — 번들에는 안 들어가고 이 탭에만 기억됩니다.
              </p>
              <div className="row">
                <input type="password" value={ghPat} onChange={(e) => saveGhPat(e.target.value)}
                  placeholder="GitHub Personal Access Token" />
              </div>
              <div className="row">
                <button className="btn sm on" onClick={doRecrawl} disabled={ghBusy || !ghPat.trim()}>
                  {ghBusy ? '요청 보내는 중…' : '재크롤링 시작'}
                </button>
              </div>
              {ghMsg && <p className="muted" style={{ fontSize: 12.5 }}>{ghMsg}</p>}
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
      {movePending && admin && (
        <div className="modal-bg" onClick={cancelMove}>
          <div className="modal glass" onClick={(e) => e.stopPropagation()}>
            <h3>다른 과목으로 옮길까요?</h3>
            <ul><li>{movePending.filename}</li></ul>
            <p className="muted" style={{ fontSize: 12.5 }}>
              지금 위치: {movePending.category} · {movePending.subject} — 드라이브에서 실제로 폴더를 옮기며, 다음 크롤링에도 그대로 반영됩니다.
            </p>
            <div className="row">
              <select value={targetCategory} onChange={(e) => { setTargetCategory(e.target.value); setTargetSubject(''); }}>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={targetSubject} onChange={(e) => setTargetSubject(e.target.value)}>
                <option value="">과목 선택</option>
                {subjectsInTarget.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="row">
              <button className="btn sm" onClick={cancelMove}>취소</button>
              <button className="btn sm on" disabled={!targetSubject || unchanged || moveBusy} onClick={doMove}>
                {moveBusy ? '옮기는 중…' : '옮기기'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
