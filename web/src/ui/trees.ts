import { useMemo } from 'react';
import { useStore, selectVisible } from '../store';
import { buildTree, incompleteExamKeys, type Category } from '../lib/archive';

/** 필터를 하나도 안 건 전체 구조 (3D 공간의 뼈대) */
export function useFullTree(): Category[] {
  const data = useStore((s) => s.data);
  const hidden = useStore((s) => s.hidden);
  return useMemo(() => buildTree(data.filter((r) => !hidden[r.id])), [data, hidden]);
}

/** 검색어·정리필요(·즐겨찾기만)를 적용한 구조. 3D 모드에서는 즐겨찾기만을 무시한다
 *  (3D에서 즐겨찾기는 "위성"으로 따로 보여주므로 나머지를 숨길 이유가 없다). */
export function useFilteredTree(opts: { ignoreFavOnly: boolean }): { tree: Category[]; rowCount: number; active: boolean } {
  const data = useStore((s) => s.data);
  const q = useStore((s) => s.q);
  const favOnly = useStore((s) => s.favOnly);
  const flagOnly = useStore((s) => s.flagOnly);
  const favorites = useStore((s) => s.favorites);
  const reviewed = useStore((s) => s.reviewed);
  const hidden = useStore((s) => s.hidden);
  const incomplete = useMemo(() => incompleteExamKeys(data), [data]);
  return useMemo(() => {
    const st = useStore.getState();
    const fav = opts.ignoreFavOnly ? false : favOnly;
    const rows = selectVisible({ ...st, q, favOnly: fav, flagOnly, favorites, reviewed, hidden }, incomplete);
    return { tree: buildTree(rows), rowCount: rows.length, active: !!q.trim() || flagOnly || fav };
  }, [data, q, favOnly, flagOnly, favorites, reviewed, hidden, incomplete, opts.ignoreFavOnly]);
}
