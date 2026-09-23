"""
재크롤링 없이 data.json 다시 계산하기
==================================
파싱 규칙(과목 추출/파일명 패턴 등)만 고쳤을 때, 드라이브를 다시 훑지 않고
이미 받아둔 data.json의 filename/folder_path로 파싱 결과만 새로 만든다.
크롤링으로만 알 수 있는 값(중복 폴더, 파일 크기, 수정시각)은 그대로 보존한다.

    python reprocess.py

결과는 data.json / data.js에 덮어쓴다. 드라이브 내용 자체가 바뀌었을 땐
이걸 쓰지 말고 crawl.py를 다시 돌려야 한다.
"""
import datetime
import json

import crawl

CARRY_OVER = [
    "duplicate_sibling_folder",
    "duplicate_folder_id",
    "duplicate_folder_modified",
    "modified_time",
    "size",
    "parent_id",
]

with open("data.json", encoding="utf-8") as f:
    old = json.load(f)

records = []
for r in old:
    rec = crawl.parse_record(r["filename"], r["folder_path"], r["id"])
    for key in CARRY_OVER:
        rec[key] = r.get(key)
    records.append(rec)

crawl.fill_missing_categories(records)
crawl.split_numbered_variants(records)
crawl.canonicalize_subjects(records)
moved_container = crawl.split_container_subjects(records)
# 과목 이름이 확정된 뒤에 해야 형제 파일을 제대로 찾는다
unified = crawl.unify_by_content(records)
filled = crawl.fill_missing_exam_fields(records)

stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
with open("data.js", "w", encoding="utf-8") as f:
    # 화면에 찍어서 "지금 보는 게 최신 데이터인지" 바로 확인할 수 있게 버전을 같이 넣는다
    # (브라우저가 data.js를 캐시해서 옛날 데이터를 보고 있는 경우를 구분하려고)
    f.write(f'var EXAM_DATA_VERSION = "{stamp}";\n')
    f.write("var EXAM_DATA = ")
    json.dump(crawl.slim_for_web(records), f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")

subjects = {(r["category"], r["subject"]) for r in records}
print(f"reprocessed {len(records)} records, {len(subjects)} distinct (category, subject) pairs")
print(f"'문학' 같은 통 폴더에서 제 과목으로 옮긴 파일: {moved_container}개")
print(f"내용이 같은 파일끼리 연도/학기를 맞춘 기록: {unified}개")
print(f"형제 파일에서 빈 칸(연도/학기/시험종류)을 채운 파일: {filled}개")
