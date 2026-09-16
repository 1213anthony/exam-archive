import { useEffect } from 'react';
import { useStore } from '../store';
import { useAdmin } from './adminStore';
import type { Rec } from '../lib/archive';

// 관리 모드에서만 렌더된다. 권한을 미리 물어봐서, 못 지우는 파일은 이유를 보여준다.
export function TrashButton({ rec }: { rec: Rec }) {
  const admin = useStore((s) => s.admin);
  const meta = useAdmin((s) => s.metaCache[rec.id]);
  const ask = useAdmin((s) => s.ask);
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
  const can = meta ? meta.canTrash : false;
  const title = !meta ? '권한 확인 중…'
    : can ? '드라이브 휴지통으로 보내기'
    : `이 파일은 ${meta.owner} 소유 — 그 계정으로 로그인해야 지울 수 있음`;
  return (
    <button className="trash" disabled={!can} title={title} onClick={() => ask(rec)} aria-label="휴지통으로">
      {meta ? '×' : '…'}
    </button>
  );
}
