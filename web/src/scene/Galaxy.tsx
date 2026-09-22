import { useMemo, useRef, useState, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, Stars, Billboard } from '@react-three/drei';
import * as THREE from 'three';
import { useStore, favKey } from '../store';
import { colorOf } from '../theme/palette';
import type { Subject } from '../lib/archive';
import { useFullTree, useFilteredTree } from '../ui/trees';
import { planetSpots, cardSpots, categoryCam, subjectCam, nebulaCards, nebulaCam, nebulaSubjectCam, nebulaFrame,
  GALAXY_CAM, ORIGIN, NEBULA_POS, type PlanetSpot, type CardSpot, type NebulaCard } from './layout';

// ---------- 공용: 빛무리 스프라이트용 텍스처 (한 번만 만든다) ----------
let haloTex: THREE.Texture | null = null;
function getHalo() {
  if (haloTex) return haloTex;
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d')!;
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,.55)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  haloTex = new THREE.CanvasTexture(c);
  return haloTex;
}

function Halo({ color, scale, opacity = 0.9 }: { color: string; scale: number; opacity?: number }) {
  return (
    <sprite scale={[scale, scale, 1]}>
      <spriteMaterial map={getHalo()} color={color} transparent opacity={opacity}
        blending={THREE.AdditiveBlending} depthWrite={false} />
    </sprite>
  );
}

// ---------- 배경 입자 ----------
function Particles({ count }: { count: number }) {
  const ref = useRef<THREE.Points>(null);
  const [positions, colors] = useMemo(() => {
    const p = new Float32Array(count * 3), c = new Float32Array(count * 3);
    const col = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const r = 22 + Math.random() * 60, a = Math.random() * Math.PI * 2, y = (Math.random() - 0.5) * 40;
      p[i * 3] = Math.cos(a) * r; p[i * 3 + 1] = y; p[i * 3 + 2] = Math.sin(a) * r;
      col.setHSL(0.6 + Math.random() * 0.25, 0.8, 0.65 + Math.random() * 0.3);
      c[i * 3] = col.r; c[i * 3 + 1] = col.g; c[i * 3 + 2] = col.b;
    }
    return [p, c];
  }, [count]);
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += dt * 0.012; });
  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.16} vertexColors transparent opacity={0.8} sizeAttenuation depthWrite={false}
        blending={THREE.AdditiveBlending} map={getHalo()} />
    </points>
  );
}

// ---------- 카메라 ----------
// 마우스 가운데 버튼(휠)을 누른 채 끌면 지금 보고 있는 지점을 중심으로 카메라가 돈다.
// 다른 곳으로 날아가면(행성 들어가기 등) 돌려둔 각도는 0으로 되돌린다.
function CameraRig({ target, look }: { target: THREE.Vector3; look: THREE.Vector3 }) {
  const { camera, pointer, gl } = useThree();
  const curLook = useRef(look.clone());
  const orbit = useRef({ yaw: 0, pitch: 0 });          // 목표 각도
  const orbitNow = useRef({ yaw: 0, pitch: 0 });       // 감쇠된 현재 각도
  const drag = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => { orbit.current = { yaw: 0, pitch: 0 }; }, [target]);

  useEffect(() => {
    const el = gl.domElement;
    const down = (e: PointerEvent) => {
      if (e.button !== 1) return;
      e.preventDefault();                               // 윈도우의 휠 클릭 자동 스크롤 막기
      drag.current = { x: e.clientX, y: e.clientY };
      el.setPointerCapture(e.pointerId);
      document.body.style.cursor = 'grabbing';
    };
    const move = (e: PointerEvent) => {
      if (!drag.current) return;
      const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
      drag.current = { x: e.clientX, y: e.clientY };
      orbit.current.yaw -= dx * 0.005;
      orbit.current.pitch = THREE.MathUtils.clamp(orbit.current.pitch - dy * 0.004, -0.9, 0.9);
    };
    const up = (e: PointerEvent) => {
      if (!drag.current) return;
      drag.current = null;
      try { el.releasePointerCapture(e.pointerId); } catch { /* 이미 풀림 */ }
      document.body.style.cursor = '';
    };
    const block = (e: MouseEvent) => { if (e.button === 1) e.preventDefault(); };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    el.addEventListener('mousedown', block);            // auxclick 자동 스크롤 차단
    el.addEventListener('auxclick', block);
    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      el.removeEventListener('mousedown', block);
      el.removeEventListener('auxclick', block);
    };
  }, [gl]);

  useFrame((_, dt) => {
    const k = 1 - Math.exp(-dt * 3.2);            // 프레임에 안 흔들리는 감쇠
    const ko = 1 - Math.exp(-dt * 8);
    orbitNow.current.yaw += (orbit.current.yaw - orbitNow.current.yaw) * ko;
    orbitNow.current.pitch += (orbit.current.pitch - orbitNow.current.pitch) * ko;

    // 시선점을 중심으로 목표 자리를 회전시킨다 (yaw: 수직축, pitch: 가로축)
    const off = target.clone().sub(look);
    const sph = new THREE.Spherical().setFromVector3(off);
    sph.theta += orbitNow.current.yaw;
    sph.phi = THREE.MathUtils.clamp(sph.phi + orbitNow.current.pitch, 0.15, Math.PI - 0.15);
    const rotated = new THREE.Vector3().setFromSpherical(sph).add(look);

    // 마우스 시차 (드래그 중에는 끈다)
    const par = drag.current ? 0 : 1.2;
    const goal = rotated.add(new THREE.Vector3(pointer.x * par, pointer.y * par * 0.6, 0));
    camera.position.lerp(goal, k);
    curLook.current.lerp(look, k);
    camera.lookAt(curLook.current);
  });
  return null;
}

