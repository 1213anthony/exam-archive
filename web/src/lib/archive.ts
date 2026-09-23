// 아카이브 데이터 가공 로직. classic/index.html에 있던 것을 그대로 옮긴 것이라
// 의미를 바꾸면 안 된다(시험 키, 중복 합치기, 세부과목 나누기, 정렬, 정리 필요 기준).
// 순수 함수만 두고 화면 상태는 store.ts가 가진다.

export interface Rec {
  id: string;
  filename: string;
  category?: string;
  subject?: string;
  subject_detail?: string;
  year?: string;
  semester?: string;
  examtype?: string;
  doctype?: string;
  parsed_ok?: boolean;
  folder_mismatch?: boolean;
  duplicate_sibling_folder?: boolean;
  size?: number | string;
  md5?: string;
  parent_id?: string;   // 드라이브에서 지금 들어있는 폴더 ID (관리자 "위치 변경"에 씀)
}

export const CAT_ORDER = [
  '국어', '수학', '물리', '화학', '생명과학', '지구과학', '정보',
  '사회', '외국어', '실험', '예체능', '창의융합특강',
];

export function catRank(c: string): number {
  const i = CAT_ORDER.indexOf(c);
  return i < 0 ? 99 : i;
}

export function viewUrl(r: Rec): string {
  return `https://drive.google.com/file/d/${r.id}/view`;
}

// ---- 문서유형 ----
export function isProblem(dt?: string): boolean {
  return !!dt && dt.indexOf('문제') >= 0;
}
export function isSolution(dt?: string): boolean {
  if (!dt) return false;
  return dt.indexOf('답안') >= 0 || dt.indexOf('해설') >= 0 || dt.indexOf('정답') >= 0;
}

// ---- 시험 키 ----
export function examKey(r: Rec): string {
  return [r.subject, r.year || '?', r.semester || '?', r.examtype || '?'].join('|');
}

// 한 해 안에서 시험이 실제로 치러지는 순서. 큰 값일수록 최근이다.
// 겨울 계절수업은 2학기 기말(12월) 다음인 이듬해 1월에 본다.
export function examOrder(semester?: string, examtype?: string): number {
  const t = examtype || '';
  if (t.indexOf('계절') >= 0) return 5;
  const base = semester === '2' ? 2 : semester === '1' ? 0 : -2;
  return base + (t.indexOf('기말') >= 0 ? 2 : 1);
}

// 최근에 본 시험이 앞으로 (연도 내림차순 → 그 해 안에서도 나중에 본 것부터)
export function compareExamKeys(a: string, b: string): number {
  const A = a.split('|'), B = b.split('|');
  if (A[1] !== B[1]) return (B[1] || '').localeCompare(A[1] || '');
  return examOrder(B[2], B[3]) - examOrder(A[2], A[3]);
}

export function matchesQuery(r: Rec, q: string): boolean {
  if (!q) return true;
  const hay = [r.category, r.subject, r.year, r.semester, r.examtype, r.doctype, r.filename]
    .filter(Boolean).join(' ').toLowerCase();
  return hay.indexOf(q.toLowerCase()) >= 0;
}

// ---- 같은 파일 합치기 ----
// 같은 파일이 여러 폴더에 복사돼 있다. 내용 해시가 같으면 한 번만 보여준다.
export function contentKey(r: Rec): string {
  if (r.md5) return 'h:' + r.md5;
  return 'n:' + r.filename + '|' + (r.size == null ? '' : r.size);
}
export function dedupeRecords(list: Rec[]): Rec[] {
  const seen = new Set<string>();
  const out: Rec[] = [];
  for (const r of list) {
    const k = contentKey(r);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(r);
  }
  return out;
}

// 같은 시험의 같은 문서유형이 여러 벌 남는 경우(A4/B4로 따로 스캔한 것 등)
// 화면에는 한 장만 내보낸다. 용량이 가장 큰 것(=제일 온전한 스캔)을 고른다.
export function pickBest(list: Rec[]): Rec | null {
  if (!list.length) return null;
  let best = list[0];
  for (let i = 1; i < list.length; i++) {
    if ((Number(list[i].size) || 0) > (Number(best.size) || 0)) best = list[i];
  }
  return best;
}
// 별지·듣기스크립트 같은 부속 자료도 문서유형별로 한 장씩만
export function pickBestPerDoctype(list: Rec[]): Rec[] {
  const buckets = new Map<string, Rec[]>();
  for (const r of list) {
    const k = r.doctype || '기타';
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k)!.push(r);
  }
  return [...buckets.values()].map((b) => pickBest(b)!) ;
}

