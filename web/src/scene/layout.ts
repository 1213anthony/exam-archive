import * as THREE from 'three';
import type { Category, Subject } from '../lib/archive';

// 3D 공간에서 행성·카드가 놓이는 자리. 한 곳에서 계산해 카메라와 렌더가 같은 값을 쓴다.
export const GALAXY_CAM = new THREE.Vector3(0, 24, 52);
export const ORIGIN = new THREE.Vector3(0, 0, 0);

export interface PlanetSpot { cat: Category; pos: THREE.Vector3; radius: number; hue: number }

export function planetSpots(tree: Category[]): PlanetSpot[] {
  const n = tree.length || 1;
  return tree.map((cat, i) => {
    // 12개를 두 겹 고리(안 6 · 밖 6)에 번갈아 놓고, 바깥 고리는 반 칸 돌려서
    // 서로의 사이에 오게 한다. 라벨이 겹치지 않을 만큼 벌린다.
    const outer = i % 2 === 1;
    const a = (i / n) * Math.PI * 2 - Math.PI / 2 + (outer ? Math.PI / n : 0);
    const ring = outer ? 27 : 16;
    const pos = new THREE.Vector3(Math.cos(a) * ring, Math.sin(a * 2) * 2.2 + (outer ? 1.5 : -1), Math.sin(a) * ring * 0.8);
    const radius = 0.9 + Math.sqrt(cat.examCount) / 9;   // 시험 수에 비례 (1.1 ~ 2.9)
    return { cat, pos, radius, hue: i / n };
  });
}

export interface CardSpot { subj: Subject; pos: THREE.Vector3 }

/** 행성 기준 좌표계: out=원점에서 바깥(카메라가 있는 쪽), right=화면 오른쪽, up */
function frame(spot: PlanetSpot) {
  const out = new THREE.Vector3(spot.pos.x, 0, spot.pos.z).normalize();
  const up = new THREE.Vector3(0, 1, 0);
  const right = new THREE.Vector3().crossVectors(up, out).normalize();
  return { out, up, right };
}

const CARD_W = 3.9, CARD_H = 2.45;

/** 과목 카드는 행성 앞에 격자로 펼친다(카메라를 정면으로 본다). 행성은 뒤에서 배경처럼 빛난다. */
export function cardSpots(spot: PlanetSpot): CardSpot[] {
  const subs = spot.cat.subjects;
  const m = subs.length;
  const cols = Math.max(1, Math.min(6, Math.ceil(Math.sqrt(m * 1.7))));
  const rows = Math.ceil(m / cols);
  const { out, up, right } = frame(spot);
  const center = spot.pos.clone().add(out.clone().multiplyScalar(spot.radius + 7));
  return subs.map((subj, j) => {
    const c = j % cols, r = Math.floor(j / cols);
    const x = (c - (cols - 1) / 2) * CARD_W;
    const y = ((rows - 1) / 2 - r) * CARD_H + 0.6;
    const pos = center.clone().add(right.clone().multiplyScalar(x)).add(up.clone().multiplyScalar(y));
    return { subj, pos };
  });
}

/** 행성에 들어갔을 때 카메라 자리 — 격자 정면, 격자 크기에 맞춰 물러선다 */
export function categoryCam(spot: PlanetSpot): { pos: THREE.Vector3; look: THREE.Vector3 } {
  const m = spot.cat.subjects.length;
  const cols = Math.max(1, Math.min(6, Math.ceil(Math.sqrt(m * 1.7))));
  const rows = Math.ceil(m / cols);
  const { out, up } = frame(spot);
  const center = spot.pos.clone().add(out.clone().multiplyScalar(spot.radius + 7)).add(up.clone().multiplyScalar(0.6));
  const dist = 9 + Math.max(cols * CARD_W, rows * CARD_H * 1.6) * 0.62;
  const pos = center.clone().add(out.clone().multiplyScalar(dist)).add(up.clone().multiplyScalar(1.2));
  return { pos, look: center };
}

/** 카드 앞에 멈추는 카메라 자리. 오른쪽에 패널이 뜨므로 카드가 화면 왼쪽으로 오게 시선을 튼다 */
export function subjectCam(spot: PlanetSpot, card: CardSpot): { pos: THREE.Vector3; look: THREE.Vector3 } {
  const { out, up, right } = frame(spot);
  // 카메라는 -out 방향을 본다. 화면 오른쪽 = cross(전방, up) = cross(-out, up) = cross(up, out) = right
  const screenRight = right.clone();
  const pos = card.pos.clone().add(out.clone().multiplyScalar(10.5)).add(up.clone().multiplyScalar(0.4))
    .add(screenRight.clone().multiplyScalar(3.4));
  const look = card.pos.clone().add(screenRight.clone().multiplyScalar(3.4));
  return { pos, look };
}