// ---------- 행성 ----------
function Planet({ spot, lit, dim, onOpen, selected, showLabel }: {
  spot: PlanetSpot; lit: boolean; dim: boolean; selected: boolean; showLabel: boolean; onOpen: () => void;
}) {
  const mesh = useRef<THREE.Mesh>(null);
  const [hover, setHover] = useState(false);
  const col = colorOf(spot.cat.name);
  const born = useRef(0);
  useFrame((_, dt) => {
    if (!mesh.current) return;
    born.current = Math.min(1, born.current + dt * 0.9);
    const s = (hover || selected ? 1.12 : 1) * (1 - Math.pow(1 - born.current, 3));
    mesh.current.scale.setScalar(THREE.MathUtils.lerp(mesh.current.scale.x, s, 0.15));
    mesh.current.rotation.y += dt * 0.25;
  });
  const alpha = dim ? 0.22 : 1;
  const inten = (lit || hover || selected) ? 1.4 : 0.55;
  return (
    <group position={spot.pos}>
      <mesh ref={mesh} onClick={(e) => { e.stopPropagation(); onOpen(); }}
        onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { setHover(false); document.body.style.cursor = ''; }}>
        <icosahedronGeometry args={[spot.radius, 3]} />
        <meshStandardMaterial color={col.deep} emissive={col.main} emissiveIntensity={inten * alpha}
          roughness={0.35} metalness={0.2} transparent opacity={alpha} flatShading />
      </mesh>
      <Halo color={col.main} scale={spot.radius * 5.2} opacity={(hover || lit || selected ? 0.9 : 0.5) * alpha} />
      {/* 고리 */}
      <mesh rotation={[Math.PI / 2.4, 0, 0]}>
        <torusGeometry args={[spot.radius * 1.7, 0.035, 6, 80]} />
        <meshBasicMaterial color={col.glow} transparent opacity={0.5 * alpha} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      {showLabel && (
        <Html position={[0, -spot.radius - 0.9, 0]} center zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
          <div className={'label' + (dim ? ' dim' : '')} style={{ ['--c' as string]: col.main }}>
            <button onClick={onOpen} onFocus={() => setHover(true)} onBlur={() => setHover(false)}
              aria-label={`${spot.cat.name} 분류 열기`}>{spot.cat.name}</button>
          </div>
        </Html>
      )}
    </group>
  );
}

