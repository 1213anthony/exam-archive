import { useEffect } from 'react';
import { useStore } from '../store';
import { useAdmin } from './adminStore';
import type { Rec } from '../lib/archive';

// 관리 모드에서만 렌더된다. 소유자 계정이 아니면(canTrash와 같은 권한 기준) 못 옮긴다 -
// 드라이브에서 폴더 이동도 결국 파일 수정 권한이 있어야 하기 때문.
export function MoveButton({ rec }: { rec: Rec }) {
  const admin = useStore((s) => s.admin);
  const meta = useAdmin((s) => s.metaCache[rec.id]);
  const askMove = useAdmin((s) => s.askMove);
  const setMeta = useAdmin((s) => s.setMeta);
  useEffect(() => {
    if (!admin || meta) return;
    let alive = true;
    import('./drive').then(({ getMeta }) => getMeta(admin.token, rec.id))
      .then((m) => { if (alive) setMeta(rec.id, { canTrash: m.canTrash, owner: m.owner }); })
      .catch(() => { if (alive) setMeta(rec.id, { canTrash: false, owner: '(조회 실패)' }); });
    return () => { alive = false; };
  }, [admin, meta, rec.id, setMeta]);
  if (!admin) return null;
  const can = meta ? meta.canTrash && !!rec.parent_id : false;
  const title = !meta ? '권한 확인 중…'
    : !rec.parent_id ? '이 파일은 위치 정보가 없음 — 전체 재크롤링 후 다시 시도'
    : meta.canTrash ? '다른 과목 폴더로 옮기기'
    : `이 파일은 ${meta.owner} 소유 — 그 계정으로 로그인해야 옮길 수 있음`;
  return (
    <button className="move" disabled={!can} title={title} onClick={() => askMove(rec)} aria-label="위치 변경">
      {meta ? '↦' : '…'}
    </button>
  );
}
