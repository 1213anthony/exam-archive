"""
정리 필요 항목 리뷰 리포트 생성기
==============================
data.json을 읽어서 review.html을 만든다. 실제 드라이브를 고치는 건 아니고,
사람이 보고 판단할 수 있게 목록만 정리한다 (drive.readonly 권한이라 쓰기는
못 함).
"""
import html
import json
from collections import defaultdict

with open("data.json", encoding="utf-8") as f:
    DATA = json.load(f)


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def fmt_dt(iso):
    if not iso:
        return "-"
    return iso.replace("T", " ").split(".")[0].replace("Z", "")


def folder_link(folder_id):
    return f"https://drive.google.com/drive/folders/{folder_id}"


# ---- 1) 중복 폴더: duplicate_folder_id로 인스턴스를 구분해서 페어링 ----
# 실제로 몇 개 표본(과학사 등)을 다운받아 MD5까지 대조해본 결과 완전히 동일한
# 파일이었던 걸 확인함 - 그래서 다운로드 없이도 신뢰할 수 있는 대용 신호로
# (연도,학기,시험종류,문서유형)이 같은 항목끼리 파일 크기(size)까지 일치하는지를
# 비교해서 "거의 확실한 중복"과 "한쪽에만 있는 고유 콘텐츠"를 자동으로 구분한다.
by_instance = defaultdict(list)
for r in DATA:
    fid = r.get("duplicate_folder_id")
    if fid:
        by_instance[fid].append(r)

def common_prefix(paths):
    """인스턴스 안 모든 파일 경로의 공통 앞부분 = 중복으로 잡힌 그 폴더의 경로.
    (예전엔 '가장 짧은 경로'를 썼는데, 인스턴스마다 하위 폴더 구성이 달라서
    같은 쌍인데도 서로 다른 경로로 잡혀 그룹에서 통째로 빠지는 버그가 있었음 -
    실제로 물리/고급물리학1 쌍 72개 파일이 리포트에서 누락됐었다.)"""
    if not paths:
        return ()
    out = []
    for parts in zip(*paths):
        if len(set(parts)) == 1:
            out.append(parts[0])
        else:
            break
    return tuple(out)


instance_summaries = []
for fid, recs in by_instance.items():
    shortest_path = common_prefix([r["folder_path"] for r in recs])
    latest_file_mod = max(
        (r.get("modified_time") for r in recs if r.get("modified_time")), default=None
    )
    keyed = defaultdict(list)
    for r in recs:
        k = (r.get("year"), r.get("semester"), r.get("examtype"), r.get("doctype"))
        keyed[k].append(r.get("size"))
    instance_summaries.append(
        {
            "folder_id": fid,
            "path": tuple(shortest_path),
            "file_count": len(recs),
            "latest_file_modified": latest_file_mod,
            "keyed": keyed,
        }
    )

dup_groups = defaultdict(list)
for s in instance_summaries:
    dup_groups[s["path"]].append(s)
dup_groups = {k: v for k, v in dup_groups.items() if len(v) >= 2}


def compare_instances(a, b):
    common = set(a["keyed"]) & set(b["keyed"])
    size_match = sum(
        1 for k in common if set(a["keyed"][k]) & set(b["keyed"][k])
    )
    size_diff = len(common) - size_match
    only_a = len(set(a["keyed"]) - set(b["keyed"]))
    only_b = len(set(b["keyed"]) - set(a["keyed"]))
    return size_match, size_diff, only_a, only_b


dup_html_parts = []
for path, insts in sorted(dup_groups.items()):
    insts_sorted = sorted(insts, key=lambda x: x["latest_file_modified"] or "", reverse=True)
    path_label = " / ".join(path)
    cards = []
    for i, inst in enumerate(insts_sorted):
        tag = "최신" if i == 0 else ""
        cards.append(f"""
        <div class="dupcard">
          <div class="dupcard-head">인스턴스 {i+1} {'<span class="tag">' + tag + '</span>' if tag else ''}</div>
          <div class="dupcard-body">
            <div>파일 {inst['file_count']}개</div>
            <div>최근 수정 {esc(fmt_dt(inst['latest_file_modified']))}</div>
            <a class="btn" href="{esc(folder_link(inst['folder_id']))}" target="_blank" rel="noopener">드라이브에서 열기</a>
          </div>
        </div>""")

    verdict_html = ""
    if len(insts_sorted) >= 2:
        size_match, size_diff, only_a, only_b = compare_instances(insts_sorted[0], insts_sorted[1])
        total_common = size_match + size_diff
        if only_a == 0 and only_b == 0 and size_diff == 0 and total_common > 0:
            verdict = f"완전 중복 - 두 폴더 내용이 100% 동일함(파일 크기까지 {total_common}건 전부 일치). 하나는 안전하게 지워도 됨"
            vclass = "verdict-dup"
        elif total_common and size_match / total_common >= 0.8:
            verdict = (
                f"거의 중복 - 같은 시험 {total_common}건 중 {size_match}건은 크기까지 일치(사실상 동일 파일). "
                + (f"한쪽에만 있는 시험 {only_a + only_b}건은 확인 후 병합 추천" if (only_a or only_b) else "")
            )
            vclass = "verdict-mostly"
        else:
            verdict = f"부분 중복 - 크기까지 일치하는 건 {size_match}/{total_common}건뿐, 한쪽에만 있는 시험도 {only_a + only_b}건 있음. 직접 확인 필요"
            vclass = "verdict-partial"
        verdict_html = f'<div class="verdict {vclass}">{esc(verdict)}</div>'

    dup_html_parts.append(f"""
    <div class="group">
      <div class="group-title">{esc(path_label)}</div>
      {verdict_html}
      <div class="dupcards">{''.join(cards)}</div>
    </div>""")