// ---- 세부과목 나누기 ----
// 한 시험 줄 안에 "고전문학"과 "현대문학"처럼 실은 서로 다른 시험이 섞여 있을 수
// 있어서, 파일명 속 과목 표기(subject_detail)로 소그룹을 나눈다. 2학년/3학년은
// 실제로 다른 시험지라 절대 합치지 않는다.
export function normDetail(s?: string): string | null {
  if (!s) return null;
  s = s.replace(/\s+/g, '');
  s = s.replace(/^(모범답안및해설|모범답안|정답및해설|문제지|해설|정답|답안|문제)[_(\-]*/, '');
  s = s.replace(/[1-3]\s*학년/g, '');
  s = s.replace(/Ⅰ/g, 'I').replace(/Ⅱ/g, 'II').replace(/Ⅲ/g, 'III').replace(/Ⅳ/g, 'IV')
    .replace(/ⅰ/g, 'I').replace(/ⅱ/g, 'II').replace(/ⅲ/g, 'III').replace(/ⅳ/g, 'IV');
  s = s.replace(/IV/g, '4').replace(/III/g, '3').replace(/II/g, '2')
    .replace(/(^|[^I0-9])I(?![I0-9])/g, '$11');
  s = s.replace(/[()\[\]{},.\-_~]/g, '');
  return s.toLowerCase();
}
export function detailGrade(s?: string): string {
  if (!s) return '';
  const m = /([1-3])\s*학년/.exec(s);
  return m ? m[1] : '';
}
function splitTrailingNum(s: string): [string, string] {
  const m = /^(.*?)([1-4])$/.exec(s);
  return m ? [m[1], m[2]] : [s, ''];
}
function isSubsequence(a: string, b: string): boolean {
  let i = 0;
  for (let j = 0; j < b.length && i < a.length; j++) if (a[i] === b[j]) i++;
  return i === a.length;
}
function editDistance1(a: string, b: string): boolean {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0, j = 0, diff = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { i++; j++; continue; }
    if (++diff > 1) return false;
    if (a.length > b.length) i++;
    else if (a.length < b.length) j++;
    else { i++; j++; }
  }
  return diff + (a.length - i) + (b.length - j) <= 1;
}
export function sameSubject(k1: string, k2: string): boolean {
  const a = splitTrailingNum(k1), b = splitTrailingNum(k2);
  // 뒤 숫자가 둘 다 적혀 있는데 다르면 다른 과목. 한쪽만 없으면 표기 생략.
  if (a[1] && b[1] && a[1] !== b[1]) return false;
  const x = a[0], y = b[0];
  if (!x || !y) return false;
  return isSubsequence(x, y) || isSubsequence(y, x) || editDistance1(x, y);
}

export interface Cluster { label: string; records: Rec[] }

interface Bucket { label: string; base: string | null; grade: string; records: Rec[] }

export function clusterGroup(group: Rec[]): Cluster[] | null {
  const buckets = new Map<string, Bucket>();
  for (const r of group) {
    const base = normDetail(r.subject_detail);
    const grade = detailGrade(r.subject_detail);
    const key = base ? base + '@' + grade : '__etc__';
    if (!buckets.has(key)) {
      buckets.set(key, { label: r.subject_detail || '기타', base, grade, records: [] });
    }
    buckets.get(key)!.records.push(r);
  }

  // 1차: 학년이 서로 어긋나지 않는 별칭끼리만 합친다
  const merged: { keys: string[] }[] = [];
  for (const [k, bk] of buckets) {
    let placed = false;
    if (bk.base) {
      for (const m of merged) {
        const head = buckets.get(m.keys[0])!;
        if (head.base && head.grade === bk.grade && sameSubject(bk.base, head.base)) {
          m.keys.push(k); placed = true; break;
        }
      }
    }
    if (!placed) merged.push({ keys: [k] });
  }

  const recordsOf = (m: { keys: string[] }) => m.keys.flatMap((k) => buckets.get(k)!.records);
  const headOf = (m: { keys: string[] }) => buckets.get(m.keys[0])!;

  // 2차: 학년(또는 과목 표기)이 안 적힌 그룹은 붙일 곳이 하나로 특정될 때만 붙인다
  let changed = true;
  while (changed && merged.length > 1) {
    changed = false;
    for (let li = 0; li < merged.length; li++) {
      const L = merged[li], lh = headOf(L);
      if (lh.base && lh.grade) continue;
      const cands: number[] = [];
      for (let mi = 0; mi < merged.length; mi++) {
        if (mi === li) continue;
        const mh = headOf(merged[mi]);
        if (lh.base && !(mh.base && sameSubject(lh.base, mh.base))) continue;
        cands.push(mi);
      }
      if (!cands.length) continue;
      let target: number | null = null;
      if (cands.length === 1) {
        target = cands[0];
      } else {
        const mine = recordsOf(L);
        const hasQ = mine.some((r) => isProblem(r.doctype));
        const hasA = mine.some((r) => isSolution(r.doctype));
        const needy = cands.filter((mi) => {
          const rs = recordsOf(merged[mi]);
          const q = rs.some((r) => isProblem(r.doctype));
          const a = rs.some((r) => isSolution(r.doctype));
          return (hasQ && !q) || (hasA && !a);
        });
        if (needy.length === 1) target = needy[0];
      }
      if (target === null) continue;
      merged[target].keys = merged[target].keys.concat(L.keys);
      merged.splice(li, 1);
      changed = true;
      break;
    }
  }

  if (merged.length <= 1) return null;

  return merged.map((m) => {
    let best: string | null = null;
    for (const k of m.keys) {
      const bk = buckets.get(k)!;
      if (!best || (bk.base && (!buckets.get(best)!.base ||
          bk.records.length > buckets.get(best)!.records.length))) best = k;
    }
    return { label: buckets.get(best!)!.label, records: recordsOf(m) };
  }).sort((a, b) => b.records.length - a.records.length);
}

