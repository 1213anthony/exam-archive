import { useStore } from '../store';
import { viewUrl, type Exam, type ExamUnit, type Rec } from '../lib/archive';
import { colorOf } from '../theme/palette';
import { TrashButton } from '../admin/TrashButton';

function Doc({ r, cls, text }: { r: Rec | null; cls: 'q' | 'a'; text: string }) {
  const selected = useStore((s) => !!(r && s.selected[r.id]));
  const toggle = useStore((s) => s.toggleSelect);
  const admin = useStore((s) => s.admin);
  if (!r) return <span className="none">{text} 없음</span>;
  return (
    <span className="btn-wrap">
      <input type="checkbox" className="pick" checked={selected}
        onChange={(e) => toggle(r, e.target.checked)} title={r.filename} />
      <a className={'doc ' + cls} href={viewUrl(r)} target="_blank" rel="noopener">{text}</a>
      {admin && <TrashButton rec={r} />}
    </span>
  );
}

function Unit({ u }: { u: ExamUnit }) {
  return (
    <>
      <Doc r={u.problem} cls="q" text="문제" />
      <Doc r={u.solution} cls="a" text="해설" />
    </>
  );
}

export function ExamRow({ exam, category, showReview }: { exam: Exam; category: string; showReview?: boolean }) {
  const reviewed = useStore((s) => !!s.reviewed[exam.key]);
  const toggleReviewed = useStore((s) => s.toggleReviewed);
  const c = colorOf(category);
  const names = exam.units.flatMap((u) => u.shown.map((r) => r.filename));
  const extras = exam.units.flatMap((u) => u.extras);
  const clustered = exam.units.length > 1;
  const tail = [exam.semester ? exam.semester + '학기' : null, exam.examtype].filter(Boolean).join(' ');

  return (
    <div className={'exam' + (clustered ? ' clustered' : '')} style={{ ['--c' as string]: c.main }}>
      <div className="exam-label">
        <div className="exam-when">
          <span className="yr">{exam.year || '연도 미상'}</span>{tail}
          {exam.siblingFolder && <span className="flag" title="같은 이름의 형제 폴더가 2개 있는데 내용이 달라 합치지 않음">동명 폴더</span>}
          {showReview && (
            <button className={'reviewbtn' + (reviewed ? ' on' : '')} onClick={() => toggleReviewed(exam.key)}
              title="확인했다고 표시하면 '정리 필요만' 목록에서 빠집니다 (이 브라우저에만)">
              {reviewed ? '확인함' : '확인'}
            </button>
          )}
        </div>
        <div className="exam-files" title={names.length > 2 ? names.join('\n') : undefined}>
          {names.slice(0, 2).join('   ·   ')}{names.length > 2 ? `   ·   외 ${names.length - 2}개` : ''}
        </div>
        {extras.length > 0 && (
          <div className="extra">
            {extras.map((r) => (
              <a key={r.id} href={viewUrl(r)} target="_blank" rel="noopener">{(r.doctype || '기타')} 열기</a>
            ))}
          </div>
        )}
      </div>
      {!clustered ? (
        <div className="btns"><Unit u={exam.units[0]} /></div>
      ) : (
        <div className="btns-clustered">
          {exam.units.map((u, i) => (
            <div className="mini" key={i}>
              <span className="mini-label">{u.label}</span>
              <div className="btns"><Unit u={u} /></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
