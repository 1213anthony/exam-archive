// 분류마다 고유한 네온 색. 행성·카드·버튼·HUD 강조에 일관되게 쓴다.
// [주색, 밝은 하이라이트, 어두운 그림자]
export const PALETTE: Record<string, { main: string; glow: string; deep: string }> = {
  '국어':        { main: '#ff5c4d', glow: '#ff9d8a', deep: '#5a1410' },
  '수학':        { main: '#22d3ee', glow: '#a5f3fc', deep: '#083344' },
  '물리':        { main: '#a78bfa', glow: '#ddd6fe', deep: '#2e1065' },
  '화학':        { main: '#34d399', glow: '#a7f3d0', deep: '#022c22' },
  '생명과학':    { main: '#84cc16', glow: '#d9f99d', deep: '#1a2e05' },
  '지구과학':    { main: '#38bdf8', glow: '#bae6fd', deep: '#0c2a44' },
  '정보':        { main: '#f472b6', glow: '#fbcfe8', deep: '#500724' },
  '사회':        { main: '#fbbf24', glow: '#fde68a', deep: '#451a03' },
  '외국어':      { main: '#fb7185', glow: '#fecdd3', deep: '#4c0519' },
  '실험':        { main: '#c084fc', glow: '#e9d5ff', deep: '#3b0764' },
  '예체능':      { main: '#f97316', glow: '#fed7aa', deep: '#431407' },
  '창의융합특강': { main: '#e879f9', glow: '#f5d0fe', deep: '#4a044e' },
};
const FALLBACK = { main: '#94a3b8', glow: '#e2e8f0', deep: '#1e293b' };
export function colorOf(category?: string) {
  return (category && PALETTE[category]) || FALLBACK;
}
