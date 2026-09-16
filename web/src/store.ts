import { create } from 'zustand';
import type { Rec } from './lib/archive';

// localStorage 키는 classic/index.html과 똑같이 써서 기존 즐겨찾기가 그대로 살아있게 한다
export const KEYS = {
  favorites: 'examArchive.favorites.v1',
  favOnly: 'examArchive.favOnly.v1',
  reviewed: 'examArchive.reviewed.v1',
  hidden: 'examArchive.hidden.v1',
  catClosed: 'archive.catclosed',
  mode: 'examArchive.mode.v1',
} as const;

function loadMap<T = unknown>(key: string): Record<string, T> {
  try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch { return {}; }
}
function saveMap(key: string, obj: Record<string, unknown>) {
  try { localStorage.setItem(key, JSON.stringify(obj)); } catch { /* 저장 못 해도 화면은 돈다 */ }
}
function loadBool(key: string, fallback: boolean): boolean {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v === '1'; } catch { return fallback; }
}

export type Mode = '3d' | 'list';

export function favKey(category: string, subject: string) { return category + '||' + subject; }

// 폰·저사양·움직임 줄이기 설정에서는 3D를 켜지 않는다
export function detectDefaultMode(): Mode {
  try {
    const saved = localStorage.getItem(KEYS.mode);
    if (saved === '3d' || saved === 'list') return saved;
  } catch { /* ignore */ }
  if (typeof window === 'undefined') return 'list';
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const narrow = window.innerWidth < 900;
  return coarse || reduce || narrow ? 'list' : '3d';
}

interface State {
  data: Rec[];
  version: string;
  loaded: boolean;
  mode: Mode;
  // 탐색
  q: string;
  category: string | null;      // 3D: 들어가 있는 행성 / 목록: 탭
  subject: string | null;       // 3D: 열린 과목 패널
  favOnly: boolean;
  flagOnly: boolean;
  // 사용자 기록
  favorites: Record<string, 1>;
  reviewed: Record<string, 1>;
  hidden: Record<string, { filename: string }>;
  catClosed: Record<string, 1>;
  // 선택 다운로드
  selected: Record<string, Rec>;
  // 관리 모드
  admin: { email: string; token: string } | null;

  setData(data: Rec[], version: string): void;
  setMode(m: Mode): void;
  setQuery(q: string): void;
  goCategory(c: string | null): void;
  goSubject(c: string | null, s: string | null): void;
  toggleFavOnly(): void;
  toggleFlagOnly(): void;
  toggleFavorite(c: string, s: string): void;
  isFavorite(c: string, s: string): boolean;
  toggleReviewed(examKey: string): void;
  unhideAll(): void;
  setCatClosed(c: string, closed: boolean): void;
  toggleSelect(r: Rec, on: boolean): void;
  clearSelection(): void;
  setAdmin(a: State['admin']): void;
}

export const useStore = create<State>((set, get) => ({
  data: [],
  version: '',
  loaded: false,
  mode: detectDefaultMode(),
  q: '',
  category: null,
  subject: null,
  favOnly: loadBool(KEYS.favOnly, true),
  flagOnly: false,
  favorites: loadMap<1>(KEYS.favorites),
  reviewed: loadMap<1>(KEYS.reviewed),
  hidden: loadMap(KEYS.hidden),
  catClosed: loadMap<1>(KEYS.catClosed),
  selected: {},
  admin: null,

  setData: (data, version) => set({ data, version, loaded: true }),
  setMode: (mode) => { try { localStorage.setItem(KEYS.mode, mode); } catch { /* */ } set({ mode }); },
  setQuery: (q) => set({ q }),
  goCategory: (category) => set({ category, subject: null }),
  goSubject: (category, subject) => set({ category, subject }),
  toggleFavOnly: () => {
    const v = !get().favOnly;
    try { localStorage.setItem(KEYS.favOnly, v ? '1' : '0'); } catch { /* */ }
    set({ favOnly: v, flagOnly: v ? false : get().flagOnly });
  },
  toggleFlagOnly: () => {
    const v = !get().flagOnly;
    set({ flagOnly: v, favOnly: v ? false : get().favOnly });
  },
  toggleFavorite: (c, s) => {
    const favorites = { ...get().favorites };
    const k = favKey(c, s);
    if (favorites[k]) delete favorites[k]; else favorites[k] = 1;
    saveMap(KEYS.favorites, favorites);
    set({ favorites });
  },
  isFavorite: (c, s) => !!get().favorites[favKey(c, s)],
  toggleReviewed: (k) => {
    const reviewed = { ...get().reviewed };
    if (reviewed[k]) delete reviewed[k]; else reviewed[k] = 1;
    saveMap(KEYS.reviewed, reviewed);
    set({ reviewed });
  },
  unhideAll: () => { saveMap(KEYS.hidden, {}); set({ hidden: {} }); },
  setCatClosed: (c, closed) => {
    const catClosed = { ...get().catClosed };
    if (closed) catClosed[c] = 1; else delete catClosed[c];
    saveMap(KEYS.catClosed, catClosed);
    set({ catClosed });
  },
  toggleSelect: (r, on) => {
    const selected = { ...get().selected };
    if (on) selected[r.id] = r; else delete selected[r.id];
    set({ selected });
  },
  clearSelection: () => set({ selected: {} }),
  setAdmin: (admin) => set({ admin }),
}));

/** 화면에 보일 기록만 (숨김·분류 탭·즐겨찾기만·정리 필요만·검색어) */
export function selectVisible(s: State, incomplete: Set<string>): Rec[] {
  const q = s.q.trim().toLowerCase();
  return s.data.filter((r) => {
    if (s.hidden[r.id]) return false;
    if (s.favOnly && !s.favorites[favKey(r.category || '', r.subject || '')]) return false;
    if (s.flagOnly) {
      const k = (r.category || '') + '||' + [r.subject, r.year || '?', r.semester || '?', r.examtype || '?'].join('|');
      if (!incomplete.has(k)) return false;
      if (s.reviewed[[r.subject, r.year || '?', r.semester || '?', r.examtype || '?'].join('|')]) return false;
    }
    if (!q) return true;
    const hay = [r.category, r.subject, r.year, r.semester, r.examtype, r.doctype, r.filename]
      .filter(Boolean).join(' ').toLowerCase();
    return hay.indexOf(q) >= 0;
  });
}
