# 기출문제 아카이브 — 3D UI 전면 재구축 프롬프트

아래 내용을 그대로 Claude Code에 붙여넣어 실행한다.

---

너는 `C:\Users\son\Desktop\files` 프로젝트(GitHub: `1213anthony/exam-archive`, 배포: https://1213anthony.github.io/exam-archive/)의 프론트엔드를 **WebGL 3D 기반의 화려한 UI로 전면 재구축**한다. 기존 기능은 하나도 잃지 않으면서, 시험지 아카이브를 "3D 공간에 떠 있는 도서관"으로 다시 만든다.

## 0. 이미 결정된 사항 (인터뷰 결과 — 다시 묻지 말 것)

| 항목 | 결정 |
|---|---|
| 작업 범위 | 메인 아카이브 화면 **+** 관리(정리/삭제) 화면 둘 다 |
| 톤 | 화려하고 입체적이며 역동적인 움직임과 색상 |
| 시각 방향 | **WebGL 3D 공간** (Three.js). 과목이 3D 공간에 떠 있고 클릭하면 날아 들어감. 검색 UX는 별도 HUD 패널 |
| 기술 | React 등 자유. 단 결과물은 GitHub Pages에 올라가는 **정적 파일** |
| 삭제/정리 기능 사용자 | **일단 나(사이트 주인)만** — 로그인 필요 |
| 기기 우선순위 | **PC 우선.** 폰에서는 무거운 3D·입자 효과를 자동으로 끄고 레이아웃만 맞춘다 |

## 1. 지금 프로젝트 상태 (반드시 읽고 시작)

- `index.html` — 현재 배포 중인 단일 파일 사이트. 무채색 리스트 UI. **여기 들어 있는 데이터 가공 로직이 핵심 자산**이다(아래 3절). 재구축 후에도 `/classic/`으로 그대로 남긴다.
- `data.js` — `var EXAM_DATA_VERSION = "..."; var EXAM_DATA = [...]`. **13,538개** 파일 기록, 필드는 정확히 이 14개:
  `id, filename, category, subject, subject_detail, year, semester, examtype, doctype, parsed_ok, folder_mismatch, duplicate_sibling_folder, size, md5`
  (값이 null인 필드는 아예 빠져 있음. 드라이브 URL은 `https://drive.google.com/file/d/{id}/view`로 id에서 만든다.)
- `crawl.py` / `reprocess.py` — 드라이브 크롤링·파싱 파이프라인. **손대지 않는다.** 프론트는 이들이 만드는 `data.js`를 소비만 한다.
- `robots.txt` + `<meta name="robots" content="noindex, nofollow, noarchive">` — 학교 내부 자료라 검색엔진 차단. **유지한다.**
- 분류 12개, 순서 고정: `국어, 수학, 물리, 화학, 생명과학, 지구과학, 정보, 사회, 외국어, 실험, 예체능, 창의융합특강`
- 현재 화면 기준 수치: **시험 1,877줄 / 과목 102개 / 문제·해설 한쪽이 없는 시험 19개 / 연도 미상 0개.** 재구축 후에도 이 숫자가 그대로 나와야 한다(회귀 테스트 기준).
- 드라이브 파일들은 `24031@sshs.hs.kr` 같은 **학생 계정 소유**라, 사이트 주인 계정으로는 지울 권한이 없다. 삭제 기능은 "파일 소유자로 로그인했을 때만 동작"하는 구조로 만들고, 권한이 없으면 그 이유를 화면에 정직하게 보여준다.

## 2. 목표 경험 (이걸 만든다)

**"미래형 도서관 / 은하계"**
1. 첫 화면: 어두운 우주 공간. 12개 분류가 **행성(또는 서가 클러스터)**로 떠 있고 느리게 자전·공전한다. 각 행성 크기는 시험 수에 비례. 배경엔 흐르는 빛 입자, 마우스를 따라 시차(parallax)가 걸린다.
2. 행성에 마우스를 올리면 이름·과목 수·시험 수가 홀로그램 라벨로 뜨고, **클릭하면 카메라가 날아 들어가** 그 분류의 과목들이 **떠 있는 유리 카드**로 궤도를 돌며 펼쳐진다.
3. 과목 카드를 클릭하면 카메라가 그 카드 앞에 멈추고, 화면 오른쪽에 **유리질감 HUD 패널**이 슬라이드해 들어와 시험 목록(최근 순)이 뜬다. 각 줄에 `문제` / `해설` 버튼과 체크박스. 이 패널이 실제 작업 공간이다.
4. 상단 HUD 검색창(`/` 키로 포커스): 입력하면 3D 공간의 해당 과목/행성이 **밝게 점등**하고 나머지는 어두워진다. Enter로 첫 결과로 비행.
5. 즐겨찾기(★)한 과목은 첫 화면에서 **위성처럼 카메라 가까이** 모여 있어서 바로 클릭 가능.
6. 우상단 토글 **`3D` / `목록`**: 목록 모드는 현재 `index.html`과 같은 깔끔한 2D 리스트(React로 재구현). 폰·저사양·`prefers-reduced-motion`에서는 **자동으로 목록 모드**.
7. 전환·비행·패널 등장은 전부 부드러운 애니메이션(스프링/이징). 색은 분류마다 고유한 네온 팔레트(국어=주홍, 수학=청록, 물리=보라 …)를 정해 행성·카드·버튼에 일관되게 쓴다.

## 3. 반드시 이식해야 하는 기존 로직 (index.html에서 그대로 옮긴다 — 의미를 바꾸지 말 것)

읽으면서 TypeScript 모듈 `src/lib/archive.ts`로 옮기고, 각 함수에 단위 테스트를 붙인다.

- `examKey(r)` = `subject|year|semester|examtype` — 한 시험의 키
- `isProblem(doctype)` = "문제" 포함 / `isSolution(doctype)` = "답안"·"해설"·"정답" 중 하나 포함
- `contentKey` / `dedupeRecords` — md5가 같으면(없으면 파일명+size) 같은 파일로 보고 한 번만
- `pickBest(list)` — 같은 문서유형이 여러 벌이면 **용량이 가장 큰 것 하나만** 화면에 (나머지는 아예 렌더하지 않음, `+N` 같은 접기 버튼 금지)
- `clusterGroup(group)` — 파일명 속 세부과목(`subject_detail`)으로 한 시험 줄을 소그룹으로 나눔. 규칙: `normDetail`(로마숫자→아라비아, 괄호·구두점 제거, 문서유형 접두사 제거), `detailGrade`("2학년/3학년"은 **다른 시험지**라 절대 합치지 않음), `sameSubject`(끝 번호가 둘 다 있고 다르면 다른 과목, 한쪽만 없으면 같은 과목; 부분수열/편집거리1 허용), 2차 패스(학년·과목 표기가 없는 그룹은 붙일 곳이 하나로 특정될 때만 붙임)
- `examOrder(semester, examtype)` — 정렬: 연도 내림차순, 같은 해 안에서는 **나중에 본 것부터** (1중간<1기말<2중간<2기말<겨울 계절수업)
- `incompleteExams()` — "정리 필요" = 위 클러스터링까지 적용한 뒤 **문제지나 해설 한쪽이 없는 시험만**
- localStorage 키를 **그대로** 써서 기존 사용자의 즐겨찾기가 유지되게: `examArchive.favorites.v1`, `examArchive.favOnly.v1`, `examArchive.reviewed.v1`, `examArchive.hidden.v1`, `archive.catclosed`
- 다중 다운로드: 체크한 파일들을 숨김 iframe으로 순차 열기(팝업 차단 회피). 현재 구현을 참고.
- 상태줄: `"1877개 시험 · 파일 13538개 · 데이터 {EXAM_DATA_VERSION}"` 형식 유지
- 분류가 하나 이상 접혀 있어도 **검색 중이거나 "정리 필요만"일 때는 항상 펼쳐서** 결과가 숨지 않게 (3D 모드에서는 "점등"으로 같은 의미를 구현)

## 4. 관리(정리/삭제) 화면 — 로그인한 나만

- 화면 어디에도 **로그인 전에는 삭제 관련 UI가 보이지 않는다.** 우하단 작은 자물쇠 아이콘 하나만.
- 로그인은 **Google Identity Services(브라우저 OAuth)**, 스코프 `https://www.googleapis.com/auth/drive`. 서버 없이 브라우저→Drive API 직접 호출. 클라이언트 ID는 `.env`에서 주입하고 리포에 커밋하지 않는다.
- **허용 이메일 목록**(`ALLOWED_ADMINS`)에 있는 계정으로 로그인했을 때만 관리 모드 진입. 목록은 빌드 시 주입.
- 관리 모드에서 할 수 있는 것:
  1. 시험 줄에서 파일 옆 `×` → **휴지통으로 이동**(`files.update {trashed:true}`, 완전 삭제 금지). 실행 전에 파일명·개수 확인 모달, "삭제"라고 타이핑해야 진행.
  2. 실행 결과를 화면 하단 로그 패널에 남기고 `trash_log.json`을 다운로드할 수 있게(되돌리기용).
  3. 각 파일의 `capabilities.canTrash`를 먼저 조회해서 **권한 없는 파일은 버튼을 비활성화하고 소유자 이메일을 표시** ("이 파일은 25072@sshs.hs.kr 소유 — 그 계정으로 로그인해야 지울 수 있음").
  4. "정리 필요" 시험에 **확인함** 표시(기존 `reviewed` 기능)와 메모 한 줄.
- 관리 기능은 별도 청크로 코드 스플리팅해서 일반 사용자는 내려받지 않게.

## 5. 기술 스택과 구조

- **Vite + React 18 + TypeScript**, 3D는 **three + @react-three/fiber + @react-three/drei**, 애니메이션은 **framer-motion**(2D)과 r3f의 스프링(3D), 상태는 **zustand**, 테스트는 **vitest**.
- 디렉터리:
  ```
  src/
    lib/archive.ts        ← 3절 로직 (순수 함수, 테스트 100% 커버)
    lib/archive.test.ts
    data/                 ← data.js를 ESM으로 감싸는 로더 (전역 EXAM_DATA를 읽는 얇은 어댑터)
    scene/                ← Galaxy, Planet, SubjectCard, CameraRig, Particles
    ui/                   ← Hud, SearchBar, ExamPanel, ClassicList, SelectionBar
    admin/                ← GoogleAuth, TrashDialog, AdminPanel (lazy)
    theme/palette.ts      ← 분류별 색
  public/robots.txt, public/classic/index.html (기존 파일 복사)
  ```
- `data.js`는 빌드에 포함하지 말고 **런타임에 `<script src="data.js">`로 로드**한다(크롤링만 다시 돌리면 프론트 재빌드 없이 갱신되게). 5MB라 첫 로드 동안 3D 로딩 화면(행성이 형성되는 애니메이션)을 보여준다.
- 성능 기준: PC 내장 GPU에서 60fps. 과목 카드 102개는 **InstancedMesh**, 입자는 Points 하나. 프레임 예산 초과 시 자동으로 입자 수를 줄인다. 폰(`pointer: coarse` 또는 GPU 티어 낮음)과 `prefers-reduced-motion`에서는 3D를 마운트하지 않고 목록 모드.
- 접근성: 3D 모드에서도 키보드로 모든 것을 할 수 있어야 한다(Tab으로 행성/카드 이동, Enter 진입, Esc 나가기, `/` 검색). 포커스된 요소는 3D에서도 링을 그린다.
- 배포: GitHub Actions로 `main` push 시 빌드 → `gh-pages` 브랜치. **URL은 지금과 동일**해야 한다. `base: '/exam-archive/'`.

## 6. 작업 순서 (단계마다 커밋. 한 번에 다 만들지 말 것)

1. **뼈대**: Vite 프로젝트 생성, 기존 `index.html`을 `public/classic/`으로 복사, Actions 배포까지 먼저 붙여서 빈 페이지가 같은 URL에 뜨는 것을 확인.
2. **데이터 계층**: `archive.ts`로 3절 로직 이식 + 테스트. 테스트에 **"시험 1877 / 과목 102 / 정리 필요 19 / 연도 미상 0"** 을 상수로 박아 회귀를 잡는다.
3. **목록 모드**(2D): 기존 UI와 기능 동등. 여기까지가 폰·저사양의 최종 화면이므로 완성도 있게.
4. **3D 은하**: Galaxy → Planet → SubjectCard → CameraRig 순. 먼저 클릭·비행·패널 연결(기능)을 만들고, 그다음 입자·글로우·시차 같은 장식.
5. **HUD 검색·즐겨찾기·선택 다운로드**를 3D 모드에 연결.
6. **관리 모드**(4절). `.env.example`에 필요한 키 이름을 적어둔다.
7. **마무리**: Lighthouse 성능·접근성 90+ , 폰 실기 확인, `README.md` 갱신(실행법, 데이터 갱신법, 관리자 추가법).

## 7. 하지 말 것

- 데이터 의미를 바꾸는 일(과목 이름, 시험 키, 정렬 규칙, 정리 필요 기준). 바꾸고 싶으면 먼저 물어볼 것.
- `crawl.py`, `reprocess.py`, `data.js` 생성 방식 변경.
- 같은 시험의 여러 판본을 `+N`처럼 접어서 보여주기. **한 장만.**
- 삭제 기능을 로그인 없이 노출하거나, 완전 삭제(`files.delete`) 사용.
- 검색엔진 차단 메타/robots 제거.
- 외부 폰트·라이브러리를 CDN 런타임 로드로 두기(전부 번들에 포함. 오프라인 교실에서도 열리게).

## 8. 완료 기준

- [ ] https://1213anthony.github.io/exam-archive/ 에서 3D 첫 화면이 뜨고, 행성 클릭 → 과목 카드 → 시험 패널 → `문제`/`해설` 열기까지 마우스만으로 된다
- [ ] 같은 흐름을 키보드만으로도 할 수 있다
- [ ] `목록` 토글과 폰에서 기존과 같은 2D 화면이 나오고, 즐겨찾기·검색·정리 필요·체크박스 다운로드가 전부 동작한다
- [ ] 테스트: 시험 1877 / 과목 102 / 정리 필요 19 / 연도 미상 0 통과
- [ ] 로그인 전에는 삭제 UI가 어디에도 없고, 허용 계정으로 로그인하면 관리 모드가 켜지며, 권한 없는 파일은 소유자를 보여주고 버튼이 비활성화된다
- [ ] `/classic/`에 예전 페이지가 그대로 살아 있다
- [ ] PC 내장 GPU 60fps, Lighthouse 성능·접근성 90 이상
