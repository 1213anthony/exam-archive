import { useMemo } from 'react';
import { useStore, selectVisible, favKey } from '../store';
import { buildTree, incompleteExamKeys, type Category } from '../lib/archive';
import { colorOf } from '../theme/palette';
import { ExamRow } from './ExamRow';

export function useVisibleTree(): { tree: Category[]; rowCount: number } {
  const data = useStore((s) => s.data);
  const q = useStore((s) => s.q);
  const favOnly = useStore((s) => s.favOnly);
  const flagOnly = useStore((s) => s.flagOnly);
  const favorites = useStore((s) => s.favorites);
  const reviewed = useStore((s) => s.reviewed);
  const hidden = useStore((s) => s.hidden);
  const category = useStore((s) => s.category);
  const mode = useStore((s) => s.mode);
  const incomplete = useMemo(() => incompleteExamKeys(data), [data]);
  return useMemo(() => {
    const st = useStore.getState();
    let rows = selectVisible({ ...st, q, favOnly, flagOnly, favorites, reviewed, hidden }, incomplete);
    // 목록 모드에서 분류 탭을 고른 경우만 거른다 (3D 모드의 category는 "들어가 있는 행성")
    if (mode === 'list' && category) rows = rows.filter((r) => (r.category || '(미분류)') === category);
    return { tree: buildTree(rows), rowCount: rows.length };
  }, [data, q, favOnly, flagOnly, favorites, reviewed, hidden, category, mode, incomplete]);
}

export function ClassicList() {
  const { tree, rowCount } = useVisibleTree();
  const q = useStore((s) => s.q);
  const favOnly = useStore((s) => s.favOnly);
  const flagOnly = useStore((s) => s.flagOnly);
  const catClosed = useStore((s) => s.catClosed);
  const setCatClosed = useStore((s) => s.setCatClosed);
  const favorites = useStore((s) => s.favorites);
  const toggleFavorite = useStore((s) => s.toggleFavorite);
  const hidden = useStore((s) => s.hidden);
  const unhideAll = useStore((s) => s.unhideAll);
  const category = useStore((s) => s.category);
  const forceOpen = !!q || flagOnly;
  const autoOpenSubjects = !!q || flagOnly || rowCount <= 60;
  const hiddenCount = Object.keys(hidden).length;

  return (
    <div className="list-wrap">
      <div className="list-inner">
        {hiddenCount > 0 && (
          <div className="glass" style={{ padding: '10px 14px', fontSize: 13 }}>
            예전에 직접 숨긴 파일 {hiddenCount}개가 있습니다 (이 브라우저에만 적용)
            <button className="btn sm" style={{ marginLeft: 10 }} onClick={unhideAll}>모두 되돌리기</button>
          </div>
        )}
        {tree.length === 0 && (
          <div className="empty">
            {favOnly ? <>즐겨찾기한 과목이 없습니다.<br />과목 이름 옆 ☆를 눌러 추가하거나, 즐겨찾기만 보기를 끄세요.</>
              : flagOnly ? '정리할 시험이 없습니다.' : '검색 결과가 없습니다.'}
          </div>
        )}
        {tree.map((c) => {
          const col = colorOf(c.name);
          const wrap = !category && tree.length > 1;
          const body = c.subjects.map((s) => (
            <details className="subj" key={s.name} open={autoOpenSubjects}>
              <summary>
                <span className="subj-name">{s.name}</span>
                <span className="subj-meta">{s.exams.length}개 시험 · {s.fileCount}개 파일</span>
                <button className={'star' + (favorites[favKey(c.name, s.name)] ? ' on' : '')} title="즐겨찾기"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleFavorite(c.name, s.name); }}>
                  {favorites[favKey(c.name, s.name)] ? '★' : '☆'}
                </button>
              </summary>
              <div className="subj-body">
                {s.exams.map((e) => <ExamRow key={e.key} exam={e} category={c.name} showReview={flagOnly} />)}
              </div>
            </details>
          ));
          if (!wrap) return <div key={c.name}>{body}</div>;
          return (
            <details className="cat" key={c.name} style={{ ['--c' as string]: col.main }}
              open={forceOpen || !catClosed[c.name]}
              onToggle={(e) => { if (!forceOpen) setCatClosed(c.name, !(e.currentTarget as HTMLDetailsElement).open); }}>
              <summary>
                <span className="cat-name">{c.name}</span>
                <span className="cat-meta">{c.subjects.length}개 과목 · {c.examCount}개 시험</span>
              </summary>
              {body}
            </details>
          );
        })}
      </div>
    </div>
  );
}
