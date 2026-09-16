import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store';
import { downloadUrl, type Subject } from '../lib/archive';
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

// 체크한 파일들을 한꺼번에 받는다. <a target=_blank>를 여러 개 연달아 클릭하면
// 두 번째부터 팝업으로 막히므로 숨긴 iframe으로 연다.
export function SelectionBar() {
  const selected = useStore((s) => s.selected);
  const clear = useStore((s) => s.clearSelection);
  const ids = Object.keys(selected);
  const download = () => {
    ids.forEach((id, i) => {
      setTimeout(() => {
        const f = document.createElement('iframe');
        f.style.display = 'none';
        f.src = downloadUrl(id);
        document.body.appendChild(f);
        setTimeout(() => document.body.removeChild(f), 15000);
      }, i * 500);
    });
  };
  return (
    <AnimatePresence>
      {ids.length > 0 && (
        <motion.div className="selbar glass" initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}>
          <span style={{ fontSize: 13 }}>{ids.length}개 선택됨</span>
          <button className="btn sm on" onClick={download}>선택한 파일 다운로드</button>
          <button className="btn sm" onClick={clear}>선택 해제</button>
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
