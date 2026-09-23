import { useMemo, useState } from 'react';
import type { Exam } from '../lib/archive';
import { ExamRow } from './ExamRow';

type TypeFilter = '전체' | '중간고사' | '기말고사';

// 과목 하나의 시험 목록. 중간/기말고사만 따로 보고 싶을 때 쓰는 필터를 붙였다.
// (겨울 계절수업처럼 그 외 시험종류는 "전체"에서만 보인다.)
export function ExamList({ exams, category, showReview }: { exams: Exam[]; category: string; showReview?: boolean }) {
  const [filter, setFilter] = useState<TypeFilter>('전체');
  const counts = useMemo(() => ({
    중간고사: exams.filter((e) => e.examtype === '중간고사').length,
    기말고사: exams.filter((e) => e.examtype === '기말고사').length,
  }), [exams]);
  const shown = filter === '전체' ? exams : exams.filter((e) => e.examtype === filter);

  return (
    <>
      <div className="examtype-filter">
        {(['전체', '중간고사', '기말고사'] as const).map((f) => (
          <button key={f} className={'btn sm' + (filter === f ? ' on' : '')} onClick={() => setFilter(f)}>
            {f}{f !== '전체' && <span className="n">{counts[f]}</span>}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <div className="empty" style={{ padding: '24px 0' }}>{filter}에 해당하는 시험이 없습니다.</div>
      ) : (
        shown.map((e) => <ExamRow key={e.key} exam={e} category={category} showReview={showReview} />)
      )}
    </>
  );
}
