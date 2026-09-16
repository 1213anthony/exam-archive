import { useEffect, useMemo, useRef } from 'react';
import { useStore } from '../store';
import { catRank, countStats } from '../lib/archive';
import { useFilteredTree } from './trees';
import { colorOf } from '../theme/palette';

export function Hud() {
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const q = useStore((s) => s.q);
  const setQuery = useStore((s) => s.setQuery);
  const favOnly = useStore((s) => s.favOnly);
  const flagOnly = useStore((s) => s.flagOnly);
  const toggleFavOnly = useStore((s) => s.toggleFavOnly);
  const toggleFlagOnly = useStore((s) => s.toggleFlagOnly);
  const category = useStore((s) => s.category);
  const subject = useStore((s) => s.subject);
  const goCategory = useStore((s) => s.goCategory);
  const goSubject = useStore((s) => s.goSubject);
  const data = useStore((s) => s.data);
  const version = useStore((s) => s.version);
  const inputRef = useRef<HTMLInputElement>(null);
  const { tree: hits } = useFilteredTree({ ignoreFavOnly: true });

  const stats = useMemo(() => countStats(data), [data]);
  const catCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const r of data) { const c = r.category || '(미분류)'; m[c] = (m[c] || 0) + 1; }
    return Object.keys(m).sort((a, b) => catRank(a) - catRank(b) || a.localeCompare(b, 'ko')).map((c) => [c, m[c]] as const);
  }, [data]);

  // 단축키: "/" 검색, Esc 뒤로
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
      if (e.key === '/' && !typing) { e.preventDefault(); inputRef.current?.focus(); }
      if (e.key === 'Escape') {
        if (typing && q) { setQuery(''); return; }
        const st = useStore.getState();
        if (st.subject) goSubject(st.category, null);
        else if (st.category) goCategory(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [q, setQuery, goCategory, goSubject]);

  return (
    <div className="hud">
      <div className="hud-row">
        <div className="brand">기출문제 아카이브 <small>서울과학고</small></div>
        <label className="search glass">
          <span style={{ color: 'var(--ink-soft)' }}>⌕</span>
          <input ref={inputRef} value={q} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              // Enter: 3D 모드에서는 첫 결과 과목으로 바로 날아간다
              if (e.key === 'Enter' && mode === '3d' && q.trim() && hits.length && hits[0].subjects.length) {
                goSubject(hits[0].name, hits[0].subjects[0].name);
                inputRef.current?.blur();
              }
            }}
            placeholder="과목, 연도, 파일명으로 검색…  (Enter: 첫 결과로)" aria-label="검색" />
          {q ? <button className="btn sm" onClick={() => setQuery('')}>지우기</button> : <kbd>/</kbd>}
        </label>
        <button className={'btn' + (favOnly ? ' on' : '')} onClick={toggleFavOnly} title="★ 표시한 과목만">즐겨찾기만</button>
        <button className={'btn' + (flagOnly ? ' on' : '')} onClick={toggleFlagOnly} title="문제지나 해설 한쪽이 안 보이는 시험만">정리 필요만</button>
        <div className="seg glass" role="group" aria-label="보기 모드">
          <button className={'btn' + (mode === '3d' ? ' on' : '')} onClick={() => setMode('3d')}>3D</button>
          <button className={'btn' + (mode === 'list' ? ' on' : '')} onClick={() => setMode('list')}>목록</button>
        </div>
      </div>

      {mode === 'list' ? (
        <div className="chips">
          <button className={'chip' + (category === null ? ' on' : '')} onClick={() => goCategory(null)}>
            전체<span className="n">{data.length}</span>
          </button>
          {catCounts.map(([c, n]) => (
            <button key={c} className={'chip' + (category === c ? ' on' : '')}
              style={{ ['--c' as string]: colorOf(c).main }}
              onClick={() => goCategory(category === c ? null : c)}>
              {c}<span className="n">{n}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="crumbs">
          <button onClick={() => goCategory(null)}>은하</button>
          {category && <><span className="sep">›</span>
            <button onClick={() => goSubject(category, null)} style={{ color: colorOf(category).glow }}>{category}</button></>}
          {subject && <><span className="sep">›</span><span className="here">{subject}</span></>}
          {!category && <span className="status" style={{ marginLeft: 8 }}>행성을 클릭해 들어가세요 · 휠 버튼 드래그로 회전 · Esc 로 나오기 · / 검색</span>}
        </div>
      )}

      <div className="status">
        {stats.exams}개 시험 · 파일 {stats.files}개
        {version ? ` · 데이터 ${version}` : ''}
      </div>
    </div>
  );
}