dup_section = "\n".join(dup_html_parts)
dup_total_files = sum(1 for r in DATA if r.get("duplicate_sibling_folder"))

# ---- 2) 폴더 불일치 (examtype 기준) ----
mismatch = [r for r in DATA if r["folder_mismatch"]]
mismatch.sort(key=lambda r: (r["category"] or "", r["subject"] or ""))
mismatch_rows = []
for r in mismatch:
    mismatch_rows.append(f"""
    <tr>
      <td>{esc(r['category'])} / {esc(r['subject'])}</td>
      <td>{esc(' / '.join(r['folder_path']))}</td>
      <td>{esc(r['filename'])}</td>
      <td>폴더: {esc(r.get('doctype'))} 파일명 시험종류 불일치</td>
      <td><a href="{esc(r['url'])}" target="_blank" rel="noopener">열기</a></td>
    </tr>""")
mismatch_section = "\n".join(mismatch_rows)

# ---- 3) 파싱 실패 ----
unparsed = [r for r in DATA if not r["parsed_ok"]]
unparsed.sort(key=lambda r: (r["category"] or "", r["subject"] or ""))
unparsed_rows = []
for r in unparsed:
    unparsed_rows.append(f"""
    <tr>
      <td>{esc(r['category'])} / {esc(r['subject'])}</td>
      <td>{esc(r['filename'])}</td>
      <td>{esc(r.get('year') or '연도 미상')}</td>
      <td>{esc(r.get('doctype') or '문서유형 미상')}</td>
      <td><a href="{esc(r['url'])}" target="_blank" rel="noopener">열기</a></td>
    </tr>""")
unparsed_section = "\n".join(unparsed_rows)

# ---- 4) 비정상적으로 작은 파일 (<20KB) ----
tiny = [r for r in DATA if r.get("size") and r["size"] < 20000]
tiny.sort(key=lambda r: r["size"])
tiny_rows = []
for r in tiny:
    tiny_rows.append(f"""
    <tr>
      <td>{esc(r['category'])} / {esc(r['subject'])}</td>
      <td>{esc(r['filename'])}</td>
      <td>{r['size']:,} bytes</td>
      <td><a href="{esc(r['url'])}" target="_blank" rel="noopener">열기</a></td>
    </tr>""")
tiny_section = "\n".join(tiny_rows)

HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>정리 필요 리뷰</title>
<style>
  :root {{
    /* index.html과 같은 무채색 + 청회색 포인트 하나 */
    --paper: #FAFAFA; --card: #FFFFFF; --line: #E0E0E0; --line-soft: #EEEEEE;
    --ink: #1B1B1B; --ink-mid: #5C5C5C; --ink-soft: #979797;
    --green: #35566E; --green-soft: #F4F6F7; --blue: #35566E; --blue-soft: #EDF1F4;
    --red: #6B6B6B; --red-soft: #F0F0F0;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif; font-size:14.5px; line-height:1.55; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:36px 20px 100px; }}
  h1 {{ font-family:Georgia,"Nanum Myeongjo",serif; font-size:26px; margin:0 0 6px; }}
  .sub {{ color:var(--ink-soft); font-size:13px; margin:0 0 30px; }}
  nav {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:30px; }}
  nav a {{ font-size:13px; padding:7px 13px; border:1px solid var(--line); border-radius:999px; background:var(--card); color:var(--ink-mid); text-decoration:none; }}
  section {{ margin-bottom:52px; }}
  h2 {{ font-size:19px; border-bottom:2px solid var(--ink); padding-bottom:10px; margin:0 0 6px; }}
  h2 .cnt {{ color:var(--ink-soft); font-weight:400; font-size:14px; }}
  .desc {{ color:var(--ink-mid); font-size:13px; margin:8px 0 20px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line-soft); font-size:13px; vertical-align:top; }}
  th {{ color:var(--ink-soft); font-weight:600; font-size:12px; }}
  a {{ color:var(--blue); }}
  .group {{ margin-bottom:22px; padding:14px 16px; background:var(--card); border:1px solid var(--line-soft); border-radius:6px; }}
  .group-title {{ font-weight:600; margin-bottom:10px; font-size:13.5px; }}
  .verdict {{ font-size:12.5px; padding:8px 10px; border-radius:4px; margin-bottom:10px; }}
  .verdict-dup {{ background:var(--red-soft); color:var(--red); }}
  .verdict-mostly {{ background:var(--green-soft); color:var(--green); }}
  .verdict-partial {{ background:var(--line-soft); color:var(--ink-mid); }}
  .dupcards {{ display:flex; gap:12px; flex-wrap:wrap; }}
  .dupcard {{ flex:1; min-width:200px; border:1px solid var(--line); border-radius:5px; padding:10px 12px; }}
  .dupcard-head {{ font-size:12.5px; color:var(--ink-soft); margin-bottom:6px; }}
  .tag {{ background:var(--green-soft); color:var(--green); font-size:10.5px; padding:1px 6px; border-radius:3px; margin-left:4px; }}
  .dupcard-body div {{ margin-bottom:4px; font-size:13px; }}
  .btn {{ display:inline-block; margin-top:6px; font-size:12px; padding:5px 10px; border:1px solid var(--blue); border-radius:4px; background:var(--blue-soft); color:var(--blue); text-decoration:none; }}
  .empty {{ color:var(--ink-soft); padding:20px 0; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>정리 필요 리뷰</h1>
  <p class="sub">data.json 기준 자동 생성 — 실제 드라이브 수정은 못 하니(읽기 전용) 여기서 확인하고 드라이브에서 직접 정리하는 용도.</p>
  <nav>
    <a href="#dup">동명 폴더 ({len(dup_groups)}쌍)</a>
    <a href="#mismatch">폴더 불일치 ({len(mismatch)}개)</a>
    <a href="#unparsed">파싱 실패 ({len(unparsed)}개)</a>
    <a href="#tiny">비정상 작은 파일 ({len(tiny)}개)</a>
  </nav>

  <section id="dup">
    <h2>동명 폴더 <span class="cnt">{len(dup_groups)}쌍 · {dup_total_files}개 파일</span></h2>
    <p class="desc">같은 이름의 형제 폴더가 2개 이상 있는 경우. 표본을 실제로 다운받아 MD5까지 대조해보니
    완전 동일한 파일이었음 — 그래서 (연도·학기·시험종류·문서유형)이 같은 항목끼리 파일 크기까지
    일치하는지 자동으로 비교해서 아래에 판정을 달아뒀음: <b>완전 중복</b>(안전하게 하나 삭제 가능),
    <b>거의 중복</b>(대부분 동일, 한쪽에만 있는 소수만 확인), <b>부분 중복</b>(직접 확인 필요).
    그래도 100% 확신은 아니니 지우기 전에 링크로 한 번 열어보길 권함.</p>
    {dup_section if dup_section else '<p class="empty">없음</p>'}
  </section>

  <section id="mismatch">
    <h2>폴더 불일치 <span class="cnt">{len(mismatch)}개</span></h2>
    <p class="desc">폴더명이 말하는 시험종류(중간/기말)와 파일명에 적힌 시험종류가 다름 — 잘못된 폴더로 옮겨진 파일 후보.</p>
    <table>
      <thead><tr><th>과목</th><th>현재 폴더 경로</th><th>파일명</th><th>비고</th><th></th></tr></thead>
      <tbody>{mismatch_section if mismatch_section else '<tr><td colspan="5" class="empty">없음</td></tr>'}</tbody>
    </table>
  </section>

  <section id="unparsed">
    <h2>파싱 실패 <span class="cnt">{len(unparsed)}개</span></h2>
    <p class="desc">파일명이 알려진 패턴에 안 맞음 — 자모 깨짐, 옛날 방식, 오타 등. year/doctype은 최선을 다한 추정치(fallback)이고 못 찾으면 미상으로 표시.</p>
    <table>
      <thead><tr><th>과목</th><th>파일명</th><th>추정 연도</th><th>추정 문서유형</th><th></th></tr></thead>
      <tbody>{unparsed_section if unparsed_section else '<tr><td colspan="5" class="empty">없음</td></tr>'}</tbody>
    </table>
  </section>

  <section id="tiny">
    <h2>비정상적으로 작은 파일 <span class="cnt">{len(tiny)}개 (20KB 미만)</span></h2>
    <p class="desc">보통 문제지 PDF는 200KB~3MB인데 이보다 훨씬 작음 — 깨졌거나 빈 파일일 가능성. 직접 열어서 확인 추천.</p>
    <table>
      <thead><tr><th>과목</th><th>파일명</th><th>크기</th><th></th></tr></thead>
      <tbody>{tiny_section if tiny_section else '<tr><td colspan="4" class="empty">없음</td></tr>'}</tbody>
    </table>
  </section>
</div>
</body>
</html>
"""

with open("review.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("review.html 생성 완료")
