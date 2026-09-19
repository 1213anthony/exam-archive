import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store';
import { viewUrl, type Rec, type Subject } from '../lib/archive';
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

// 체크한 파일들을 한꺼번에 받는다. 예전에는 숨긴 iframe으로 uc?export=download를 불러
// 조용히 저장했지만, 구글이 다운로드 전에 로그인/확인 화면을 끼워 넣게 되면서
// 숨긴 iframe 안에서는 그 화면이 아예 안 보여 아무 일도 안 일어나는 것처럼 되어버렸다.
// 그래서 각 파일을 새 탭(드라이브 보기 화면)으로 열어, 로그인이 필요하면 사용자가 직접 보고 처리하게 한다.
export function SelectionBar() {
  const selected = useStore((s) => s.selected);
  const clear = useStore((s) => s.clearSelection);
  const ids = Object.keys(selected);
  const recs = Object.values(selected);
  const download = () => {
    recs.forEach((r: Rec, i) => {
      setTimeout(() => window.open(viewUrl(r), '_blank', 'noopener'), i * 300);
    });
  };
  return (
    <AnimatePresence>
      {ids.length > 0 && (
        <motion.div className="selbar glass" initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}>
          <span style={{ fontSize: 13 }}>{ids.length}개 선택됨</span>
          <button className="btn sm on" onClick={download} title="각 파일을 드라이브 보기 화면으로 새 탭에 엽니다">선택한 파일 열기</button>
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
