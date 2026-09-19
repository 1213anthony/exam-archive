import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store';
import { type Subject } from '../lib/archive';
import { downloadAsZip } from '../lib/bulkDownload';
import { CLIENT_ID } from '../admin/adminStore';
import { colorOf } from '../theme/palette';
import { ExamRow } from './ExamRow';

export function Loading({ text }: { text: string }) {
  return (
    <div className="loading">
      <div>
        <div className="orb" />
        <p>{text}</p>
      </div>
    </div>
  );
}

// 체크한 파일들을 zip 하나로 묶어 받는다. 드라이브 링크를 새 탭으로 여러 개 열면 두 번째부터
// 팝업으로 막히고, 숨긴 iframe은 구글의 로그인 확인 화면을 띄울 수 없어 조용히 실패한다.
// 그래서 구글 로그인 한 번 거쳐 API로 내용을 직접 받아 묶는다.
export function SelectionBar() {
  const selected = useStore((s) => s.selected);
  const clear = useStore((s) => s.clearSelection);
  const ids = Object.keys(selected);
  const recs = Object.values(selected);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const download = async () => {
    if (busy) return;
    setErr(null); setBusy(true); setProgress({ done: 0, total: recs.length });
    try {
      const { failed } = await downloadAsZip(recs, setProgress);
      if (failed.length) setErr(`${failed.length}개 파일은 못 받음 (권한 없음 등): ${failed.slice(0, 3).join(', ')}${failed.length > 3 ? ' 외' : ''}`);
    } catch (e: any) {
      setErr(e.message || '다운로드에 실패했습니다.');
    } finally {
      setBusy(false); setProgress(null);
    }
  };

  return (
    <AnimatePresence>
      {ids.length > 0 && (
        <motion.div className="selbar glass" initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}>
          <span style={{ fontSize: 13 }}>{ids.length}개 선택됨</span>
          {!CLIENT_ID ? (
            <span className="muted" style={{ fontSize: 12.5 }} title="site owner가 구글 로그인(Client ID) 설정을 아직 안 함">
              일괄 다운로드 설정 필요
            </span>
          ) : (
            <button className="btn sm on" onClick={download} disabled={busy}
              title="구글 로그인 후 zip 하나로 받습니다">
              {busy ? `받는 중… (${progress?.done ?? 0}/${progress?.total ?? 0})` : '선택한 파일 일괄 다운로드'}
            </button>
          )}
          <button className="btn sm" onClick={clear} disabled={busy}>선택 해제</button>
          {err && <span style={{ color: 'var(--danger)', fontSize: 12.5 }}>{err}</span>}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// 3D 모드에서 과목을 열면 오른쪽에 뜨는 유리 패널
export function ExamPanel({ subject }: { subject: Subject | null }) {
  const goSubject = useStore((s) => s.goSubject);
  const flagOnly = useStore((s) => s.flagOnly);
  const favorites = useStore((s) => s.favorites);
  const toggleFavorite = useStore((s) => s.toggleFavorite);
  return (
    <AnimatePresence>
      {subject && (
        <motion.aside className="panel glass" key={subject.category + subject.name}
          style={{ ['--c' as string]: colorOf(subject.category).main }}
          initial={{ x: 80, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 80, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 260, damping: 28 }}>
          <div className="panel-head">
            <span className="cat">{subject.category}</span>
            <h2>{subject.name}</h2>
            <span className="meta">{subject.exams.length}개 시험 · {subject.fileCount}개 파일</span>
            <button className={'star' + (favorites[subject.category + '||' + subject.name] ? ' on' : '')}
              onClick={() => toggleFavorite(subject.category, subject.name)} title="즐겨찾기">
              {favorites[subject.category + '||' + subject.name] ? '★' : '☆'}
            </button>
            <button className="btn sm close" onClick={() => goSubject(subject.category, null)} aria-label="닫기">Esc</button>
          </div>
          <div className="panel-body">
            {subject.exams.map((e) => <ExamRow key={e.key} exam={e} category={subject.category} showReview={flagOnly} />)}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
