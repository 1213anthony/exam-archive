import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { useStore } from './store';
import { loadData } from './data/load';
import { Hud } from './ui/Hud';
import { ClassicList } from './ui/ClassicList';
import { Loading, SelectionBar, ExamPanel } from './ui/Bits';
import { useFilteredTree } from './ui/trees';

const Galaxy = lazy(() => import('./scene/Galaxy').then((m) => ({ default: m.Galaxy })));
const AdminGate = lazy(() => import('./admin/AdminGate'));

function SubjectPanelHost() {
  // 3D 모드에서 열린 과목의 시험 목록. 검색·정리필요는 적용하고 즐겨찾기만은 무시한다.
  const category = useStore((s) => s.category);
  const subject = useStore((s) => s.subject);
  const { tree } = useFilteredTree({ ignoreFavOnly: true });
  const subj = useMemo(() => {
    if (!category || !subject) return null;
    const c = tree.find((x) => x.name === category);
    return c ? c.subjects.find((s) => s.name === subject) || null : null;
  }, [tree, category, subject]);
  // 검색으로 걸러져 시험이 하나도 없으면 빈 패널 대신 닫는다
  return <ExamPanel subject={subj && subj.exams.length ? subj : null} />;
}

export default function App() {
  const loaded = useStore((s) => s.loaded);
  const setData = useStore((s) => s.setData);
  const mode = useStore((s) => s.mode);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    loadData().then(({ data, version }) => setData(data, version)).catch((e) => setErr(e.message));
  }, [setData]);

  if (err) return <Loading text={'데이터를 불러오지 못했습니다: ' + err} />;
  if (!loaded) return <Loading text="시험지 13,000장을 불러오는 중…" />;

  return (
    <>
      <div className="bg-space" />
      {mode === '3d' ? (
        <Suspense fallback={<Loading text="은하를 만드는 중…" />}>
          <Galaxy />
          <SubjectPanelHost />
        </Suspense>
      ) : (
        <ClassicList />
      )}
      <Hud />
      <SelectionBar />
      <Suspense fallback={null}><AdminGate /></Suspense>
    </>
  );
}