// ---------- 과목 카드 ----------
function SubjectCard({ card, category, lit, dim, selected, onOpen, fav }: {
  card: CardSpot; category: string; lit: boolean; dim: boolean; selected: boolean; fav: boolean; onOpen: () => void;
}) {
  const g = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  const col = colorOf(category);
  const seed = useMemo(() => Math.random() * Math.PI * 2, []);
  const born = useRef(0);
  useFrame(({ clock }, dt) => {
    if (!g.current) return;
    born.current = Math.min(1, born.current + dt * 1.6);
    const e = 1 - Math.pow(1 - born.current, 3);
    g.current.position.y = card.pos.y + Math.sin(clock.elapsedTime * 0.9 + seed) * 0.08;
    const s = (hover || selected ? 1.15 : 1) * e;
    g.current.scale.setScalar(THREE.MathUtils.lerp(g.current.scale.x, s, 0.18));
  });
  const alpha = dim ? 0.2 : 1;
  const active = hover || lit || selected;
  return (
    <group ref={g} position={card.pos} scale={0}>
      <Billboard>
        <mesh onClick={(e) => { e.stopPropagation(); onOpen(); }}
          onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = 'pointer'; }}
          onPointerOut={() => { setHover(false); document.body.style.cursor = ''; }}>
          <planeGeometry args={[3.4, 2]} />
          <meshStandardMaterial color={col.deep} emissive={col.main} emissiveIntensity={(active ? 0.9 : 0.3) * alpha}
            transparent opacity={0.85 * alpha} roughness={0.2} metalness={0.4} side={THREE.DoubleSide} />
        </mesh>
        <mesh position={[0, 0, -0.02]}>
          <planeGeometry args={[3.55, 2.15]} />
          <meshBasicMaterial color={col.glow} transparent opacity={(active ? 0.55 : 0.18) * alpha}
            blending={THREE.AdditiveBlending} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
        {fav && <Halo color="#fbbf24" scale={1.6} opacity={0.9 * alpha} />}
        <Html center zIndexRange={[6, 0]} style={{ pointerEvents: 'none' }}>
          <div className={'label card' + (dim ? ' dim' : '')} style={{ ['--c' as string]: col.main }}>
            <button onClick={onOpen} onFocus={() => setHover(true)} onBlur={() => setHover(false)}
              aria-label={`${card.subj.name} 과목 열기`}>{fav ? '★ ' : ''}{card.subj.name}</button>
            <small>{card.subj.exams.length}개 시험</small>
          </div>
        </Html>
      </Billboard>
    </group>
  );
}

