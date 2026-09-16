import { create } from 'zustand';
import type { Rec } from '../lib/archive';

export interface LogEntry { at: string; action: 'trash' | 'untrash' | 'error'; id: string; name: string; note?: string }

interface AdminState {
  pending: Rec | null;              // 휴지통으로 보낼지 묻는 중인 파일
  log: LogEntry[];
  metaCache: Record<string, { canTrash: boolean; owner: string }>;
  ask(r: Rec): void;
  cancel(): void;
  addLog(e: LogEntry): void;
  setMeta(id: string, m: { canTrash: boolean; owner: string }): void;
}

export const useAdmin = create<AdminState>((set) => ({
  pending: null,
  log: [],
  metaCache: {},
  ask: (pending) => set({ pending }),
  cancel: () => set({ pending: null }),
  addLog: (e) => set((s) => ({ log: [e, ...s.log].slice(0, 200) })),
  setMeta: (id, m) => set((s) => ({ metaCache: { ...s.metaCache, [id]: m } })),
}));

export const ALLOWED_ADMINS: string[] = (import.meta.env.VITE_ALLOWED_ADMINS || '')
  .split(',').map((s: string) => s.trim().toLowerCase()).filter(Boolean);
export const CLIENT_ID: string = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
