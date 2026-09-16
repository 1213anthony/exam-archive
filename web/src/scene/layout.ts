import * as THREE from 'three';
import type { Category, Subject } from '../lib/archive';

// 3D 공간에서 행성·카드가 놓이는 자리. 한 곳에서 계산해 카메라와 렌더가 같은 값을 쓴다.
export const GALAXY_CAM = new THREE.Vector3(0, 40, 50);
export const ORIGIN = new THREE.Vector3(0, 0, 0);

// 즐겨찾기 성운: 은하에서 멀리 떨어진 별도의 자리. 은하 화면에서는 저 멀리 금빛으로만 보인다.
export const NEBULA_POS = new THREE.Vector3(-50, -3, -34);

export interface PlanetSpot { cat: Category; pos: THREE.Vector3; radius: number; hue: number }

export function planetSpots(tree: Category[]): PlanetSpot[] {
  const n = tree.length || 1;
  return tree.map((cat, i) => {
    // 12개를 두 겹 고리(안 6 · 밖 6)에 번갈아 놓고, 바깥 고리는 반 칸 돌려서
    // 서로의 사이에 오게 한다. 라벨이 겹치지 않을 만큼 벌린다.
    const outer = i % 2 === 1;
    const a = (i / n) * Math.PI * 2 - Math.PI / 2 + (outer ? Math.PI / n : 0);
    const ring = outer ? 30 : 17.5;
    const pos = new THREE.Vector3(Math.cos(a) * ring, Math.sin(a * 2) * 2.6 + (outer ? 2.2 : -1.6), Math.sin(a) * ring * 0.8);
    const radius = 0.9 + Math.sqrt(cat.examCount) / 9;   // 시험 수에 비례 (1.1 ~ 2.9)
    return { cat, pos, radius, hue: i / n };
  });
}

export interface CardSpot { subj: Subject; pos: THREE.Vector3 }

/** 카드 격자가 놓이는 기준 좌표계: out=카메라가 있는 쪽, right=화면 오른쪽, up */
export interface Frame { out: THREE.Vector3; up: THREE.Vector3; right: THREE.Vector3 }

function frameToward(out: THREE.Vector3): Frame {
  const up = new THREE.Vector3(0, 1, 0);
  // 카메라는 -out 방향을 본다. 화면 오른쪽 = cross(전방, up) = cross(-out, up) = cross(up, out)
  const right = new THREE.Vector3().crossVectors(up, out).normalize();
  return { out: out.clone().normalize(), up, right };
}

/** 행성 기준: 원점에서 바깥쪽이 카메라 쪽 */
export function planetFrame(spot: PlanetSpot): Frame {
  return frameToward(new THREE.Vector3(spot.pos.x, 0, spot.pos.z));
}
/** 성운 기준: 성운에서 은하 쪽을 바라보는 방향이 카메라 쪽 */
export function nebulaFrame(): Frame {
  return frameToward(ORIGIN.clone().sub(NEBULA_POS).setY(0));
}

const CARD_W = 3.9, CARD_H = 2.45;

function gridDims(n: number) {
  const cols = Math.max(1, Math.min(6, Math.ceil(Math.sqrt(n * 1.7))));
  return { cols, rows: Math.ceil(n / cols) };
}

/** 격자에 n장을 놓는다 (center 를 중심으로, 카메라를 정면으로 본다) */
export function gridSpots(center: THREE.Vector3, f: Frame, n: number): THREE.Vector3[] {
  const { cols, rows } = gridDims(n);
  const out: THREE.Vector3[] = [];
  for (let j = 0; j < n; j++) {
    const c = j % cols, r = Math.floor(j / cols);
    const x = (c - (cols - 1) / 2) * CARD_W;
    const y = ((rows - 1) / 2 - r) * CARD_H;
    out.push(center.clone().add(f.right.clone().multiplyScalar(x)).add(f.up.clone().multiplyScalar(y)));
  }
  return out;
}

/** 격자 정면에서 격자 전체가 들어오게 물러선 카메라 */
export function gridCam(center: THREE.Vector3, f: Frame, n: number): { pos: THREE.Vector3; look: THREE.Vector3 } {
  const { cols, rows } = gridDims(n);
  const dist = 9 + Math.max(cols * CARD_W, rows * CARD_H * 1.6) * 0.62;
  const pos = center.clone().add(f.out.clone().multiplyScalar(dist)).add(f.up.clone().multiplyScalar(1.2));
  return { pos, look: center.clone() };
}

/** 카드 앞에 멈추는 카메라. 오른쪽에 패널이 뜨므로 카드가 화면 왼쪽으로 오게 시선을 튼다 */
export function cardCam(cardPos: THREE.Vector3, f: Frame): { pos: THREE.Vector3; look: THREE.Vector3 } {
  const shift = f.right.clone().multiplyScalar(3.4);
  const pos = cardPos.clone().add(f.out.clone().multiplyScalar(10.5)).add(f.up.clone().multiplyScalar(0.4)).add(shift);
  return { pos, look: cardPos.clone().add(shift) };
}

// ---- 행성 안 ----
function planetGridCenter(spot: PlanetSpot, f: Frame) {
  return spot.pos.clone().add(f.out.clone().multiplyScalar(spot.radius + 7)).add(f.up.clone().multiplyScalar(0.6));
}
/** 과목 카드는 행성 앞에 격자로 펼친다. 행성은 뒤에서 배경처럼 빛난다. */
export function cardSpots(spot: PlanetSpot): CardSpot[] {
  const f = planetFrame(spot);
  const pts = gridSpots(planetGridCenter(spot, f), f, spot.cat.subjects.length);
  return spot.cat.subjects.map((subj, j) => ({ subj, pos: pts[j] }));
}
export function categoryCam(spot: PlanetSpot) {
  const f = planetFrame(spot);
  return gridCam(planetGridCenter(spot, f), f, spot.cat.subjects.length);
}
export function subjectCam(spot: PlanetSpot, card: CardSpot) {
  return cardCam(card.pos, planetFrame(spot));
}

// ---- 즐겨찾기 성운 ----
export interface NebulaCard { category: string; subj: Subject; pos: THREE.Vector3 }
function nebulaGridCenter(f: Frame) {
  return NEBULA_POS.clone().add(f.out.clone().multiplyScalar(9));
}
export function nebulaCards(items: { category: string; subj: Subject }[]): NebulaCard[] {
  const f = nebulaFrame();
  const pts = gridSpots(nebulaGridCenter(f), f, items.length);
  return items.map((it, j) => ({ ...it, pos: pts[j] }));
}
export function nebulaCam(n: number) {
  const f = nebulaFrame();
  return gridCam(nebulaGridCenter(f), f, Math.max(n, 2));
}
export function nebulaSubjectCam(card: NebulaCard) {
  return cardCam(card.pos, nebulaFrame());
}