// ---------- 즐겨찾기 위성 (은하 화면에서 카메라 가까이) ----------
// 은하에서 멀리 떨어진 곳에 있는 즐겨찾기 성운. 은하 화면에서는 저 멀리 금빛으로만
// 보이고(클릭하면 날아감), "즐겨찾기만"을 켜면 카메라가 거기로 가서 즐겨찾기한 과목이
// 카드 격자로 펼쳐진다. 카드 색은 각자 원래 분류의 색.
function Nebula({ cards, open, subject, lit, dim, onEnter, onOpen }: {
  cards: NebulaCard[]; open: boolean; subject: string | null;
  lit: (c: string, s: string) => boolean; dim: (c: string, s: string) => boolean;
  onEnter: () => void; onOpen: (c: string, s: string) => void;
}) {
  const g = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  useFrame((_, dt) => { if (g.current) g.current.rotation.y += dt * 0.05; });
  const gold = '#fbbf24';
  // 카드 격자가 놓이는 자리(성운 기준 좌표) - 빈 안내문도 거기에 둔다
  const gridLocal = useMemo(() => nebulaFrame().out.multiplyScalar(9), []);
  return (
    <group position={NEBULA_POS}>
      {/* 성운 본체: 금빛 구름 몇 겹 + 작은 별. 안개를 안 받게 해서 멀리서도 보인다 */}
      <group ref={g}>
        {[[0, 0, 0, 26], [6, 3, -4, 16], [-7, -2, 5, 18], [3, -5, 2, 12]].map(([x, y, z, sc], i) => (
          <sprite key={i} position={[x, y, z]} scale={[sc, sc, 1]}>
            <spriteMaterial map={getHalo()} color={i % 2 ? '#f59e0b' : gold} transparent opacity={open ? 0.25 : 0.55}
              blending={THREE.AdditiveBlending} depthWrite={false} fog={false} />
          </sprite>
        ))}
        <mesh onClick={(e) => { e.stopPropagation(); if (!open) onEnter(); }}
          onPointerOver={() => { if (!open) { setHover(true); document.body.style.cursor = 'pointer'; } }}
          onPointerOut={() => { setHover(false); document.body.style.cursor = ''; }}>
          <sphereGeometry args={[2.2, 24, 24]} />
          {/* 안에 들어가면 가운데 카드 뒤로 비쳐서 거슬리므로 핵은 숨긴다 */}
          <meshBasicMaterial color="#fff7d6" fog={false} transparent opacity={open ? 0 : 1} />
        </mesh>
      </group>
      {!open && (
        <Html position={[0, -4.2, 0]} center zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
          <div className={'label' + (hover ? ' lit' : '')} style={{ ['--c' as string]: gold }}>
            <button onClick={onEnter} aria-label="즐겨찾기 성운으로 이동">★ 즐겨찾기 성운</button>
            <small>{cards.length ? `${cards.length}개 과목` : '아직 비어 있음'}</small>
          </div>
        </Html>
      )}
      {open && cards.length === 0 && (
        <Html position={gridLocal} center zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
          <div className="label" style={{ ['--c' as string]: gold }}>
            <button tabIndex={-1}>즐겨찾기한 과목이 없습니다</button>
            <small>과목 카드나 패널의 ☆를 누르면 여기에 모입니다</small>
          </div>
        </Html>
      )}
      {open && cards.map((c) => (
        <group key={c.category + c.subj.name} position={c.pos.clone().sub(NEBULA_POS)}>
          <SubjectCard card={{ subj: c.subj, pos: new THREE.Vector3(0, 0, 0) }} category={c.category}
            selected={c.subj.name === subject} lit={lit(c.category, c.subj.name)} dim={dim(c.category, c.subj.name)}
            fav onOpen={() => onOpen(c.category, c.subj.name)} />
        </group>
      ))}
    </group>
  );
}

