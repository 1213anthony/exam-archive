import { useMemo, useRef, useState, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, Stars, Billboard } from '@react-three/drei';
import * as THREE from 'three';
import { useStore, favKey } from '../store';
import { colorOf } from '../theme/palette';
import type { Category } from '../lib/archive';
import { useFullTree, useFilteredTree } from '../ui/trees';
import { planetSpots, cardSpots, categoryCam, subjectCam, GALAXY_CAM, ORIGIN, type PlanetSpot, type CardSpot } from './layout';

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
function CameraRig({ target, look }: { target: THREE.Vector3; look: THREE.Vector3 }) {
  const { camera, pointer } = useThree();
  const curLook = useRef(look.clone());
  useFrame((_, dt) => {
    const k = 1 - Math.exp(-dt * 2.4);            // 프레임에 안 흔들리는 감쇠
    // 마우스 시차: 갤럭시에서는 크게, 안으로 들어갈수록 작게
    const par = 1.2;
    const goal = target.clone().add(new THREE.Vector3(pointer.x * par, pointer.y * par * 0.6, 0));
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
            <small>{spot.cat.subjects.length}개 과목 · {spot.cat.examCount}개 시험</small>
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
function FavoriteSatellites({ tree, onOpen }: { tree: Category[]; onOpen: (c: string, s: string) => void }) {
  const favorites = useStore((s) => s.favorites);
  const items = useMemo(() => {
    const out: { c: string; s: string; n: number }[] = [];
    for (const c of tree) for (const s of c.subjects) if (favorites[favKey(c.name, s.name)]) out.push({ c: c.name, s: s.name, n: s.exams.length });
    return out;
  }, [tree, favorites]);
  const g = useRef<THREE.Group>(null);
  useFrame((_, dt) => { if (g.current) g.current.rotation.y += dt * 0.06; });
  if (!items.length) return null;
  const m = items.length;
  return (
    <group ref={g} position={[0, 1.5, 12]}>
      {items.map((it, j) => {
        const a = (j / m) * Math.PI * 2, r = 4.5 + Math.min(4, m * 0.25);
        const col = colorOf(it.c);
        return (
          <group key={it.c + it.s} position={[Math.cos(a) * r, Math.sin(a * 3) * 0.5, Math.sin(a) * r * 0.5]}>
            <mesh onClick={(e) => { e.stopPropagation(); onOpen(it.c, it.s); }}
              onPointerOver={() => { document.body.style.cursor = 'pointer'; }} onPointerOut={() => { document.body.style.cursor = ''; }}>
              <sphereGeometry args={[0.32, 16, 16]} />
              <meshStandardMaterial color={col.deep} emissive={col.main} emissiveIntensity={1.6} />
            </mesh>
            <Halo color="#fbbf24" scale={1.8} opacity={0.8} />
            <Html position={[0, -0.7, 0]} center zIndexRange={[7, 0]} style={{ pointerEvents: 'none' }}>
              <div className="label card" style={{ ['--c' as string]: col.main }}>
                <button onClick={() => onOpen(it.c, it.s)} aria-label={`즐겨찾기 ${it.s} 열기`}>★ {it.s}</button>
                <small>{it.c} · {it.n}개 시험</small>
              </div>
            </Html>
          </group>
        );
      })}
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

  const spots = useMemo(() => planetSpots(full), [full]);
  const spot = spots.find((p) => p.cat.name === category) || null;
  const cards = useMemo(() => (spot ? cardSpots(spot) : []), [spot]);
  const card = cards.find((c) => c.subj.name === subject) || null;

  // 검색·정리필요가 켜져 있을 때 "불 켜진" 것들
  const litCats = useMemo(() => new Set(filtered.map((c) => c.name)), [filtered]);
  const litSubs = useMemo(() => {
    const s = new Set<string>();
    for (const c of filtered) for (const sub of c.subjects) s.add(favKey(c.name, sub.name));
    return s;
  }, [filtered]);

  const cam = useMemo(() => {
    if (spot && card) return subjectCam(spot, card);
    if (spot) return categoryCam(spot);
    return { pos: GALAXY_CAM, look: ORIGIN };
  }, [spot, card]);

  const lowPower = useMemo(() => navigator.hardwareConcurrency ? navigator.hardwareConcurrency <= 4 : false, []);

  return (
    <>
      <color attach="background" args={['#05060d']} />
      <fog attach="fog" args={['#05060d', 45, 110]} />
      <ambientLight intensity={0.35} />
      <pointLight position={[0, 6, 0]} intensity={90} color="#c7d2fe" distance={80} decay={1.6} />
      <pointLight position={[30, 20, 30]} intensity={40} color="#a5f3fc" distance={120} decay={1.8} />
      <Stars radius={90} depth={40} count={lowPower ? 1500 : 4000} factor={3} saturation={0.4} fade speed={0.4} />
      <Particles count={lowPower ? 600 : 1600} />
      {/* 중심의 태양 — 행성 안에 들어가면 뒤에서 거슬리지 않게 줄인다 */}
      <group scale={category ? 0.35 : 1}>
        <mesh><sphereGeometry args={[1.3, 32, 32]} /><meshBasicMaterial color="#e0e7ff" /></mesh>
        <Halo color="#a5b4fc" scale={14} opacity={category ? 0.3 : 0.75} />
      </group>
      {spots.map((p) => (
        <Planet key={p.cat.name} spot={p} selected={p.cat.name === category} showLabel={!category}
          lit={active && litCats.has(p.cat.name)} dim={(active && !litCats.has(p.cat.name)) || (!!category && p.cat.name !== category)}
          onOpen={() => goCategory(p.cat.name)} />
      ))}
      {spot && cards.map((c) => (
        <SubjectCard key={c.subj.name} card={c} category={spot.cat.name} selected={c.subj.name === subject}
          lit={active && litSubs.has(favKey(spot.cat.name, c.subj.name))}
          dim={active && !litSubs.has(favKey(spot.cat.name, c.subj.name))}
          fav={!!favorites[favKey(spot.cat.name, c.subj.name)]}
          onOpen={() => goSubject(spot.cat.name, c.subj.name)} />
      ))}
      {!category && <FavoriteSatellites tree={full} onOpen={(c, s) => goSubject(c, s)} />}
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
          else if (st.category) goCategory(null);
        }}>
        <Scene />
      </Canvas>
    </div>
  );
}