// ---- 화면용 구조 ----
export interface ExamUnit {
  label: string | null;      // 세부과목 라벨 (나뉘었을 때만)
  problem: Rec | null;
  solution: Rec | null;
  extras: Rec[];             // 별지, 듣기스크립트 …
  shown: Rec[];              // 실제로 화면에 나온 파일들
}
export interface Exam {
  key: string;
  year?: string;
  semester?: string;
  examtype?: string;
  units: ExamUnit[];
  fileCount: number;         // 합치기 전 원본 개수
  incomplete: boolean;       // 문제·해설 한쪽이 없는 단위가 있는가
  siblingFolder: boolean;    // "동명 폴더" 표시
}
export interface Subject {
  category: string;
  name: string;
  exams: Exam[];
  fileCount: number;
}
export interface Category {
  name: string;
  subjects: Subject[];
  examCount: number;
}

function buildUnit(label: string | null, recs: Rec[]): ExamUnit {
  const problem = pickBest(recs.filter((r) => isProblem(r.doctype)));
  const solution = pickBest(recs.filter((r) => isSolution(r.doctype)));
  const extras = pickBestPerDoctype(recs.filter((r) => !isProblem(r.doctype) && !isSolution(r.doctype)));
  const shown = [problem, solution].filter((x): x is Rec => !!x).concat(extras);
  return { label, problem, solution, extras, shown };
}

export function buildExam(key: string, all: Rec[]): Exam {
  const group = dedupeRecords(all);
  const clusters = clusterGroup(group);
  const units = clusters
    ? clusters.map((c) => buildUnit(c.label, c.records))
    : [buildUnit(null, group)];
  const first = group[0];
  return {
    key,
    year: first.year, semester: first.semester, examtype: first.examtype,
    units,
    fileCount: all.length,
    incomplete: units.some((u) => !u.problem || !u.solution),
    siblingFolder: all.length === group.length && group.some((r) => !!r.duplicate_sibling_folder),
  };
}

/** 전체 기록을 분류 → 과목 → 시험(최근순)으로 묶는다. rows는 이미 필터된 목록. */
export function buildTree(rows: Rec[]): Category[] {
  const byCat = new Map<string, Map<string, Map<string, Rec[]>>>();
  for (const r of rows) {
    const c = r.category || '(미분류)';
    const s = r.subject || '(과목 미상)';
    if (!byCat.has(c)) byCat.set(c, new Map());
    const bySub = byCat.get(c)!;
    if (!bySub.has(s)) bySub.set(s, new Map());
    const byExam = bySub.get(s)!;
    const k = examKey(r);
    if (!byExam.has(k)) byExam.set(k, []);
    byExam.get(k)!.push(r);
  }
  const cats = [...byCat.keys()].sort((a, b) => catRank(a) - catRank(b) || a.localeCompare(b, 'ko'));
  return cats.map((cName) => {
    const bySub = byCat.get(cName)!;
    const subjects = [...bySub.keys()].sort((a, b) => a.localeCompare(b, 'ko')).map((sName) => {
      const byExam = bySub.get(sName)!;
      const keys = [...byExam.keys()].sort(compareExamKeys);
      const exams = keys.map((k) => buildExam(k, byExam.get(k)!));
      const fileCount = exams.reduce((n, e) => n + e.fileCount, 0);
      return { category: cName, name: sName, exams, fileCount } as Subject;
    });
    return { name: cName, subjects, examCount: subjects.reduce((n, s) => n + s.exams.length, 0) };
  });
}

/** 정리 필요(문제/해설 한쪽이 없는) 시험 키 집합 — "분류||시험키" */
export function incompleteExamKeys(all: Rec[]): Set<string> {
  const out = new Set<string>();
  for (const c of buildTree(all)) {
    for (const s of c.subjects) {
      for (const e of s.exams) if (e.incomplete) out.add(c.name + '||' + e.key);
    }
  }
  return out;
}

export function countStats(all: Rec[]) {
  const tree = buildTree(all);
  let exams = 0, subjects = 0, incomplete = 0, unknownYear = 0;
  for (const c of tree) {
    subjects += c.subjects.length;
    for (const s of c.subjects) {
      for (const e of s.exams) {
        exams++;
        if (e.incomplete) incomplete++;
        if (!e.year) unknownYear++;
      }
    }
  }
  return { categories: tree.length, subjects, exams, incomplete, unknownYear, files: all.length };
}