// ---------- 장면 ----------
function Scene() {
  const full = useFullTree();
  const { tree: filtered, active } = useFilteredTree({ ignoreFavOnly: true });
  const category = useStore((s) => s.category);
  const subject = useStore((s) => s.subject);
  const goCategory = useStore((s) => s.goCategory);
  const goSubject = useStore((s) => s.goSubject);
  const favorites = useStore((s) => s.favorites);
  const favOnly = useStore((s) => s.favOnly);
  const setFavOnly = useStore((s) => s.setFavOnly);

  const spots = useMemo(() => planetSpots(full), [full]);
  // 성운에 있는 동안은 행성 안으로 들어가지 않는다 (category는 어느 과목인지 알려주는 용도)
  const spot = (!favOnly && spots.find((p) => p.cat.name === category)) || null;
  const cards = useMemo(() => (spot ? cardSpots(spot) : []), [spot]);
  const card = cards.find((c) => c.subj.name === subject) || null;

  const favItems = useMemo(() => {
    const out: { category: string; subj: Subject }[] = [];
    for (const c of full) for (const sub of c.subjects) if (favorites[favKey(c.name, sub.name)]) out.push({ category: c.name, subj: sub });
    return out;
  }, [full, favorites]);
  const nebCards = useMemo(() => nebulaCards(favItems), [favItems]);
  const nebCard = favOnly ? nebCards.find((c) => c.category === category && c.subj.name === subject) || null : null;

  // 검색·정리필요가 켜져 있을 때 "불 켜진" 것들
  const litCats = useMemo(() => new Set(filtered.map((c) => c.name)), [filtered]);
  const litSubs = useMemo(() => {
    const s = new Set<string>();
    for (const c of filtered) for (const sub of c.subjects) s.add(favKey(c.name, sub.name));
    return s;
  }, [filtered]);

  const cam = useMemo(() => {
    if (favOnly) return nebCard ? nebulaSubjectCam(nebCard) : nebulaCam(nebCards.length);
    if (spot && card) return subjectCam(spot, card);
    if (spot) return categoryCam(spot);
    return { pos: GALAXY_CAM, look: ORIGIN };
  }, [favOnly, nebCard, nebCards.length, spot, card]);

  const litSub = (c: string, sName: string) => active && litSubs.has(favKey(c, sName));
  const dimSub = (c: string, sName: string) => active && !litSubs.has(favKey(c, sName));

  const lowPower = useMemo(() =>
    (navigator.hardwareConcurrency ? navigator.hardwareConcurrency <= 4 : false)
    || window.matchMedia('(pointer: coarse)').matches, []);

  return (
    <>
      <color attach="background" args={['#05060d']} />
      <fog attach="fog" args={['#05060d', 45, 150]} />
      <ambientLight intensity={0.35} />
      <pointLight position={[0, 6, 0]} intensity={90} color="#c7d2fe" distance={80} decay={1.6} />
      <pointLight position={[30, 20, 30]} intensity={40} color="#a5f3fc" distance={120} decay={1.8} />
      <Stars radius={90} depth={40} count={lowPower ? 1500 : 4000} factor={3} saturation={0.4} fade speed={0.4} />
      <Particles count={lowPower ? 600 : 1600} />
      {/* 중심의 태양 — 행성 안에 들어가면 뒤에서 거슬리지 않게 줄인다 */}
      <group scale={category || favOnly ? 0.35 : 1}>
        <mesh><sphereGeometry args={[1.3, 32, 32]} /><meshBasicMaterial color="#e0e7ff" /></mesh>
        <Halo color="#a5b4fc" scale={14} opacity={category || favOnly ? 0.3 : 0.75} />
      </group>
      {spots.map((p) => (
        <Planet key={p.cat.name} spot={p} selected={!favOnly && p.cat.name === category} showLabel={!category && !favOnly}
          lit={!favOnly && active && litCats.has(p.cat.name)}
          dim={favOnly || (active && !litCats.has(p.cat.name)) || (!!category && p.cat.name !== category)}
          onOpen={() => goCategory(p.cat.name)} />
      ))}
      {spot && cards.map((c) => (
        <SubjectCard key={c.subj.name} card={c} category={spot.cat.name} selected={c.subj.name === subject}
          lit={active && litSubs.has(favKey(spot.cat.name, c.subj.name))}
          dim={active && !litSubs.has(favKey(spot.cat.name, c.subj.name))}
          fav={!!favorites[favKey(spot.cat.name, c.subj.name)]}
          onOpen={() => goSubject(spot.cat.name, c.subj.name)} />
      ))}
      <Nebula cards={nebCards} open={favOnly} subject={favOnly ? subject : null} lit={litSub} dim={dimSub}
        onEnter={() => { goCategory(null); setFavOnly(true); }}
        onOpen={(c, sName) => goSubject(c, sName)} />
      <CameraRig target={cam.pos} look={cam.look} />
    </>
  );
}

export function Galaxy() {
  // 빈 곳을 클릭하면 한 단계 나간다
  const goCategory = useStore((s) => s.goCategory);
  const goSubject = useStore((s) => s.goSubject);
  const [dpr, setDpr] = useState<[number, number]>([1, 1.5]);
  useEffect(() => { setDpr([1, Math.min(1.75, window.devicePixelRatio || 1)]); }, []);
  return (
    <div className="scene">
      <Canvas dpr={dpr} camera={{ position: GALAXY_CAM.toArray(), fov: 50, near: 0.1, far: 200 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        onPointerMissed={(e) => {
          // 라벨(DOM 버튼) 클릭도 캔버스 입장에선 "빈 곳"이라 여기로 온다. 그건 뺀다.
          const t = e.target as HTMLElement | null;
          if (t && t.closest && t.closest('.label')) return;
          const st = useStore.getState();
          if (st.subject) goSubject(st.category, null);
          else if (st.favOnly) st.setFavOnly(false);
          else if (st.category) goCategory(null);
        }}>
        <Scene />
      </Canvas>
    </div>
  );
}
