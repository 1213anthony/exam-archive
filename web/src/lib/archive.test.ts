// 실제 data.js를 그대로 읽어서 화면에 찍히던 숫자가 그대로 나오는지 본다.
// 이 숫자들은 classic/index.html이 마지막으로 보여주던 값이다. 로직을 옮기면서
// 의미가 바뀌었으면 여기서 바로 걸린다.
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  countStats, buildTree, examOrder, compareExamKeys, normDetail, detailGrade,
  sameSubject, clusterGroup, pickBest, dedupeRecords, type Rec,
} from './archive';

function loadData(): Rec[] {
  const src = fs.readFileSync(path.resolve(__dirname, '../../../data.js'), 'utf-8');
  // data.js는 var 선언 두 개짜리 스크립트다
  const fn = new Function(src + '; return EXAM_DATA;');
  return fn() as Rec[];
}

describe('실제 데이터 회귀', () => {
  const all = loadData();
  const st = countStats(all);
  it('파일 수', () => expect(st.files).toBe(13566));
  it('분류 12개', () => expect(st.categories).toBe(12));
  it('과목 102개', () => expect(st.subjects).toBe(102));
  it('시험 1889줄', () => expect(st.exams).toBe(1889));
  it('정리 필요 15개', () => expect(st.incomplete).toBe(15));
  it('연도 미상 0개', () => expect(st.unknownYear).toBe(0));

  it('한 시험 줄에 같은 문서유형은 한 장만', () => {
    for (const c of buildTree(all)) for (const s of c.subjects) for (const e of s.exams) {
      for (const u of e.units) {
        expect(u.shown.filter((r) => r === u.problem).length).toBeLessThanOrEqual(1);
        expect(u.shown.filter((r) => r === u.solution).length).toBeLessThanOrEqual(1);
      }
    }
  });

  it('2학년/3학년 시험지는 합치지 않는다 (생명과학3 2023 1기말)', () => {
    const bio = buildTree(all).find((c) => c.name === '생명과학')!
      .subjects.find((s) => s.name === '생명과학3')!;
    const e = bio.exams.find((x) => x.key.startsWith('생명과학3|2023|1|기말'))!;
    expect(e.units.length).toBe(2);
    expect(e.units.every((u) => u.problem && u.solution)).toBe(true);
  });
});

describe('정렬', () => {
  it('한 해 안에서 나중에 본 시험이 앞으로', () => {
    const keys = ['x|2014|1|중간고사', 'x|2014|2|기말고사', 'x|2014|1|기말고사',
                  'x|2014|2|중간고사', 'x|2014|?|겨울 계절수업', 'x|2015|1|중간고사'];
    expect(keys.slice().sort(compareExamKeys)).toEqual([
      'x|2015|1|중간고사', 'x|2014|?|겨울 계절수업', 'x|2014|2|기말고사',
      'x|2014|2|중간고사', 'x|2014|1|기말고사', 'x|2014|1|중간고사',
    ]);
  });
  it('examOrder 값', () => {
    expect(examOrder('1', '중간고사')).toBeLessThan(examOrder('1', '기말고사'));
    expect(examOrder('1', '기말고사')).toBeLessThan(examOrder('2', '중간고사'));
    expect(examOrder('2', '기말고사')).toBeLessThan(examOrder(undefined, '겨울 계절수업'));
  });
});

describe('세부과목 표기 정규화', () => {
  it('로마숫자·괄호·접두사', () => {
    expect(normDetail('문제지(고급물리학1)')).toBe('고급물리학1');
    expect(normDetail('고급생명과학I(2학년')).toBe('고급생명과학1');
    expect(normDetail('(생명과학IV, 3학년)')).toBe('생명과학4');
    expect(normDetail('생명과학Ⅲ3학년')).toBe('생명과학3');
    expect(detailGrade('생명과학3_2학년')).toBe('2');
  });
  it('한쪽만 번호를 안 적은 건 같은 과목', () => {
    expect(sameSubject('선형대수학', '선형대수학1')).toBe(true);
    expect(sameSubject('고급물리학1', '고급물리학2')).toBe(false);
    expect(sameSubject('고전문학', '현대문학')).toBe(false);
  });
  it('학년이 안 적힌 문제지는 해설이 비어 있는 학년에 붙는다', () => {
    const g: Rec[] = [
      { id: 'a', filename: 'q3', subject_detail: '(생명과학IV, 3학년)', doctype: '문제지' },
      { id: 'b', filename: 'a2', subject_detail: '생명과학4(2학년)', doctype: '모범답안및해설' },
      { id: 'c', filename: 'q?', subject_detail: '생명과학4', doctype: '문제지' },
    ];
    const cl = clusterGroup(g)!;
    expect(cl.length).toBe(2);
    const two = cl.find((c) => c.records.some((r) => r.id === 'b'))!;
    expect(two.records.some((r) => r.id === 'c')).toBe(true);
  });
});

describe('중복·판본', () => {
  it('md5가 같으면 한 번만', () => {
    const l: Rec[] = [{ id: '1', filename: 'a', md5: 'x' }, { id: '2', filename: 'b', md5: 'x' }];
    expect(dedupeRecords(l).length).toBe(1);
  });
  it('여러 벌이면 용량 큰 것', () => {
    const l: Rec[] = [{ id: '1', filename: 'a', size: 10 }, { id: '2', filename: 'b', size: 99 }];
    expect(pickBest(l)!.id).toBe('2');
  });
});
