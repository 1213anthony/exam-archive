"""
기출문제 아카이브 크롤러
=====================
학교 구글 드라이브(기출문제 폴더)를 재귀적으로 순회해서 data.json 인덱스를 생성한다.

실제 폴더를 확인해서 검증한 결과 요약 (2026-09-03 기준):
- 최근 연도(~2015년 이후)는 두 가지 파일명 규칙 중 하나로 통일돼 있음:
    A) 01_문제지_(고급물리학1)_2021년1중간(B4).pdf
    B) 문제지_양자역학_2025년_1기말(B4).pdf   (용지크기 없는 경우도 있음)
- 2011~2014년 등 오래된 자료는 규칙이 거의 없음(구분자 없이 붙여쓰기, 연도 누락 등).
  이런 파일은 완전 파싱이 안 되고 fallback으로 doctype/year만 최선을 다해 추출한다.
  parsed_ok=false인 항목은 검색은 되지만(파일명 전체가 데이터에 남아있음) 구조화된
  필터(연도/학기 드롭다운 등)에는 안 걸릴 수 있음 - 수동 정리 후보.
- 폴더명(예: "2학기 중간고사")이 실제로는 다른 학기 파일을 포함하는 경우가 있었음
  (인수인계 과정에서 잘못 옮겨진 것으로 추정). 그래서 파일명에서 파싱 성공한 값을
  최우선으로 쓰고, 폴더명과 다르면 folder_mismatch=true로 표시한다.
  -> 이 목록 자체가 "잘못 분류된 파일 찾기" 정리 작업에 바로 쓸 수 있다.

사용법
------
1. pip install google-auth-oauthlib google-api-python-client
2. https://console.cloud.google.com 에서 프로젝트 생성 → "Google Drive API" 활성화
   → "OAuth 클라이언트 ID" 생성 (애플리케이션 유형: 데스크톱 앱) → credentials.json 다운로드
   (이 스크립트와 같은 폴더에 둘 것)
3. python crawl.py
   → 브라우저가 열리고 학교 계정으로 로그인 → 읽기 전용 권한 승인
   → 완료되면 data.json 생성됨 (기존 data.json은 덮어씀)
4. data.json을 index.html과 같은 폴더에 두고 그대로 GitHub Pages 등에 배포
"""

import datetime
import json
import re
import sys
import unicodedata

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# 기출문제 최상위 폴더들.
# 드라이브에 서로 다른 최상위 폴더가 두 개 있다("지필고사", "기말고사 기출").
# 처음엔 "지필고사"만 훑었는데, 그 바람에 기말고사 문제지/해설이 통째로 빠져서
# 사이트에 "문제 없음 / 해설 없음"으로 뜨는 시험이 68개나 있었다.
# 두 폴더는 내용이 일부 겹치므로(약 900개), 겹치는 건 화면에서 합쳐서 보여준다.
# layout이 "분류먼저"면 경로 맨 앞이 분류(국어/물리/…)이고, "분류없음"이면
# 경로에 분류가 아예 없이 학년/이수구분부터 시작한다. 후자는 과목만 뽑아두고
# 분류는 나중에 과목 이름으로 채운다.
ROOT_FOLDERS = [
    ("지필고사", "1_W8bDBPF5zGU3B9JuAt5g2Ycsjq7VpkH", "분류먼저"),
    ("기말고사 기출", "11A09DJOktS1l6f3ilFuGdGF5ZnZHpSxO", "분류없음"),
    ("1학기 중간고사 기출", "1HdeYJ-aU2hpW9RT8UucU1hA2pcSKu0ka", "분류없음"),
    ("2학기 중간고사 기출", "1FZiTWiy5zBNzHIUiYwvADrrFWJpT7lT6", "분류없음"),
    ("2025년 1학기 중간 기출", "1LoLd3D3dAzc9zcP9skeBmKkbFPYd2aay", "분류없음"),
    ("1학기 기말_2025", "1dIYSJoBWbDI6mTwk0dStwsThR_LMv7BF", "분류없음"),
    ("2024_1학기_중간", "1qpaBwkvue-KIvRyhsbHVHk2yTusFYm4t", "분류없음"),
]

# ---- 파일명 패턴 ----------------------------------------------------------
# 실제 4234개 데이터로 검증한 결과, 실패 사례의 69%는 파일명이 유니코드 NFD
# (자모 분리 - 맥에서 흔함)로 저장돼 있어서 정규식 속 리터럴 한글("년" 등,
# NFC)과 안 맞았던 것. list_children()에서 이름을 전부 NFC로 정규화해서
# 해결한다 (아래 patterns/키워드는 전부 NFC 기준).
#
# 과목명에 "(구)"나 "(2학년)"처럼 괄호가 중첩된 경우가 있어서, subject_raw는
# 괄호 한 겹 중첩까지 허용하는 이 조각을 재사용한다 (예: "생명과학1(구)").
_NESTED_PARENS = r"[^()]*(?:\([^()]*\)[^()]*)*"

PATTERN_A = re.compile(
    r"^(?P<seq>\d+)_(?P<doctype>[^_]+)_\((?P<subject_raw>" + _NESTED_PARENS + r")\)_?\s*"
    r"(?P<year>\d{4})년[\s_-]*(?P<semester>\d+)(?:\s*학기)?[\s_-]*(?P<examtype>중간|기말)[^_\(]*"
    r"(?:\((?P<paper>[^)]+)\))?"
    r"(?P<suffix>.*)\.pdf$"
)
PATTERN_B = re.compile(
    r"^(?P<doctype>[^_]+)_(?P<subject_raw>[^_]+)_\s*"
    r"(?P<year>\d{4})년[_\s]*(?P<semester>\d+)(?:\s*학기)?\s*(?P<examtype>중간|기말)[^\(]*"
    r"(?:\((?P<paper>[^)]+)\))?(?P<suffix>.*)\.pdf$"
)
PATTERN_C = re.compile(
    r"^(?P<year>\d{4})_(?P<semester>\d)(?P<examtype>중간|기말)[^_]*_(?P<subject_raw>[^_]+)_(?P<doctype>[^_]+)"
    r"(?P<suffix>.*)\.pdf$"
)
# D) 옛날 순서: "역학1_2012년1중간_문제지.pdf" (과목이 맨 앞, 문서유형이 맨 뒤)
PATTERN_D = re.compile(
    r"^(?P<subject_raw>[^_]+)_(?P<year>\d{4})년\s*(?P<semester>\d+)(?:\s*학기)?\s*(?P<examtype>중간|기말)[^_]*_"
    r"(?P<doctype>[^_]+)(?P<suffix>.*)\.pdf$"
)
# E) 시험종류 없이 "연도_학기_과목_문서유형.pdf" (예: 2013_2_고급영어독해_문제지.pdf)
PATTERN_E = re.compile(
    r"^(?P<year>\d{4})_(?P<semester>\d)_(?P<subject_raw>[^_]+)_(?P<doctype>[^_]+)"
    r"(?P<suffix>.*)\.pdf$"
)
# I) 과목 괄호가 안 닫히고 바로 "_연도" 로 이어지는 오타형:
#    "01_문제지_(한국사_2012년1기말.pdf"
PATTERN_I = re.compile(
    r"^(?P<seq>\d+)_(?P<doctype>[^_]+)_\(\s*(?P<subject_raw>[^_)]+?)_"
    r"(?P<year>\d{4})년(?P<semester>\d)(?P<examtype>중간|기말)(?P<suffix>.*)\.pdf$"
)
# L) PATTERN_A와 같은데 "년"이 아예 빠진 경우: "...(유기화학)_20131중간(B4)_최종.pdf"
PATTERN_L = re.compile(
    r"^(?P<seq>\d+)_(?P<doctype>[^_]+)_\((?P<subject_raw>" + _NESTED_PARENS + r")\)_"
    r"(?P<year>\d{4})(?P<semester>\d)(?P<examtype>중간|기말)"
    r"(?:\((?P<paper>[^)]+)\))?(?P<suffix>.*)\.pdf$"
)
# M) PATTERN_D와 비슷하지만 순서가 "번호_문서유형_과목_연도..." (괄호 없음):
#    "01_문제지_일반생물학1_2012년1중간.pdf"
PATTERN_M = re.compile(
    r"^(?P<seq>\d+)_(?P<doctype>[^_]+)_(?P<subject_raw>[^_]+)_"
    r"(?P<year>\d{4})년(?P<semester>\d)(?P<examtype>중간|기말)(?P<suffix>.*)\.pdf$"
)
# N) "2010학년도1학기기말고사모범답안(1학년국어).pdf" 처럼 통짜로 붙여쓴 옛날 파일
PATTERN_N = re.compile(
    r"^(?P<year>\d{4})학년도(?P<semester>\d)학기(?P<examtype>중간|기말)고사"
    r"(?P<doctype>[^\(]+)\((?P<subject_raw>[^)]+)\)(?P<suffix>.*)\.pdf$"
)
# P) "2012서울과학1학기중간고사(중국어).pdf" / "...중간고사모범답안(중국어).pdf"
#    N)과 같은 통짜형인데 "학년도"가 없고 학교 이름이 끼어있는 경우. 문서유형이
#    비어 있으면(=시험지 자체) 문제지로 본다.
PATTERN_P = re.compile(
    r"^(?P<year>(?:19|20)\d{2})[^\d]*?(?P<semester>\d)학기(?P<examtype>중간|기말)고사"
    r"(?P<doctype>[^()\d]*)\((?P<subject_raw>[^)]+)\)(?P<suffix>.*)\.pdf$"
)
# Q) "04_모범답안및해설_(미적분학2)_2019_2학기_기말.pdf" (연도와 학기 사이가 "_")
PATTERN_Q = re.compile(
    r"^(?P<seq>\d+)_(?P<doctype>[^_]+)_\(?(?P<subject_raw>" + _NESTED_PARENS + r")\)?_"
    r"(?P<year>(?:19|20)\d{2})_(?P<semester>\d)\s*학기[_\s]*(?P<examtype>중간|기말)"
    r"(?:고사)?(?P<suffix>.*)\.pdf$"
)
# O) "11-1한국사기말고사문제.pdf" (두 자리 연도-학기 축약형, 20xx로 간주)
PATTERN_O = re.compile(
    r"^(?P<yy>\d{2})-(?P<semester>\d)(?P<subject_raw>[^0-9]+?)(?P<examtype>중간|기말)고사(?P<doctype>.+)\.pdf$"
)
# F) 2011~2014년 옛날 파일: "역학1모범답안201101중간.pdf" (과목+문서유형+연도+월(01/02로
#    학기를 나타냄)+중간/기말, 구분자 없음)
PATTERN_F = re.compile(
    r"^(?P<subject_raw>.+?)(?P<doctype>모범답안및해설|모범답안\(해설\)|모범답안|모법답안"
    r"|정답및해설|정답\(해설\)|정답지|정답|해설|문제지|시험지)"
    r"(?P<year>\d{4})(?P<sem2>0[12])(?P<examtype>중간|기말)(?P<suffix>.*)\.pdf$"
)
# F2) F와 같은 모양인데 문서유형 단어가 아예 없는 것: "컴퓨터과학201101중간.pdf".
#     문서유형은 못 정하지만 과목/연도/학기는 확실히 건질 수 있다.
PATTERN_F2 = re.compile(
    r"^(?P<subject_raw>[^\d_]+?)(?P<year>(?:19|20)\d{2})(?P<sem2>0[12])"
    r"(?P<examtype>중간|기말)(?P<suffix>.*)\.pdf$"
)
# G) "2011년2학기기말문제지_현대문학.pdf" (연도+학기+시험종류+문서유형이 통짜, 과목만 분리)
PATTERN_G = re.compile(
    r"^(?P<year>\d{4})년(?P<semester>\d)학기(?P<examtype>중간|기말)"
    r"(?P<doctype>모범답안및해설|모범답안\(해설\)|모범답안|문제지)_(?P<subject_raw>.+)\.pdf$"
)
# H) PATTERN_B와 같은 모양인데 "년"이 없음: "문제지_고급프로그래밍_2025_2중간.pdf"
PATTERN_H = re.compile(
    r"^(?P<doctype>[^_]+)_(?P<subject_raw>[^_]+)_(?P<year>\d{4})_"
    r"(?P<semester>\d)(?P<examtype>중간|기말)(?P<suffix>.*)\.pdf$"
)
# J) "2011-1학기기말-영어1.pdf", "2011-1학기기말-영어1-모범답안.pdf"
PATTERN_J = re.compile(
    r"^(?P<year>\d{4})-(?P<semester>\d)학기(?P<examtype>중간|기말)-(?P<subject_raw>[^-]+?)"
    r"(?:-(?P<doctype>.+))?\.pdf$"
)
# K) "01_문제지_선형대수학_2018_2_중간고사_문제지.pdf" (examtype 뒤에 "고사"가 그대로 붙음)
PATTERN_K = re.compile(
    r"^(?P<seq>\d+)_(?P<doctype>[^_]+)_\(?(?P<subject_raw>[^_)]+)\)?_"
    r"(?P<year>\d{4})_(?P<semester>\d)[-_]?(?P<examtype>중간|기말)고사(?P<suffix>.*)\.pdf$"
)
# PATTERN_E("2013_2_철학_문제지.pdf")의 가운데 숫자는 학기가 아니라 그 해의
# 시험 회차다. 1=1학기 중간, 2=1학기 기말, 3=2학기 중간, 4=2학기 기말.
# 회차·연도·과목을 바꿔가며 PDF 표지 13장을 열어 확인했다(2013 고급영작문 1중간,
# 2016 영작문 1중간, 2011 물리학1 1기말, 2013 철학 1기말, 2012 미적분학1 1기말,
# 2011/2012 지구과학2 2기말, 2012 미적분학1 2기말, 2013 확률과통계 2기말 등).
# 그냥 학기로 읽으면 "2011_2_..."가 2학기로 잡혀서 1학기 기말 시험의 문제지와
# 해설이 엉뚱한 줄에 가서 붙는다. 실제로 3(2학기 중간)은 한 건도 없다.
EXAM_ORDINAL = {
    "1": ("1", "중간"),
    "2": ("1", "기말"),
    "3": ("2", "중간"),
    "4": ("2", "기말"),
}

# 순서 중요: 더 구체적인(오탈자 특정) 패턴을 먼저, 느슨한 패턴을 나중에 시도한다.
PATTERNS = [
    PATTERN_A, PATTERN_B, PATTERN_C, PATTERN_D, PATTERN_E,
    PATTERN_I, PATTERN_L, PATTERN_M, PATTERN_N, PATTERN_O,
    PATTERN_F, PATTERN_G, PATTERN_H, PATTERN_J, PATTERN_K,
    # 아래는 나중에 추가한 예외형. 위 패턴들이 먼저 잡아가는 걸 막지 않도록 끝에 둔다.
    PATTERN_Q, PATTERN_P, PATTERN_F2,
]

FOLDER_EXAM_RE = re.compile(r"(?P<semester>\d)학기\s*(?P<examtype>중간|기말)고사")
# "20141년중간"처럼 오타로 숫자가 하나 더 붙은 파일이 있는데, 가드가 없으면
# 뒤에서부터 맞춰서 연도를 "0141"로 읽어버린다. 19xx/20xx로 제한한다.
YEAR_ANYWHERE_RE = re.compile(r"((?:19|20)\d{2})년")
# "년" 바로 뒤가 아니어도(예: "2011학년도...", 구분자 없이 붙어쓴 옛날 파일) 최소한
# 연도 후보는 건지도록 하는 2차 fallback. 19xx/20xx 범위로 오탐 위험을 줄인다.
BARE_YEAR_RE = re.compile(r"((?:19|20)\d{2})")
# 완전 파싱은 안 돼도 "중간"/"기말" 단어와 그 앞의 학기 숫자가 파일명에 그냥 텍스트로
# 보이는 경우가 있음 - 이럴 땐 폴더명보다 이 값을 믿는 게 낫다(폴더명이 실제로 자주
# 틀리다는 걸 확인했기 때문). 예: 파일명엔 분명히 "중간"이라고 쓰여 있는데 폴더는
# "기말고사"인 경우, 폴더 대신 파일명 쪽을 신뢰해야 함.
# 학기 숫자는 구분자 뒤("2011_1중간", "2019년2중간")나 "N학기" 꼴로만 인정한다.
# 그냥 앞 글자에 붙어 있으면 과목 이름의 끝 숫자일 때가 많다
# ("미적분학2중간고사.pdf"의 2는 학기가 아니라 과목 번호).
SEM_EXAMTYPE_ANYWHERE_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s_\-년\(\)\[\]]))(?P<semester>\d)\)?(?:\s*학기\s*|[\s_\-]*)(?P<examtype>중간|기말)"
    r"|(?P<semester2>\d)\s*학기\s*(?P<examtype2>중간|기말)"
)
EXAMTYPE_ANYWHERE_RE = re.compile(r"(중간|기말)")
DOCTYPE_KEYWORDS = [
    "모범답안및해설", "모범답안", "해설", "정답지", "답안지", "문제지",
    # 아래 둘은 오타("모법답안" 등)나 "전자기-문제.pdf"처럼 축약된 이름을 위한
    # 넓은 catch-all - 위의 구체적인 키워드가 먼저 매칭되므로 순서상 안전함
    "답안", "문제",
]

# 같은 것을 다르게 부른 이름들. 화면에서는 doctype에 "문제"나 "답안/해설"이
# 들어있어야 문제지/해설 버튼으로 잡히는데, 아래 표기들은 그 글자가 없어서
# 짝이 있는데도 "문제 없음 / 해설 없음"으로 뜨고 있었다.
DOCTYPE_SYNONYMS = {
    "원안": "문제지",            # 시험 원안 = 문제지
    "시험지": "문제지",
    "논서술형채점기준표": "모범답안및해설",
    "논술형채점기준표": "모범답안및해설",
    "채점기준표": "모범답안및해설",
}


def normalize_doctype(doctype):
    if not doctype:
        return doctype
    if doctype in DOCTYPE_SYNONYMS:
        return DOCTYPE_SYNONYMS[doctype]
    for word, canon in DOCTYPE_SYNONYMS.items():
        if word in doctype:
            return canon
    return doctype


# ---- 파일 내용 해시 캐시 ---------------------------------------------------
# 실제로 다운받아 계산해둔 MD5(드라이브 파일 ID -> 해시). 같은 시험이 두 번
# 올라와 있는 걸 화면에서 하나로 합칠 때 쓴다. 파일명이 서로 달라도(예:
# "01_문제지_(고급물리학I)_2014년2중간(B4).pdf" 와
# "문제지_고급물리학1_2014년_2중간(B4).pdf") 내용이 같은 경우가 45쌍 확인돼서,
# 파일명이 아니라 해시로 판단해야 정확하다.
try:
    with open("md5_cache.json", encoding="utf-8") as _f:
        MD5_CACHE = json.load(_f)
except (FileNotFoundError, ValueError):
    MD5_CACHE = {}


# ---- 수동 확정값 (실제 PDF를 열어서 표지를 직접 대조 확인함) -----------------
# 파일명이 완전히 깨졌거나(자모 손상 등) 연도 정보가 아예 없어서 정규식으로는
# 못 잡는 파일들. drive.readonly 권한으로 실제 PDF 표지("2013학년도 (1학기
# 중간)고사...")를 열어서 확인한 진짜 값. 파일명이나 폴더명과 다른 경우가
# 여러 건 있었음(예: 파일명엔 "중간"이라고 써있는데 실제 내용은 "기말"인
# 경우, 폴더는 "2학기"인데 실제로는 "1학기"인 경우 등) - 그래서 둘 다
# 못 믿고 PDF 원문을 기준으로 확정함. key는 드라이브 파일 ID.
MANUAL_OVERRIDES = {
    # "연도_N중간_과목_문서유형.pdf"(PATTERN_C) 형식 파일들 - 폴더와 examtype이
    # 달라서 걸린 159개를 전부 표지 대조한 결과, 파일명에 "중간"이라고 써있어도
    # 실제로는 "기말"인 경우가 다수 확인됨 (같은 형식이라도 전부 그런 건 아니라서
    # -"인공지능" 과목 16개는 확인해보니 실제로도 전부 중간고사였음- 패턴으로
    # 일반화하지 않고 확인된 파일 하나하나만 확정함).
    "1nB7ggKE6Q53VMxUqIkurvzGdJUQOBzua": {"semester": "2", "examtype": "기말고사"},
    "1Gc5BtRS77qH23rW_Am0vkMp8KAKVlUE0": {"semester": "2", "examtype": "기말고사"},
    "1AriEc0X4rRaOHji6uEpcJgOYgKY5wOJH": {"semester": "1", "examtype": "기말고사"},
    "19PdWkdxQKka1u7djDdz1CTVRzIkf0w4t": {"semester": "1", "examtype": "기말고사"},
    "1RNtyB8bTHbwGq_PjwGOV2t0coFlnH0Lr": {"semester": "2", "examtype": "기말고사"},
    "1gzj82LELmQyG7d8FGnqT53jIwhUpGeU6": {"semester": "1", "examtype": "기말고사"},
    "1HOWw6uScCqqA4IHbx3jbofTzVwYCJyc6": {"semester": "1", "examtype": "기말고사"},
    "1mXR3EKNmXsPNpcv0GOn1z2i2be1zr272": {"semester": "1", "examtype": "중간고사"},
    "1LUDuFUDiUUo21-alLuiQaxypJuVzu73n": {"semester": "2", "examtype": "기말고사"},
    "1akZS7LrFGb32BvoC7HO7K2f59sfyro7R": {"semester": "2", "examtype": "기말고사"},
    "1z983AEs6oUjPip1jkLJTiIjRxR_1Z8ur": {"semester": "2", "examtype": "기말고사"},
    "1iafxZzPEKr0JCow6RzQ8Hdoyam6W4Ozm": {"semester": "1", "examtype": "기말고사"},
    "1AmdQHQX7XYsD1ijqVWSMkhd_0Nk5uN2S": {"semester": "1", "examtype": "기말고사"},
    "1LBhcrcQXBoquwnsx-5b99j2yGROTajJF": {"semester": "2", "examtype": "기말고사"},
    "1zks9gjVqkevvg0eEVjYBFx57NePWbA-_": {"semester": "1", "examtype": "기말고사"},
    "1uK2AZAQjNurndHF-TmpKiibqSEFAO_iL": {"semester": "2", "examtype": "기말고사"},
    "1bIEwskL3lB8uIm97pZPM-UrLuumBJSGU": {"semester": "1", "examtype": "기말고사"},
    "1Wx8hO0CmptXbb7aJzbealXfckpITkZS-": {"semester": "2", "examtype": "중간고사"},
    "1HC95LfguBp_Rr1W_9V8im67p5NULB_Oh": {"semester": "1", "examtype": "기말고사"},
    "1xW7-Uj0F61CiXQYVLub_vAEes46dGh19": {"semester": "1", "examtype": "기말고사"},
    "1FxZtVhNo5B7eGYUYp4c8D2Xk6VovxISc": {"semester": "2", "examtype": "기말고사"},
    "1uFN5UhQTDwKunDdqTuo4TEhZ_rcmnG76": {"semester": "1", "examtype": "기말고사"},
    "1cSrbtoH0OOA0iucsYTGxQrAPr5aEBlEu": {"semester": "1", "examtype": "기말고사"},
    "163unrr4qe9nNJrU_2CBhVuijUIsoH2Sy": {"semester": "2", "examtype": "기말고사"},
    "1bMOkAYPT-2hVDosAsJQ6lr7qQpLBZv4g": {"semester": "2", "examtype": "기말고사"},
    "1VGfLZGem7Uoh-TSxMhL8XrCyIMr6ZnpO": {"semester": "2", "examtype": "기말고사"},
    "1LMnCa0rmzt09bqBKP1Nk7d2AcRiGKpHW": {"semester": "2", "examtype": "기말고사"},
    "1nddFqsht-HmZSPMq-70qKsF2S8VR_M4W": {"semester": "2", "examtype": "기말고사"},
    "1O-Tcd7F_LoAVaH2Tx3HfOaloEpLckdfK": {"semester": "2", "examtype": "기말고사"},
    "1LrHCSsZm6SzT23oZ2_3MhlgelT5IlDMh": {"semester": "2", "examtype": "기말고사"},
    "1YhmMhgvNt-nne_dm1P9wObd406XKFnDP": {"semester": "2", "examtype": "기말고사"},
    "1zoX21JzTJB_MyNX_eqQzEqewZcqIPWe_": {"semester": "2", "examtype": "기말고사"},
    "1Qu1SXatW-jWjU4n9fORj3I8tJZx9IJwG": {"semester": "2", "examtype": "기말고사"},
    "1pwDs46fblnMCTv45iIFc6MMPFTGEabzr": {"semester": "2", "examtype": "기말고사"},
    "131Oz52wO7jdjB_mnYp8mHzyfbU2VvIo3": {"semester": "2", "examtype": "기말고사"},
    "13nByVSJdaNojtU5Xtoao8FA-wkLFo8bF": {"semester": "2", "examtype": "기말고사"},
    "1WKQpWrkhWYYPY_mMQZu_AAJY7xCH1j4g": {"semester": "2", "examtype": "기말고사"},
    "1CCSDjVV4MLgvBPWypCPh10Jd46XGezLI": {"semester": "2", "examtype": "기말고사"},
    # "연도_N학기_기말_문제지.pdf" 구조라 PATTERN_C가 아예 잘못 파싱하던 것
    # (동명 폴더 두 인스턴스, 내용은 동일)
    "11alwNhpDu_VsN1AMudrAJDqk5TZ0Mx9n": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1eQNvelP33bwwPyw-tZ_E62fVvy4RzYYS": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1o-qc8mJZBm4IWdfO_1OCQp2yQbG80d4G": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1OZcoDRJFdi-abXSihZEEQzzHeriHft5I": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},

    # "01_문제지_위상수학과 곡면_20201학기_기말고사.pdf" - 연도와 학기가 붙어 있어
    # (20201학기) 파싱이 안 되고, 폴더도 "창융특"뿐이라 과목이 분류 이름이 돼버린다.
    "1D0nl45SjtZAfde26CUBf5DG2mYHX4nqJ": {"year": "2020", "semester": "1", "examtype": "기말고사", "subject": "위상수학과 곡면"},
    "1aw2TvTPpFtpnGzWaEiW_DhdoJUM_d4f1": {"year": "2020", "semester": "1", "examtype": "기말고사", "subject": "위상수학과 곡면"},

    # ---- 남아 있던 미분류 52개를 표지 대조로 전부 확정 ----------------------
    # 파일명만으로는 연도/학기를 알 수 없는 것들이라 PDF 표지를 직접 읽어서 넣었다.
    "1ZQ0T69WENYPdCh4z0qQ2TB1xGv3NugZn": {"year": "2013", "semester": "1", "examtype": "중간고사"},
    "1ghDsakkq84rQC_HHwG_g-WZnSh6bhTlA": {"year": "2022", "semester": "1", "examtype": "중간고사"},
    "1qE8wdINB0csWrGuFU2Ow3RidIlSbMWGR": {"year": "2013", "semester": "1", "examtype": "기말고사"},
    "1jJ1p_CIpHReer-w0YbVLYSFtdpC5crF1": {"year": "2014", "semester": "1", "examtype": "기말고사"},
    "1jdp8rsZVYMShECYF9hH9BTClfXLVF1hC": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1ozCuxTH41J5TZ8X5cJaZASYWFPxKL5gh": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1qfGUIEpwIwmQMtHMXdVgAQjgvXo2cTyP": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1RCDxI_zQCyQsNC1XUHCLZU6JnU2haz7n": {"year": "2014", "semester": "2", "examtype": "기말고사"},
    "1AEwc5pEQdmdvwig-N51E1ghg0jjMJLwj": {"year": "2012", "semester": "1", "examtype": "기말고사"},
    "1EZ-4KMpYpRa9jUm3rAWxrKXPdgishCBa": {"year": "2012", "semester": "2", "examtype": "기말고사"},
    "1rfGFGprJiYuwasHQwJ4oIS5uw3tLXvEI": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1Qriik4Nj4_4FVEKAp7DyIvAnEQ3tD6HE": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1X6JoDC2VvJzmmKRtbBK4ASq8sRE55yG4": {"year": "2013", "semester": "1", "examtype": "기말고사"},
    "1bQifV9wAhBXsdKnlYtB9nxwaDmUjoZh2": {"year": "2013", "semester": "1", "examtype": "기말고사"},
    "1UYKZDrO8DgHGbbam6RMiJYnH1oMztbQ5": {"year": "2013", "semester": "2", "examtype": "중간고사"},
    "1o-_S_c1rZlU9Pt4HAMsI5Qd_IJDeVAMY": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1ziUrcQptIRuza-DiQrozDqkycjot8dag": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1wO-kZ9XkBbqrftTFjVPNinKWIYr12HdO": {"year": "2013", "semester": "2", "examtype": "중간고사"},
    "19HsZCEymbOL-gW7mDh6qwmXb9cGXQ-Qc": {"year": "2019", "semester": "2", "examtype": "기말고사"},
    "17hT8x4xZeB8H6ureJKsusu0AwkHByVUS": {"year": "2021", "semester": "1", "examtype": "기말고사"},
    "1RxjJZniP9PS8xEKQc0f7JafVGVxeq0i7": {"year": "2012", "semester": "2", "examtype": "기말고사"},
    "1EBJid9YvZgRO-DZl73VJ2ZWMRetvod-v": {"year": "2012", "semester": "2", "examtype": "기말고사"},
    "1fjM_6mAkEI6B6bksV4uZUFZjdOxhpzB5": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1BMo_nTK75-Hd-tN9VHFkvRzubfqS-fLs": {"year": "2013", "semester": "1", "examtype": "기말고사"},
    "1K-Ee8AuRedAgxn9tAp60dyaC_XyUFqGm": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1TfDii-NfDqe0HhbX8x3QeTW2C5K1UcW1": {"year": "2014", "semester": "1", "examtype": "기말고사"},
    "1zuJzOBayY7eFin2-OxAHfGGWEXpkI2i7": {"year": "2013", "semester": "1", "examtype": "기말고사"},
    "1RLICW-JuOPX0j7cMcOk0u6rulWPq404o": {"year": "2012", "semester": "2", "examtype": "기말고사"},
    "1OyzuL-N8H7nnlB10jvLX5lCPePJm_Kdn": {"year": "2012", "semester": "2", "examtype": "기말고사"},
    "1dey6kZ9pdiK1ricS5W_x-XWanl4Ce3B5": {"year": "2013", "semester": "1", "examtype": "기말고사"},
    "18Sz-xnvU4pSyVFy8I9Yb5BlogZKa4PSX": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1vr-GvSQ599xNHuLNgvJaSTuBBt_DvdNZ": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "16IZEAEJS20Flizok13kkTxb2Ib0bSYi7": {"year": "2014", "semester": "2", "examtype": "기말고사"},
    "1vdmtxspBkHTcPJ3bBsdmeS0Yf0khO081": {"year": "2021", "semester": "2", "examtype": "기말고사"},
    "1j3S0_DswrmhgIaP-Zf-Z7ktm0icuPV8r": {"year": "2020", "semester": "2", "examtype": "기말고사"},
    "101eoqMVh7aAS3zo7NoCp1b-DnBfxNEvr": {"year": "2020", "semester": "2", "examtype": "기말고사"},
    "16XUCgF0xqH0uRHQuiioy1hVOVhV9ZFzu": {"year": "2023", "semester": "2", "examtype": "기말고사"},
    "1pr1k3EXuWe_nLTposuXgEyz4XT8lssQg": {"year": "2023", "semester": "2", "examtype": "기말고사"},
    "1sVjuvSBGmX7ee-xcgH85PV7Br-EDVtVw": {"year": "2012", "semester": "2", "examtype": "기말고사"},

    # 표지 글자가 뒤죽박죽이라 정규식으로는 못 읽고 직접 눈으로 확인한 것들
    "1di9X6kNJ6fgDN6TxV_F6Qmoq9vWGt8Ge": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1-wRa_6eGUssWh4FdwOR_0mglLf1zEk6l": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "122_YJGjsdWeiyu8w3m_y0OYqtppXn4p6": {"year": "2012", "semester": "2", "examtype": "기말고사"},
    "1jFIwmdXEbuKqP2GskM_ZtasgaNIBmdTZ": {"year": "2014", "semester": "1", "examtype": "기말고사"},
    "11DwNgZOjuEcVZcmpb5QUnfh4JW6LrM6c": {"year": "2013", "semester": "2", "examtype": "기말고사"},
    "1kBBfgFDk3174upUFIcbMATyOIisjI0EA": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1MrIL_zOzI2MAx7a_cuU3gKEaNyvEKuNm": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1CDZ1aIQw4d9nLnvOVLG6kaQoa_438-S9": {"year": "2014", "semester": "1", "examtype": "기말고사"},

    # 커뮤니케이션 겨울계절수업 - 표지가 전부 "2014학년도 (겨울 계절수업)고사,
    # 2015년 1월 27일 시행"이다. 1/2학기가 아니라서 학기는 비우고 시험종류에
    # 적어둔다. 이름만 다른 같은 시험이 네 벌 올라와 있어 한 줄로 묶인다.
    "1fBjM1OQg7lAAKVJkgBn1RQ9i67IylCVe": {"year": "2014", "semester": None, "examtype": "겨울 계절수업"},
    "1ZaJyJvApwTRyRfKC3qo88gddMXDk_vyd": {"year": "2014", "semester": None, "examtype": "겨울 계절수업"},
    "16epcpKccECKp5L89vyk16c9XaH7gMgAZ": {"year": "2014", "semester": None, "examtype": "겨울 계절수업"},
    "1UHHmCogthmuSPKgunUIWnSjTLHwdDm7J": {"year": "2014", "semester": None, "examtype": "겨울 계절수업"},

    # 파일이 깨져 있어 열리지 않는다(4KB, PDF 헤더 없음). 같은 폴더에 정상적인
    # "01_문제지_(물리학1) 중간고사 문제지.pdf"(2013년 1학기 중간)가 있으므로
    # 이 파일은 지워도 된다. 값은 표지를 못 읽어 폴더 기준만 남긴다.
    "15FAg-llKvTwvBkx636JpxSYy__rf-hSv": {"year": None, "semester": "1", "examtype": "중간고사"},

    # 아래 6개는 파일명 형식이 하나뿐이라 정규식을 새로 만들 값어치가 없고,
    # 화면에 뜨는 값은 이미 정확해서 "확정"으로만 표시한다(미분류 딱지 제거).
    #   "2014_계절학기기말_..."  계절학기 표기라 학기 숫자가 없음
    #   "..._(추상대수학2)_2022_2_중간"  연도와 학기 사이가 언더스코어
    #   "일반물리학 2011년도 1학기 기말고사-모법답안"  띄어쓰기 자유형
    "1EsPvEv-BbU1o-_sJUiTavjRsXszXWclS": {"year": "2014", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1np-CdsIsRzY_3K2myjL6Hl2ts8GhCBUl": {"year": "2014", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1nBIcgbakGBi-Ch5h1a7Wy_RG3ObGmNAT": {"year": "2022", "semester": "2", "examtype": "중간고사", "doctype": "문제지"},
    "1E34-k4c9HqWKNwtXszLGC1QEhZ5kFftw": {"year": "2022", "semester": "2", "examtype": "중간고사", "doctype": "모범답안및해설"},
    "1aepjRt-jVRIC9hCVBuPwZu8njyUbVHVv": {"year": "2011", "semester": "1", "examtype": "기말고사", "doctype": "문제지"},
    "1F9JnpG2K8tWgJj8tXfFOKlPZsm6wKcIc": {"year": "2011", "semester": "1", "examtype": "기말고사", "doctype": "모범답안및해설"},

    # "해설 없음/문제 없음"으로 뜨는 줄을 확인하다 나온 오류 2건.
    # 파일명엔 2기말이라 적혀 있지만 표지는 1학기 기말이었고, 같은 시험의 문제지가
    # 1기말로 따로 떨어져 있어서 짝이 깨져 보였던 경우.
    "1T0uvRXPiZwyu2HC1D0hI6VsB7q3AfO_T": {"semester": "1"},   # 2011_2기말_지구과학I_모범답안및해설
    "1zYVeM-kjC2HrjWw4JfP3_WcHTQcZdcmb": {"semester": "1"},   # 2022_2기말_커뮤니케이션_모범답안및해설

    # "폴더 불일치"로 걸린 것들을 마저 확인하다 나온 오류 2건
    # (2011_1중간_기말_세포.pdf 는 파일명에 "중간"과 "기말"이 같이 들어있어
    #  파서가 "중간"을 먼저 잡았는데, 표지는 기말고사였음)
    "1OTShGgCfWvTyQ_1iuocd2bRSXzpOOGGx": {"year": "2011", "semester": "1", "examtype": "기말고사"},
    "1VVoivtc_MUpognHIW_kknAdvVUapfq0n": {"year": "2013", "semester": "2", "examtype": "중간고사"},

    # 동명 폴더 520개를 전부 다운받아 표지를 대조했을 때 나온 오류 5건
    # (파일명의 연도/학기가 실제 시험지와 달랐음)
    "1Cb9XEGubqOlqYE_M5lxPAQw_jjRX_mtO": {"year": "2022", "semester": "1", "examtype": "중간고사"},
    "1gr70mMsf5eeSUVnjFdmiNW-F54fCuhJH": {"year": "2015", "semester": "1", "examtype": "중간고사"},
    "1B2qvfy6SSsBSursjTIXxi_pcq30o3SVA": {"year": "2015", "semester": "1", "examtype": "중간고사"},
    "1qkwhS5BXQFTkwY5aiMtmvLjcWsa-mMpA": {"year": "2023", "semester": "2", "examtype": "중간고사"},
    "1gFHcmhk5vjPNwAp2r-dM5IYFxSqY1H3F": {"year": "2023", "semester": "2", "examtype": "중간고사"},

    # 물리 - 전자기/물리학1 (연도가 파일명에 아예 없던 것들)
    "1-eCtrpHc3nbHRtEXfgZn6QYKMT5WYjaB": {"year": "2011", "semester": "1", "examtype": "중간고사", "doctype": "문제지"},
    "1fOF0oB6gXZiCx4tHpYXRy0Yt_8yiHxCN": {"year": "2011", "semester": "1", "examtype": "중간고사", "doctype": "모범답안및해설"},
    "1t2WIcHS9zujI7HbgqegGlYG2vlfJvEEe": {"year": "2013", "semester": "1", "examtype": "중간고사", "doctype": "모범답안및해설"},
    "1ZZi6wVX7EiRC2_JH_5G42osLm6WG1UzC": {"year": "2013", "semester": "1", "examtype": "중간고사", "doctype": "문제지"},
    # 생명과학 - 실제로는 생명과학2(Ⅱ) 내용인데 생명과학1 폴더에 잘못 들어가 있었음
    "13xSSI-26YyZy__wwS2tSXThhyVNfMuyw": {"year": "2012", "semester": "2", "examtype": "중간고사", "doctype": "문제지", "subject": "생명과학2"},
    "1uCwK5ep8Y_7ta4ZwPP9nKDShnMqH7JQ_": {"year": "2012", "semester": "2", "examtype": "중간고사", "doctype": "모범답안및해설", "subject": "생명과학2"},
    # 지구과학1 - 폴더는 "2학기 중간고사"인데 표지 확인 결과 전부 1학기였음
    "1pA8Lg_CvTK3eyk3aC7uo7tjnTbkpO4i6": {"year": "2013", "semester": "1", "examtype": "중간고사", "doctype": "모범답안및해설"},
    "131yU4G_hxhxXZ7IWShlgSbxd0I5YJSUF": {"year": "2012", "semester": "1", "examtype": "중간고사", "doctype": "모범답안및해설"},
    "1-3mSLnqWGViu9dURbtI7YulieBWAZ5BZ": {"year": "2012", "semester": "1", "examtype": "중간고사", "doctype": "문제지"},
    "141miinyF84cpIq6OYLGrv6TU5g7iG5-H": {"year": "2013", "semester": "1", "examtype": "중간고사", "doctype": "문제지"},
    # 화학 - 유기화학(고급화학2), 화학IV
    "1rUIoq72uPHzdtvyOJdclu3GDmLvncBWE": {"year": "2013", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1Ulh_e4NmRrdOxQSEgpfVSDvUkXZUgxQ5": {"year": "2023", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1QkogRQZ3vHwXYGmsfZBZM08LGHMrBJUc": {"year": "2023", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    # 사회 - 한국사, 생활철학
    "1xdtfN4s95lX_UklVEW37LDaIE1amoGn8": {"year": "2012", "semester": "1", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1RwPsk3A6yFh2S583wol9EODwM5i55ZzA": {"year": "2014", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1HS2WWXGAsTsnwM0xGehgMuNGmz00bKjg": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1eyjbdv8RAn0qMIDV88j5fxasHtic7Gi8": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1vF7CscUbFbqvPLl2dxVZ3AssfuDw-j4M": {"year": "2011", "semester": "1", "examtype": "기말고사", "doctype": "문제지"},
    # 수학 - 선형대수학 (폴더는 "2학기"인데 표지는 1학기)
    "1RWCYPAkBdk4nj2jzFktxs6nZ_T2Ma9Xv": {"year": "2011", "semester": "1", "examtype": "중간고사", "doctype": "모범답안및해설"},
    "1Gx2XjMUAgMxdnAVb0LJ-KmdgPNzCrhJw": {"year": "2011", "semester": "1", "examtype": "중간고사", "doctype": "문제지"},
    # 외국어 - 영작문
    "1mrkO4B3s1vkWLwRs9AFHewHy6cdQZeTm": {"year": "2013", "semester": "1", "examtype": "기말고사", "doctype": "모범답안및해설"},
    # 정보 - 컴퓨터과학1 (같은 폴더의 "컴퓨터과학모범답안201101중간.pdf"와 짝인
    # 문제지 쪽인데 doctype 단어가 아예 없어서 못 잡던 파일)
    "1WIaOp8wyVnX8e4vkikS5KMfYdCtehixX": {"doctype": "문제지"},
    # 자모가 깨진 파일들 - 파일명엔 "중간"이라고 써있지만 실제 표지는 전부 "기말"이었음
    "14lAIzsLqLkWQ9j1arELCv6UgC1epkacn": {"year": "2014", "semester": "1", "examtype": "기말고사", "doctype": "문제지"},
    "1YTymgFSr6vZaHsu5oXZVdMwzje_jHrpH": {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1m1Rv6QzQFSZF5IkoeRBEJd7WzcdnthPz": {"year": "2014", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1qQxffe0_AFnVBIsuK8OKEXWIR-VLrc7d": {"year": "2021", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1z17b-vPmSnAd0r2EzBXQApdzxnQCtokn": {"year": "2020", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1x4RFOqu-Ymj70vQczhInyu2JTIpJu3-8": {"year": "2020", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    # 창의융합특강/과학사 - "동명 폴더" 두 인스턴스, 실제로 MD5까지 동일한 완전
    # 중복 파일로 확인됨(둘 다 같은 표지). 인스턴스1
    "16ynJ8jFZ0EFq2Oroy1y6zEpHl9fdIhRN": {"year": "2013", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "1MBuduKdmn0sEwoWKHRd8zOEm3kvXMu8A": {"year": "2013", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1UvMjl2yon8NM44dHqdCAHwt6t9_kxWjd": {"year": "2013", "semester": "1", "examtype": "기말고사", "doctype": "문제지"},
    # 인스턴스2 (인스턴스1과 바이트 단위로 동일한 파일)
    "1A9L8AD2u0bjBrsQBBX4ZHW_-kxKoztF3": {"year": "2013", "semester": "2", "examtype": "기말고사", "doctype": "모범답안및해설"},
    "1aNrYlwZ4vBREQygqTLrwqKa7yHbzYpB2": {"year": "2013", "semester": "2", "examtype": "기말고사", "doctype": "문제지"},
    "13Vj_3qYFz4UkxlwkAdpFgq9fpeSR-ShQ": {"year": "2013", "semester": "1", "examtype": "기말고사", "doctype": "문제지"},
}

# 위 MANUAL_OVERRIDES에 이미 같은 파일이 다른 이유로 들어가 있는 경우가 있다
# (예: 시험종류만 고쳐둔 파일의 과목까지 나중에 바로잡게 된 경우).
# 같은 사전에 키를 두 번 쓰면 앞의 것이 조용히 사라지므로, 나중에 확인한 것은
# 여기에 따로 모아두고 아래에서 "덮어쓰기"가 아니라 "합치기"로 반영한다.
VERIFIED_FIXES = [
    # ---- PDF 표지를 직접 열어서 확정한 것들 (파일명·폴더가 실제와 달랐음) ----
    # 표지: 2015학년도 2학기 기말고사 (중국어 Ⅱ) - 파일명엔 번호가 없었음
    ("1SNj1Y6XEJlS1YHihLq2GJhOSi5ErKLZE", {"subject": "중국어2"}),
    ("1x8uHunu7-rMHySxdrd5iu-foZaSI5X7P", {"subject": "중국어2"}),
    # 표지: 2014학년도 2학기 기말고사 중국어Ⅱ - 파일명은 "2014_ᄀ중간"으로 깨져 있음
    ("1m1Rv6QzQFSZF5IkoeRBEJd7WzcdnthPz", {"subject": "중국어2", "year": "2014", "semester": "2", "examtype": "기말고사"}),
    ("16IZEAEJS20Flizok13kkTxb2Ib0bSYi7", {"subject": "중국어2", "year": "2014", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2021학년도 2학기 기말고사 (중국어Ⅱ) - 파일명은 "(2)2_ᄂ중간"으로 깨져 있음
    ("1qQxffe0_AFnVBIsuK8OKEXWIR-VLrc7d", {"subject": "중국어2", "year": "2021", "semester": "2", "examtype": "기말고사"}),
    ("1vdmtxspBkHTcPJ3bBsdmeS0Yf0khO081", {"subject": "중국어2", "year": "2021", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2016학년도 1학기 기말고사 (중국어 Ⅰ)
    ("1M6HT-myQ_9kWoYaML2ynkKExklPQHUtZ", {"subject": "중국어1"}),
    # 표지: 2022학년도 1학기 중간고사 (독서Ⅲ)과 모범답안 - 폴더는 독서1이었음
    ("1X06sJ93c0L2nrpjbvr1okZ9JumPSZohq", {"subject": "독서3"}),
    ("1ToSXJyFp2txACQBBuvR9gfFdfGk9G7_d", {"subject": "독서3"}),
    ("1PkQKcNESQTwRLijRrbj0PYb7bfmaLufu", {"subject": "독서3"}),
    ("1aacWTxtMWtEGZKRcrd1-HbKnQDOdw8q7", {"subject": "독서3"}),
    # 표지: (현대문학)과 정답 및 해설 - 파일명엔 그냥 "문학"이라고만 돼 있어서
    # 같은 시험의 현대문학 문제지와 짝이 안 맞고 있었다
    ("1LFy5Qq2yT_yOdOB26OE21bTQwdUFAD0Z", {"subject_detail": "현대문학"}),
    ("1kmQqp_MRvVPSt1XrDyjPlT_v9dzDQsrv", {"subject_detail": "현대문학"}),
    ("1joSdecEGCO4BPacZg9SAWOWWgYNYGFrx", {"subject_detail": "현대문학"}),
    ("18KryKVB508hseuEe8hkAO5hPf5VfDe-R", {"subject_detail": "현대문학"}),

    # ---- 엉뚱한 과목 폴더에 들어가 있던 파일들 ----
    # 파일명에 적힌 과목과 폴더가 완전히 다르고, 파일명 쪽 과목의 같은 시험에는
    # 이미 같은 파일이 있는 걸(내용 해시로) 확인했다. 폴더가 틀린 것.
    # 이 파일은 창의융합특강 폴더 밑에 있어서 분류까지 같이 바로잡아야 한다
    ("1YYQhwq1uHlZTSJgo8hSBFLE-EFT1XJuV", {"subject": "국어2", "category": "국어"}),
    ("1tac6M6OnVJ2YDxV7ZMxmjKFWAKjEFxEN", {"subject": "국어2"}),
    ("1kxvijphLSc6E3jjASePsZsp-zU1mPDQb", {"subject": "컴퓨터과학2"}),  # 지구과학III 폴더에 있던 컴퓨터과학II 해설
    ("191TXHW-pq7DROagPSXRH_597IBqGuQSB", {"subject": "생명과학3"}),    # 물리학3 폴더에 있던 생명과학3 해설
    ("1SuxSRyo1TjPmOEMdmkpSTBF6ubrv8emT", {"subject": "생명과학3"}),
    ("1dWixt3iVirhlYZ66JBcfyO5Gog9ShFky", {"subject": "영어회화1"}),    # English Conversation I = 영어회화1
    ("1u9mZtTfLefXohSx125Kg8UOYH41ADrC9", {"subject": "영어회화1"}),    # 같은 파일(확장자만 없음)
    # "1학년 / 국어" 폴더의 2023년 1중간 문제지. 같은 시험의 해설이 국어1에
    # 있고 파일명 형식도 짝이 맞는다(01_문제지_(국어) / 05_모범답안및해설_(국어1)).
    ("1dZ9-hXDBCOAhRs3NhYMvWL9gHI3Hzeyn", {"subject": "국어1"}),
    ("1ZWGBn2J8f6x0lTxdEPOrCrxEunTFUifn", {"subject": "국어1"}),
    # 표지: 2013학년도 1학기 중간고사 (물리학1)
    ("1ZQ0T69WENYPdCh4z0qQ2TB1xGv3NugZn", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1McLcBFv-wuUqOo4kuhoB4_4XyZJLKUc8", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("18K50KdmnV_iYeQeK2VWe5bSzZGw4SEKU", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1a7w_6e7xLLQLDowokbL83wlfP5mXCgNR", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 표지: 2012학년도 2학기 기말고사 (물 리 화 학) - 파일명의 '2중간'이 틀림
    ("1akZS7LrFGb32BvoC7HO7K2f59sfyro7R", {"semester": "2", "examtype": "기말고사"}),
    ("1v6909jA8SijlTnl5vKd01EPFndlytbh_", {"semester": "2", "examtype": "기말고사"}),
    # 내용이 답안표(번호/답/배점)이고 같은 폴더의 2011 1기말 세포생물학I 시험 것
    ("1OTShGgCfWvTyQ_1iuocd2bRSXzpOOGGx", {"examtype": "기말고사", "doctype": "모범답안및해설"}),
    ("12Oy-3dfPoh6fcamiR3y-VzHpu_aRM1QD", {"examtype": "기말고사", "doctype": "모범답안및해설"}),
    # 표지: 2013학년도 2학기 기말고사 (미적분학II), 2013년 12월 2일
    ("11DwNgZOjuEcVZcmpb5QUnfh4JW6LrM6c", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1mVgB_dRt9Vb19ibFUvLcj_rSmzYcyZae", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2012학년도 1학기 중간고사 (미적분학II)
    ("1KZbO8O82hva4JhIYOEGZduZbiFsLgp1n", {"year": "2012", "semester": "1", "examtype": "중간고사", "doctype": "문제지"}),
    ("1TRWNTVisL2L27T_TU3Qxfe4m1HwYcn6R", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    ("1wdnVUWE6ejBPdKcdszrRFjfNkfLWPv-d", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    # 표지: 2013학년도 2학기 중간고사 (미적분학II)
    ("1-E_k4yEQMaARzUTd_IAnhR3OFegGobPQ", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    ("1EeBBP-S6LB11a0ziZJP3VwAimzARuI4X", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    ("1VS6WbMLKl-Gc48qmkpSlbfFMI8MSQmUM", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    # 표지: 2014학년도 1학기 기말고사 (미적분학II)
    ("12iMd2QRct7-3k1QQ02NbVXHgl0tr2WDO", {"year": "2014", "semester": "1", "examtype": "기말고사"}),
    # 표지: 2016학년도 1학기 기말고사 (영어Ⅰ) - 파일명의 '2'는 학기가 아님
    ("1VmYixyz53MjTARE3QcD1I6ncOv5bdOB7", {"year": "2016", "semester": "1", "examtype": "기말고사"}),
    # 표지: 2016학년도 1학기 중간고사 (영 작 문)
    ("1uhLP6pSNzVEVgUMghv_A7U0twMP-7lKg", {"year": "2016", "semester": "1", "examtype": "중간고사"}),
    # 표지: 2016학년도 1학기 기말고사 (중국어 Ⅰ)
    ("1NoCc-hJ_DZrNXkN6aeTt34a125xQOUcf", {"year": "2016", "semester": "1", "examtype": "기말고사"}),
    # 표지: 2015학년도 1학기 기말고사 (고급생명과학 II)
    ("131RtAy8lT_Ve3o6JqQW1w6JUzIEZQlJt", {"year": "2015", "semester": "1", "examtype": "기말고사"}),
    ("1-Lqs9ND-0P9-X8zX8by1Vsaau2NMPzpX", {"year": "2015", "semester": "1", "examtype": "기말고사"}),
    # 표지: (일반생물학II)과 정답 및 해설 - 폴더는 생명과학1이었음
    ("1kI3BamJRDrYGW4_DhqGW31RSy4oS1EyX", {"subject": "생명과학2"}),
    ("1rKvhXvV6UhLI59MGZiCk8TLt3aDuawP2", {"subject": "생명과학2"}),
    # 위와 같은 시험의 다른 판본
    ("1Pp90H1ZSI3s98oCHImpQoUJ2bqNcwByC", {"subject": "생명과학2"}),
    # 표지 머리글엔 '1학기 중간'이라고 돼 있지만 시행일이 9월 25일(2학기)이고,
    # 똑같은 파일명이 이미 2015년 2학기 중간 시험에 짝을 이뤄 들어가 있다.
    # 표지 머리글 쪽이 선생님 오타로 보여 학기를 2로 잡는다.
    ("1mXR3EKNmXsPNpcv0GOn1z2i2be1zr272", {"year": "2015", "semester": "2", "examtype": "중간고사"}),
    ("1gr70mMsf5eeSUVnjFdmiNW-F54fCuhJH", {"year": "2015", "semester": "2", "examtype": "중간고사"}),
    ("1B2qvfy6SSsBSursjTIXxi_pcq30o3SVA", {"year": "2015", "semester": "2", "examtype": "중간고사"}),
    # 표지: 2022학년도 1학기 기말고사 (커뮤니케이션), 2022년 7월 4일 - 세 파일 다
    # 이름엔 "2기말"이라 돼 있지만 실제로는 1학기 기말이다(같은 시험의 문제지도 1기말에 있음)
    ("1t_y36G1g16I1gwD3svZJue7AiBd_KMMc", {"year": "2022", "semester": "1", "examtype": "기말고사"}),
    ("1XBfzJRvJ_Pms2KkrfMpm_zzM4UIBcpzW", {"year": "2022", "semester": "1", "examtype": "기말고사"}),
    ("1Llj9z_k2fny22NWUeEp5S72ToRJ_Q7Vm", {"year": "2022", "semester": "1", "examtype": "기말고사"}),
    # 표지: 2015학년도 1학기 기말고사 (고급생명과학1) - 파일명의 '1중간'이 틀림. 같은 내용이 이미 1기말 시험에 들어가 있음
    ("1MX0OVt7-OICkSrbAfpWh9gTx7-O_ox-O", {"examtype": "기말고사"}),
    # 내용 해시가 물리학1 2024년 1학기 중간 해설과 같음(같은 파일). 파일명의 '2중간'이 틀림
    ("132Jgc_YG_fJKroZDmbyNAvAqI5N5OBNF", {"semester": "1"}),
    # 표지: 2022학년도 1학기 중간고사 (물리학1). 내용 해시도 1중간 해설과 같음
    ("1hVqRtrcAKup_UCTUW6YuF2c9FlkpP53h", {"semester": "1"}),
    ("1NxicuD_TKUi29cC8UoHOGO67Zju04pPJ", {"semester": "1"}),
    # 표지: 2013학년도 2학기 중간고사 (생명과학Ⅰ) - 파일명의 2012가 틀림
    ("1YbOk-wC3NRvz_B6SA0m4vtSWhxlgqlMK", {"year": "2013"}),
    # 표지: 2019학년도 2학기 기말고사 (수리정보탐구) - 파일명의 '2중간'이 틀림
    ("1ZKhHhwGZPe7jjzqVwPOD7YTUy_cQ46kX", {"examtype": "기말고사"}),
    # 표지 머리글이 2023학년도 2학기 중간이고 같은 시험의 문제지도 2023년 10월 10일. 해설 표지의 '2022년'이 오타
    ("1qkwhS5BXQFTkwY5aiMtmvLjcWsa-mMpA", {"year": "2023"}),
    ("1gFHcmhk5vjPNwAp2r-dM5IYFxSqY1H3F", {"year": "2023"}),
    ("1_8-NO4w1WrMPHdWu9Ez-trzFshCkrx6u", {"year": "2023"}),
    ("1_NdI0JedR7OrN5-z7k3ygqbASZUtfq19", {"year": "2023"}),
    # 표지: 2014학년도 2학기 기말고사 (커뮤니케이션) - 파일명의 '2중간'이 틀림
    ("1Oxg261gDET2OU37EetTW6xVbt4xPdkGQ", {"examtype": "기말고사"}),
    # 내용 해시가 한국사 2024년 1학기 중간 해설과 같음(같은 파일)
    ("1RrymUFAhkndhgOeqyJRk6s359t7lW3b4", {"semester": "1"}),
    # 이름은 '문제지'인데 표지가 '(고급영작문)과 정답 및 해설'이다. 2013년 2학기 중간 해설
    ("1wO-kZ9XkBbqrftTFjVPNinKWIYr12HdO", {"doctype": "모범답안및해설"}),
    ("13zqRkC6GoybcZsTj1lF0q3NJ5xRNTF05", {"doctype": "모범답안및해설"}),
    # 표지: 2011학년도 1학기 중간고사 (현대문학) 문항수 표기가 있는 문제지. 이름만 '모범답안및해설'
    ("1kLlWpNQFKG2YCk1SUL21e9lbzGjtfPnZ", {"doctype": "문제지"}),
    ("182DAsFo9QSeepTvl3eqpgdFKrQzMnAWf", {"doctype": "문제지"}),
    ("1zUqxpOewFT51phsMuvmLke-Wfi1k3P75", {"doctype": "문제지"}),
    ("1Td1P44v685fSHjrMCkS9l41KH-V2HcU2", {"doctype": "문제지"}),
    ("1OADS9Aavj_oMrVbZmsdk5f5Gt095cd4_", {"doctype": "문제지"}),
    ("10Ay0j3kf68CcS2zq4kIw9GDY0tCVUSOd", {"doctype": "문제지"}),
    # 표지: 2011학년도 2학기 중간고사 (현대문학) 문제지. 이름만 '모범답안및해설'
    ("15FxaQ2GOuXWP4xjuhAQks815Y6ykpfeO", {"doctype": "문제지"}),
    ("1TgMYyzdxnfW7q6yzSr0-RW8Jsvppviy6", {"doctype": "문제지"}),
    ("1g2V4f0Idcl_67itjTKZDuucu-BCDrVDM", {"doctype": "문제지"}),
    ("1XsKcgOFLLNMCIE3--sXcFOqJ3QPI8pA8", {"doctype": "문제지"}),
    ("11f4AJ1riiHOuN_yI6Oq1Nxjs-IGysNTk", {"doctype": "문제지"}),
    ("1qz6BVRjEXHQ9dmCRxsT1adPhOV0BpfvB", {"doctype": "문제지"}),
    # 표지: 2011학년도 2학기 기말고사 (영어 II) 문제지(6면, 문항수 표기). 이름만 '모범답안및해설'
    ("1D8ce5rWcUIBMNQ3-zauZwQR1y4a0mr0F", {"doctype": "문제지"}),
    ("18YCk9eEZjmuxz3fXMYZp7TSHtAotdonn", {"doctype": "문제지"}),
    # 표지: 2013학년도 1학기 중간고사, 중국어Ⅰ 정답 및 해설 (파일명에 연도가 없었음)
    ("16tpZHO6m3tjyDFfAJkZkZGWY10v5B8br", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 표지: 2012학년도 2학기 기말고사 (한국사) 문제지. 파일명 "122말한국사문제"는 못 읽던 것
    ("1JSgXflPDltm3KLfpu4gACI8zeJ8jY0K9", {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"}),
    # 표지: 2013학년도 1학기 중간고사 중국어Ⅰ 문제지 (파일명에 연도가 없음)
    ("1gLidY66Jq_d51xdM44EnfcA2Oa9oyjUr", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 표지: 2013학년도 1학기 중간고사 중국어Ⅰ 정답 및 해설 (위 문제지의 짝)
    ("16tpZHO6m3tjyDFfAJkZkZGWY10v5B8br", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 표지: 2014학년도 2학기 기말고사 (한국사)과 정답 및 해설
    ("1cidkdFsYmb3jc9DUE5msni96lIn1OXSD", {"year": "2014", "semester": "2", "examtype": "기말고사"}),
    ("1RwPsk3A6yFh2S583wol9EODwM5i55ZzA", {"year": "2014", "semester": "2", "examtype": "기말고사"}),
    ("1RCDxI_zQCyQsNC1XUHCLZU6JnU2haz7n", {"year": "2014", "semester": "2", "examtype": "기말고사"}),
    ("1Mza68ztn6C-MP-iqwJ2OoeOyQh8JRxSg", {"year": "2014", "semester": "2", "examtype": "기말고사"}),
    ("14g_jBht3KI5miHoiIG53LsyoRqhXP0QD", {"year": "2014", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2012학년도 2학기말고사 (한국사)과 정답 및 해설
    ("1lNnQHu5UtlBvSXCWZ4zRtmizYg_3EpZA", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1HS2WWXGAsTsnwM0xGehgMuNGmz00bKjg", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("122_YJGjsdWeiyu8w3m_y0OYqtppXn4p6", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1P1pRpdkOBW8-6-AYbX5e9ADAGQfINkh2", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1XCIUdQkMaCF9LHVxg4DpnSbSMz6Q4QBc", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2012학년도 1학기 기말고사 (한국사)과 정답 및 해설
    ("1PH0ZBRaCLAJ2kCKQyS6kmG1CpNqFRtbM", {"year": "2012", "semester": "1", "examtype": "기말고사"}),
    ("1xdtfN4s95lX_UklVEW37LDaIE1amoGn8", {"year": "2012", "semester": "1", "examtype": "기말고사"}),
    ("1AEwc5pEQdmdvwig-N51E1ghg0jjMJLwj", {"year": "2012", "semester": "1", "examtype": "기말고사"}),
    ("1ve0QxUX7fBPDaBrM1o_1Xcv6AieRalTv", {"year": "2012", "semester": "1", "examtype": "기말고사"}),
    ("1LWDg7M2o-hJT_RF9Cewy_CKMxCKej5Ve", {"year": "2012", "semester": "1", "examtype": "기말고사"}),
    # 표지: 2012학년도 2학기 기말고사 (한국사) 문제지
    ("11lBELlsMD3qRnN51ODdh3JgMekOcKr4-", {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"}),
    ("1eyjbdv8RAn0qMIDV88j5fxasHtic7Gi8", {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"}),
    ("1EZ-4KMpYpRa9jUm3rAWxrKXPdgishCBa", {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"}),
    ("1ywjLl1iW5HMZqHfA4aAWebSv1z7z5ksD", {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"}),
    ("1JSgXflPDltm3KLfpu4gACI8zeJ8jY0K9", {"year": "2012", "semester": "2", "examtype": "기말고사", "doctype": "문제지"}),
    # 2011학년도 1학기 중간고사 (전자기학 I)과 정답 및 해설
    ("13Frt7OS3R9ZXOyr586mfwr0g9UrphNSN", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1fOF0oB6gXZiCx4tHpYXRy0Yt_8yiHxCN", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1Ynqkqs7aw6QdygD8Z5dpB5DncHmyj-jm", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1vo4KxWMmQzN1DqPjp-d9ndDVic6hVH95", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1Glq6tk-1lSR74XHzSOACNd1A0YDSx6xL", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1nd9wlTI6X8jzVC4D41i317y7M33lTJPS", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1l41_7fjJAKYpUYBp-Y0RRYVnKbfAB2hR", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    # 2011학년도 1학기 중간고사 (전자기학Ⅰ) 문제지
    ("1j9yPS_LrGdiDDvxkss0Kam68_siVIuAn", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1-eCtrpHc3nbHRtEXfgZn6QYKMT5WYjaB", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("19pYkHJ8d-nng8w6jdfgbyACZ8C348qzQ", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1fHA8kGfOdhguRd88pkY3NvBCNDjpLC4U", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("15rx0MCVgTxrPZr4YrFj91jQf8QK_8hpG", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1I_UrD1D6jDuVsReWYTR_ArpoWBln-7e5", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1HJcBJeLOudDaS1gqCXC20qZn9gUfZJ1i", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    # 2013학년도 1학기 중간고사 (전자기학 I)과 정답 및 해설
    ("1dN4K9qeCM6SvB0KnzF60v4SuPR0ICDUq", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1t2WIcHS9zujI7HbgqegGlYG2vlfJvEEe", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("14RepUXZs7br6MwQVUDqTeDBo6-Cv-mF_", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1d89hsMhMlOiQm_ph1tPKO-R1dkitSWa1", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("17ECt0qGAfxERwZXoCqGB0PvKcUNmcnEk", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1mk8HI0_foAIF54xcv-W2WfqTHsvlafUm", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1C-CwratebN5eiNWFCWtOC8DUKi-vNvW8", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 2013학년도 1학기 중간고사 (전자기학 I) 문제지
    ("1i7g_DQGBwt8qARBIWRrUSZNc9lPV5nJH", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1ZZi6wVX7EiRC2_JH_5G42osLm6WG1UzC", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1RO2uIMaatiO8i9Me33n5CufZA6KI4wS6", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1k2OiH0XyjUET0uj8kQ4G20Qvf4GHSyAz", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1zTrS0-AMkj_Npzc0iXIT8VPIq7PpmueC", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1KLo8_rZTDH0debDU5U5RUX_QHrtv3r2D", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1MBo_3QNmGVhCPiaib5nxlRF0NpZtdgzB", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 2011학년도 1학기 기말고사 (생활철학)과 정답 및 해설
    ("1k3j1tgwPeRGrG5TEZ9yXLBQ1YJCEmq6N", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1Qriik4Nj4_4FVEKAp7DyIvAnEQ3tD6HE", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1v7NHtRYMuUbFA8xccK1Ok4SADD9PUMK0", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1l-CyTiDKXYvMoqcHcg_Prl22WYnWHneh", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    # 2011학년도 1학기 기말고사 (생활철학) 문제지
    ("1EG6P8uQD-9CckZ_3fa92HQ7aoSYcyzt9", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1vF7CscUbFbqvPLl2dxVZ3AssfuDw-j4M", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1rfGFGprJiYuwasHQwJ4oIS5uw3tLXvEI", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1x6LRJdKpOctfY3RQDnFoM1y9n6Oj0N87", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    ("1eoZrh34g5-RPCJFkoBtx7v_fvQAgf2Od", {"year": "2011", "semester": "1", "examtype": "기말고사"}),
    # 2012학년도 2학기 중간고사 (생명과학 Ⅱ)과 정답 및 해설
    ("1uCwK5ep8Y_7ta4ZwPP9nKDShnMqH7JQ_", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1JuW-l-N1XKekWKkOxBQ1SBBqqJTzKLU-", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("11kLT4Sv7sq2bebAZLYrsrGGLmm3nmRzi", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("16SzicdNK-PEHflfR-JzfU7ykbeA4SEIx", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1ai2_rSa0PgU8Stm1d7uZAI0p_OjdH4O0", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1XMSEiy1uC7QUklN1o2ajMS6T3xB7ORQX", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1A9W3HfbZrnyG14Sx2fXxZkTO3DYcBIyF", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1rueJ1fROzoOJQcPL8aA1vCzjYMNBJLXd", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    # 2012학년도 2학기 중간고사 (생명과학Ⅱ) 문제지
    ("13xSSI-26YyZy__wwS2tSXThhyVNfMuyw", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1bUypkgUSMrEX5VaqrwiUEelLavkqpXOx", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1_hEBJpbT6BEnNKYdOdvGiDxnFdpoLEPH", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1suWxJnwj-lY6585g0kfkxHNc_52jsc6A", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1yKhynse8HXkGzLPi1SN_KuEOcHHwT9w7", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1sfasYDXCX7fw28jAj34YTNOMXvTJTKln", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1kbhKUBxOv_Vbi0cPZ4GXuPnQ293LJ8aB", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1ANuFpNOYZPXo-LI0mPZKQJ7y1DlB5pQk", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    # 2020학년도 1학기 중간고사 (미적분학1)과 정답 및 해설
    ("1d636e7joe6tM2MztR-bFXPgMfd64e-Nk", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1sY3iIkCk9_-Rpmh6ZQ2u3n6i2N6j3Zqi", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1Sbd4rx32sborFNFX3ppbYBAHaV3sRt61", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1nPoIW5gChoZKM9mn0CANKPZRdNOCX5pf", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1RbSJKmjVi4CgATyY9FPk0JVLsX9zhXtx", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1p_OnTOaS32QvYu4k41UMMCN1EXmEzv0m", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1yWeztg0VObSiILnCUDkcTkyYrdrpg24J", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1I6IMCIM07jyeqQhNiiviQxPOcyng_C4N", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1jrdCS6_4rXH04GeTkSAEp946krzRVZRT", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    # 2020학년도 1학기 중간고사 (미적분학1) 문제지
    ("1qNwScRgY1BM5yerVrOxNJXOhn2zXccxQ", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1TLVtVKQFJvi5fMhZB_gLHdnKCdBWQNDX", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1r3PgKTSMYNZFTm-3Eb9u08bJ0sT9KCT0", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1cFbJprxZfAkqkbyHuMrLaHDNyuY-rvWB", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1GPMfahIhDB4eVg_rkQ2Zd3H8poUKvQeZ", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    ("1ewHi9ENZ-HWRXsaQnx97wOBRnzZ_W-Tk", {"year": "2020", "semester": "1", "examtype": "중간고사"}),
    # 2020학년도 1학기 기말고사 (미적분학1)과 모범답안및해설
    ("16vG_f4Y76Q_ptHMGqF0snhdFAgmeODHZ", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    ("1dyJZPA_qdI_goYGqjVyA2OYLIAzIweKo", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    ("1yiwqXVlYmXE-pNSvc9JSPCJa3Cht92uP", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    ("143Ss9s3a2urYZOJP3otLsdIXV0o6F9Mp", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    # 2020학년도 1학기 기말고사 (미적분학1) 문제지
    ("1UYjL9Cxo6L_MceK-IkRLVSs6ZHE1-gIf", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    ("1tWQ8k5FOQD96Je0vlQLLXDT-TpiVZ92u", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    ("1FvRIw50i-2_6YEpvxPzrTIOZsa4oaBrr", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    ("1Clo0omp5A1Fu6E8WV5H4RzIgFM1crC58", {"year": "2020", "semester": "1", "examtype": "기말고사"}),
    # 2011학년도 1학기 중간고사 (선형대수학) 문제지
    ("1Gx2XjMUAgMxdnAVb0LJ-KmdgPNzCrhJw", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1ExWSvyCpa81ticNGBampclAYdbpUESKE", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("10Tsc4FY-qZdXRoQbj9xYjAZQ_JxsAVZc", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1Box4vplk1U26kvSv4nI_OlTzx38CjjWs", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1q7_9r8eTDh2fp1pHJduSwV1AYQNk2Uva", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1WiaPng2NOTd3AiMZWalX6dMgbo8Q1766", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    # 2011학년도 1학기 중간고사 선형대수학 정답 및 해설
    ("1RWCYPAkBdk4nj2jzFktxs6nZ_T2Ma9Xv", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1gpvtaaM-50oqheIVqlz6c6SeElCDrKT4", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("15hu6v9eQi_sGA8fdCEPe2hm88XdZI29E", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("12ng_IFjg9KemtH44_FdUt3skbNH58T28", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1vAROy056LnLu3iqvAOuKsMwCvQkgodrB", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    ("1Om4a0tGsH_upDiJBiS_YbaNpX1bqJ4ep", {"year": "2011", "semester": "1", "examtype": "중간고사"}),
    # 2023학년도 2학기 기말고사 (선형대수학)과 정답및해설
    ("1Hcy4fPn84j0mIrSAPmt2R58PXuy7ueo7", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1Y4LWEeEaOPhtiqBr3Bt9Yewh2KqCm8hM", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1EpJ-dbyh4cqnXxWOXbOKOXHiGFqWxUBj", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1Q_6cPph4yoq091C5WnpOiLUBjWB8Xr8z", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1zW2KHM8C01oeRBKfmkmPVZfVGH431QnM", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    # 2023학년도 2학기 기말고사 (선형대수학) 문제지
    ("1w0qn7SD7ccsYa6F3vRTLL1oh_kUNf_cF", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1fzx6U3W6sgC030ZWFLp9iyoxfV3HNlvA", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1NBnA3IX4zbks8IDW814m666TT8--i6EH", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1EaRxC8gu5_-yrgXZ3ZNM9r4CT6VArCUB", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    ("1O4fffxIEhSS-sAL1j18GhuMWdQne2eAQ", {"year": "2023", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 2학기 중간고사 (고급영작문)과 정답 및 해설
    ("1wO-kZ9XkBbqrftTFjVPNinKWIYr12HdO", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    ("13zqRkC6GoybcZsTj1lF0q3NJ5xRNTF05", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    # 2013학년도 1학기 기말고사 (고급 영작문)과 정답 및 해설
    ("1mrkO4B3s1vkWLwRs9AFHewHy6cdQZeTm", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1bQifV9wAhBXsdKnlYtB9nxwaDmUjoZh2", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1CopzFdOKyPP95aAMThEIAhu1CvPWhQQE", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    # 2013학년도 2학기 중간고사 (고급 영작문) 문제지
    ("1UYKZDrO8DgHGbbam6RMiJYnH1oMztbQ5", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    ("1yOHB00N-ZOFaX8HvjN1Qsp9uUpt_dAVv", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    # 2013학년도 1학기 기말고사 (고급 영작문) 문제지
    ("1X6JoDC2VvJzmmKRtbBK4ASq8sRE55yG4", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1KgzcRU20u5XjSFkopReqigXpK1u17dO-", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    # 2013학년도 2학기 기말고사 (고급 영작문) 문제지
    ("1ziUrcQptIRuza-DiQrozDqkycjot8dag", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1-4KTarQ0sGtkUyTKDJhR0n_a-Kzv9rqe", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 2학기 기말고사 (고급영작문)과 정답 및 해설
    ("1jdp8rsZVYMShECYF9hH9BTClfXLVF1hC", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1o-_S_c1rZlU9Pt4HAMsI5Qd_IJDeVAMY", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1cC0l9ARRNXBQhKfKdqK2uUsp7XIdrMCZ", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 1학기 중간고사 (지구과학Ⅰ) 문제지
    ("141miinyF84cpIq6OYLGrv6TU5g7iG5-H", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1hq7Efym_mYjAC0LSIu770N6S8MphjRbt", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 2013학년도 1학기 중간고사 (지구과학1)과 정답 및 해설
    ("1pA8Lg_CvTK3eyk3aC7uo7tjnTbkpO4i6", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("11I7-6oj_dcGnE3gB-XlWsKQFxi_0Rid8", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 2012학년도 1학기 중간고사 (지구과학 I) 문제지
    ("1-3mSLnqWGViu9dURbtI7YulieBWAZ5BZ", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    ("1BekI9nnpHQMP0d34Bcp1pKOymqYt6z9g", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    # 2012학년도 1학기 중간고사 (지구과학 I)과 정답 및 해설
    ("131yU4G_hxhxXZ7IWShlgSbxd0I5YJSUF", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    ("129e5kVrdBD9pDimyOxcbYmOACatA7lpk", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    # 2012학년도 2학기 중간고사 (지구과학 Ⅱ) 문제지 - 지구과학3 폴더에 있었음
    ("1m8mY-SHvimOKY9nQUylUjzf4jYhNwlwX", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1iwMzZij41bZyGSARThUCLbtVmLICVJdB", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1ZB8PLZTTFm6m2C2lrwLIfNQWe2jDRlEN", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1qMBC9iHrq8iMs5c9ACFJi2nwXuYiUnaV", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1Yr_Qql1LWrbL6ZqVVazazE8bvY0C_qO_", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1-S5YGWRFZBEMWKqrLW9HprHpqS-RIF5T", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    # 2012학년도 2학기 중간고사 (지구과학 Ⅱ)과 정답 및 해설 - 지구과학3 폴더에 있었음
    ("1IA_MztSeQRTFjTDYEGc91pHrxxb5UfYA", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1peNuGX4prjGugaByaqH12UCLUNxc7ok_", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1EFgCVeWVZFNzIXuo-ImO-WaCrd-bGsxg", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1w5RDZgnjG6xGcEokXKWzg8sUshBWyBoB", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("10zvgJzP8aoxbrcurUiVQ65_fFDdO4M_w", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    ("1pNXOm4DoMbQUbhWyV1z2LRUW7TCBsrVX", {"year": "2012", "semester": "2", "examtype": "중간고사", "subject": "지구과학2"}),
    # 2017학년도 2학기 중간고사 (지구과학 Ⅲ) 문제지
    ("1IYyhJTWyUMTbmPViqFp_S7tofD89gpWG", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1wXbrHdbeiqyGrKAGH6de1Soj63ddIO_w", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("10bs6FYOrT0AeuLdsrzy-dRJb4yBXCU3u", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1eUScbD6D3Jv8az7wPvchltx9I3c24F93", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1R7CmEwmhoZVgP2MOOUZRaEpbrXRP9BZO", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1NF2zY6tF6dH-qp5Bhi78jzrAOCMhHu1v", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    # 2017학년도 2학기 중간고사 (지구과학Ⅲ)과 정답 및 해설
    ("1GbIHfAkaZMigAFffbaBQoYQ1lUbdh0NZ", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1tzEwU-AXAZtwiBmO2Xc_HqDnJo3TTlFW", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1q4IB4m_5gvwJC5r0qiEeaEGUZnWQGmDc", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1E0TuPHQPeoSk1YRcBy5umDHobr7fHaE5", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1Q_l3iC3QQ1GC6IrjM-mYKajA9x9obust", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    ("1y3zGU-Di9MDWPEVq0x-2NWjlb4vb_mX4", {"year": "2017", "semester": "2", "examtype": "중간고사"}),
    # 2013학년도 2학기 중간고사 (과학사) 정답과 해설
    ("1RYvUvE7ihUt2bsP-UZTHuWH4JdqQ5a0O", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    ("1fCu86S_rUI9Ns8HlalJsOiL3gaLTIJtW", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    # 2013학년도 2학기 중간고사 (과학사) 문제지
    ("1xmI87oFCsFRE0nAIshE7CnyLA570N6RQ", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    ("1ohMnDebtE1zq1MkB5WnOrPyDHd2Ydq5L", {"year": "2013", "semester": "2", "examtype": "중간고사"}),
    # 2012학년도 2학기 중간고사 (과학사) 문제지
    ("1SYG7_OVP2QmnN3NIRlxZd5ZcQv4YvsxG", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("1Vrh47Culk4Bv6-KakCYILeDKNbDBlpqQ", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    # 2012학년도 2학기 중간고사 (과학사)과 정답 및 해설
    ("1Dj9NdmU4H16BcjViwlWdlDpbFBtqEFFs", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    ("11uy9WpYm5CIpQ2ijTypSYlQ8EfFxQ1ju", {"year": "2012", "semester": "2", "examtype": "중간고사"}),
    # 2013학년도 1학기 기말고사 (과학사) 문제지
    ("1UvMjl2yon8NM44dHqdCAHwt6t9_kxWjd", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("13Vj_3qYFz4UkxlwkAdpFgq9fpeSR-ShQ", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1BMo_nTK75-Hd-tN9VHFkvRzubfqS-fLs", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1dey6kZ9pdiK1ricS5W_x-XWanl4Ce3B5", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1sAhIb_xAgbfPFA-Zph8t0brxq7DMDHil", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    ("1GAQYJYg3Q55i8gIM3qCSdMpAGDCaMZys", {"year": "2013", "semester": "1", "examtype": "기말고사"}),
    # 2012학년도 1학기 중간고사 (과학사)과 정답 및 해설
    ("108c4qzzpkvtNoOFcmKnm2ib-tByNSHjp", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    ("1qyZ5-cVBBIWVD5Ut8a03V6ylaWC_ebcE", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    # 2012학년도 1학기 중간고사 (과학사) 문제지 (시행일 표기는 2011년이지만 학년도는 2012)
    ("1PW2wU2QtMNjy1a4F9Z5FWLcMNT8KGmKc", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    ("12epp1iS4hFLKpugUcOBaXqbaUQUVuCSn", {"year": "2012", "semester": "1", "examtype": "중간고사"}),
    # 2013학년도 1학기 중간고사 (과학사) 정답과 해설
    ("1CcWg8ta8HBrPbJyIpZMH8GBsLAMClh0m", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("1ZJH2SwGK4k6OUs2xCBDPsbiHO6GVJbQG", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 2013학년도 1학기 중간고사 (과학사) 문제지
    ("15nSu5t0E2vTi0BzAAtco8hFWz8OQTxzK", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    ("11NJ8yJaVv6FyFhGVThwcl59hNG4KDH-A", {"year": "2013", "semester": "1", "examtype": "중간고사"}),
    # 2012학년도 2학기 기말고사 (과학사)과 정답 및 해설
    ("1o-qc8mJZBm4IWdfO_1OCQp2yQbG80d4G", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1OZcoDRJFdi-abXSihZEEQzzHeriHft5I", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1EBJid9YvZgRO-DZl73VJ2ZWMRetvod-v", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1OyzuL-N8H7nnlB10jvLX5lCPePJm_Kdn", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1krGkVY13_gxt0wJi-tQYq90KZqW5yFzx", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1cCjOMZKpJb5x6JveWQl4DfpB09zv6KDA", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    # 2012학년도 2학기 기말고사 (과학사) 문제지
    ("11alwNhpDu_VsN1AMudrAJDqk5TZ0Mx9n", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1eQNvelP33bwwPyw-tZ_E62fVvy4RzYYS", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1RxjJZniP9PS8xEKQc0f7JafVGVxeq0i7", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1RLICW-JuOPX0j7cMcOk0u6rulWPq404o", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1LzpI31RaMsgTdoAR3yjU5Gw7J6UVjbEo", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    ("1iTRfPHb_NWbc6RU8cvjYrB80kZHk0q6A", {"year": "2012", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 2학기 기말고사 (과학사) 정답과 해설
    ("1MBuduKdmn0sEwoWKHRd8zOEm3kvXMu8A", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1A9L8AD2u0bjBrsQBBX4ZHW_-kxKoztF3", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1fjM_6mAkEI6B6bksV4uZUFZjdOxhpzB5", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("18Sz-xnvU4pSyVFy8I9Yb5BlogZKa4PSX", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("18VtUvPda2f35Bcr3sWJrXY2TwBjvmEsw", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1cq-Ka79SeARB0_2-eUerfv8awyb0meet", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 2학기 기말고사 (과학사) 문제지
    ("16ynJ8jFZ0EFq2Oroy1y6zEpHl9fdIhRN", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1aNrYlwZ4vBREQygqTLrwqKa7yHbzYpB2", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1K-Ee8AuRedAgxn9tAp60dyaC_XyUFqGm", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1vr-GvSQ599xNHuLNgvJaSTuBBt_DvdNZ", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1fcQeoY5NwkN7X1EATORSFKMOMl-50CCm", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1Go9hvcul8ZGTLDBZrUCihu-G1k_2Wur5", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 2018학년도 2학기 기말고사 (고급화학Ⅱ) 문제지
    ("16MQfUdF4gujROR0t31bEdBukWMvbte9V", {"year": "2018", "semester": "2", "examtype": "기말고사"}),
    ("13-a8Ts8Sti2W1B41ZOhZqxIMUBXqGTBd", {"year": "2018", "semester": "2", "examtype": "기말고사"}),
    ("1f9d6CKrx4muDco59w4b2ih7-mrWer1l_", {"year": "2018", "semester": "2", "examtype": "기말고사"}),
    ("1MGfDEINUW8cRCeQ9wdaUksxTxc7J0vJM", {"year": "2018", "semester": "2", "examtype": "기말고사"}),
    ("1E-40O96O6z0zZnDg7iQNaAWvVeC6w2Y0", {"year": "2018", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 2학기 기말고사 (유기화학) 문제지
    ("1z4WT73-Y29NG8qLALgTP5Ztiaj6YbqZ5", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1-wRa_6eGUssWh4FdwOR_0mglLf1zEk6l", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1muCN5VsdDC-BbFcModjIrhhIASR4Fhy3", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("18zM-HlA_7J9vGD3ABerYBYBW2CFlaMJY", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("19PETuodN1kE7A8-CmzhgaS-Db5u4o147", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 2013학년도 2학기 기말고사 (유기화학)과 정답 및 해설
    ("1Xhx6JGNQXUv2JpuVEx7l8PvXsq7p_elz", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1rUIoq72uPHzdtvyOJdclu3GDmLvncBWE", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1di9X6kNJ6fgDN6TxV_F6Qmoq9vWGt8Ge", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1dQ42_eq1-ZmUIxshRsNLQ90UWQxe92e2", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1UqRCnBnkm5M7hBV3alE-AmQ5L4USvFnd", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    ("1p6NOG-wstb0yR8wvHVfzGk3HdBt7cYEW", {"year": "2013", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2015학년도 2학기 기말고사 (고급생명과학 II), 2015년 12월 2일.
    # 앞서 파일명 앞부분만 보고 1학기로 잘못 잡았던 것을 바로잡는다
    # ("...(B4).pdf"는 1학기, "...(B4)11.pdf"는 2학기로 서로 다른 파일이다).
    ("1psDigmfJXgvPmlo779SufCTxe7KCx0zR", {"year": "2015", "semester": "2", "examtype": "기말고사"}),
    ("1-Lqs9ND-0P9-X8zX8by1Vsaau2NMPzpX", {"year": "2015", "semester": "2", "examtype": "기말고사"}),
    # 표지: 2023학년도 1학기 기말고사 (미적분학II)과 정답및해설, 2023년 6월 28일 - 파일명의 2021이 틀림
    ("1LsRsgmhQK5LYmmazfDXXdr25Pjmc0nDz", {"year": "2023", "semester": "1", "examtype": "기말고사"}),
    ("14NU9EUEy9boGr-NCERS4cp3uCISY4LqE", {"year": "2023", "semester": "1", "examtype": "기말고사"}),
    ("1RwleFqs95P-PqeSM91A_MQAu2wx8TtVW", {"year": "2023", "semester": "1", "examtype": "기말고사"}),
    ("1-3XASuMT4fCqkpuQpXX_L8hVWarwRzUd", {"year": "2023", "semester": "1", "examtype": "기말고사"}),
    # 표지: 2023학년도 1학기 중간고사 (영어I)과 모범답안 및 해설, 2023년 4월 17일 - 파일명의 2024가 틀림
    ("1DkbYNUNMohn6EHCiqQl01dq4jOuAozWX", {"year": "2023", "semester": "1", "examtype": "중간고사"}),
    ("10IpVE6otvqJSXYuNJMstti2Qb7uYwv0H", {"year": "2023", "semester": "1", "examtype": "중간고사"}),
    ("1yQK5HBtxOFxN6msW5TDnI36-PhZYfdUU", {"year": "2023", "semester": "1", "examtype": "중간고사"}),
    ("10VoscZDGjC-296g7_R4jMZmr3L2u6iyc", {"year": "2023", "semester": "1", "examtype": "중간고사"}),
    # 영어1 1학기 중간 해설이 2023년 것과 2024년 것 두 벌 있는데 이름이 서로
    # 엇갈려 있었다. 이 파일은 PDF 메타데이터가 2024년 문제지와 같은 도구·같은
    # 날짜(iLovePDF, 2025-03-15)로 찍혀 있고, 표지가 읽히는 다른 한 벌은
    # 2023년으로 확인됐다. 그래서 이쪽을 2024년으로 본다.
    ("1l9GoIZD_xlTsJ6vHD8iZ6F6nWKFZHMOj", {"year": "2024", "semester": "1", "examtype": "중간고사"}),
    ("1b0yfFGoZtUglo-xZ6dXE1-2hKmMnYf4D", {"year": "2024", "semester": "1", "examtype": "중간고사"}),
    ("1IDbsqyLnJGXZBvgTmICH_BVmh0QdH8VN", {"year": "2024", "semester": "1", "examtype": "중간고사"}),
]

for _fid, _fix in VERIFIED_FIXES:
    MANUAL_OVERRIDES.setdefault(_fid, {}).update(_fix)


def parse_filename(filename):
    # 확장자가 빠진 파일이 꽤 많다(예: "2024_1기말_과학사_문제지"). 아래 패턴들이
    # 전부 ".pdf"로 끝나도록 돼 있어서, 없으면 붙여서 맞춰본다.
    if not filename.lower().endswith(".pdf"):
        filename = filename + ".pdf"
    for pat in PATTERNS:
        m = pat.match(filename)
        if m:
            groups = m.groupdict()
            if "yy" in groups and groups.get("yy"):
                groups["year"] = str(2000 + int(groups["yy"]))
            if "sem2" in groups and groups.get("sem2"):
                groups["semester"] = str(int(groups["sem2"]))
            # 정규식이 "맞긴 맞았는데" 값이 말이 안 되는 경우가 있다. 그냥 두면
            # parsed_ok=True로 확정돼버려서 fallback도 안 타고 틀린 값이 남는다.
            if not _plausible(groups):
                continue
            if pat is PATTERN_E:
                # 가운데 숫자는 학기가 아니라 시험 회차다 (EXAM_ORDINAL 주석 참고)
                slot = EXAM_ORDINAL.get(groups.get("semester"))
                if not slot:
                    continue
                groups["semester"], groups["examtype"] = slot
            # "2011-1학기기말-영어1.pdf"(J), "2012...중간고사(중국어).pdf"(P)처럼
            # 문서유형 칸이 비어 있는 형식은 시험지 본체를 뜻한다. 같은 시험의
            # 해설은 늘 "-모범답안"이 붙은 별도 파일로 존재하는 걸 확인했다.
            if pat in (PATTERN_J, PATTERN_P) and not (groups.get("doctype") or "").strip():
                groups["doctype"] = "문제지"
            return groups
    return None


# 파싱 결과가 상식적인지 확인한다.
#  - 연도: "20141년중간" 같은 오타 파일에서 뒤로 밀려 "0141"이 잡히는 걸 막는다.
#  - 과목: "2011_1중간_기말_세포.pdf"는 칸이 하나 더 많아서 과목 자리에 "기말"이
#    들어간다. 이런 건 과목이 아니라 파싱 실패로 취급해야 한다.
_BAD_SUBJECT_WORDS = {"중간", "기말", "중간고사", "기말고사", "문제", "문제지",
                      "답안", "해설", "모범답안", "모범답안및해설", "정답"}


def _plausible(groups):
    year = groups.get("year")
    if year and not (year.isdigit() and 1990 <= int(year) <= 2100):
        return False
    subj = (groups.get("subject_raw") or "").strip()
    if subj and subj in _BAD_SUBJECT_WORDS:
        return False
    return True


def fallback_parse(filename):
    year_m = YEAR_ANYWHERE_RE.search(filename) or BARE_YEAR_RE.search(filename)
    doctype = next((kw for kw in DOCTYPE_KEYWORDS if kw in filename), None)
    sem_ex_m = SEM_EXAMTYPE_ANYWHERE_RE.search(filename)
    if sem_ex_m:
        semester = sem_ex_m.group("semester") or sem_ex_m.group("semester2")
        examtype = sem_ex_m.group("examtype") or sem_ex_m.group("examtype2")
    else:
        semester = None
        ex_m = EXAMTYPE_ANYWHERE_RE.search(filename)
        examtype = ex_m.group(1) if ex_m else None
    return {
        "year": year_m.group(1) if year_m else None,
        "doctype": doctype,
        "semester": semester,
        "examtype": examtype,
    }


def folder_semester_examtype(folder_path):
    for seg in folder_path:
        fm = FOLDER_EXAM_RE.search(seg)
        if fm:
            return fm.group("semester"), fm.group("examtype") + "고사"
    return None, None


# ---- 과목 이름 뽑기 --------------------------------------------------------
# 대부분의 분류는 "분류 / 과목 / N학기 X고사 / ..." 구조라 folder_path[1]이 과목이지만,
# 창의융합특강만 "창의융합특강 / N학기 X고사 / 창융특 / 실제과목 / ..." 구조라서
# folder_path[1]을 그냥 쓰면 시험 폴더명("1학기 기말고사")이 과목으로 잡힌다.
# 그래서 시험 폴더 / 분류명 반복 / 문서유형 폴더 / 연도범위 폴더를 건너뛰고
# 처음 나오는 "진짜 이름"을 과목으로 쓴다.
SUBJECT_SKIP_EXAM_RE = re.compile(r"\d\s*학기\s*(중간|기말)")
SUBJECT_SKIP_DOCTYPE_RE = re.compile(r"^(문제지|모범\s*답안.*|정답.*|해설.*)$")
# "2011년~2014년"뿐 아니라 "2015-2019", "2011-2019", "2015~2021년"처럼
# 년을 안 붙인 연도범위 폴더도 과목이 아니다.
SUBJECT_SKIP_YEARRANGE_RE = re.compile(r"^\d{4}\s*(년|[-~–])")
# 폴더에서 실제로 쓰이는 분류 축약어(과목명이 아니라 묶음 폴더)
CATEGORY_ALIASES = {"창의융합특강": ["창융특"]}

# "지필고사" 폴더 맨 앞에 오는 12개 분류. 경로 맨 앞이 이 중 하나가 아니면
# (학년/이수구분/시험회차 같은 것이면) 분류가 없는 구조로 본다.
CATEGORY_NAMES = [
    "국어", "수학", "물리", "화학", "생명과학", "지구과학",
    "정보", "사회", "외국어", "실험", "예체능", "창의융합특강", "창융특",
]
CATEGORY_NAME_RE = re.compile(r"^(" + "|".join(CATEGORY_NAMES) + r")$")


def derive_subject(folder_path, category):
    aliases = set(CATEGORY_ALIASES.get(category, [])) | {category}
    for seg in folder_path[1:]:
        s = seg.strip()
        if SUBJECT_SKIP_EXAM_RE.search(s):
            continue
        if s in aliases:
            continue
        if SUBJECT_SKIP_DOCTYPE_RE.match(s):
            continue
        if SUBJECT_SKIP_YEARRANGE_RE.match(s):
            continue
        # "창융특 고체물리"처럼 묶음 이름이 접두어로 붙은 경우 떼어낸다
        for a in aliases:
            if s.startswith(a + " "):
                s = s[len(a) + 1:].strip()
        return apply_subject_alias(re.sub(r"\s+", " ", s))
    return category


# "기말고사 기출" 쪽 경로 판별과 과목 추출.
# 경로가 "1학기 기말고사 기출 / 기본선택 / 물리학3 / 문제지" 처럼 생겨서,
# 분류(국어/물리/…)가 아예 없고 대신 이수 구분(기본선택/심화선택/N학년)이 온다.
# 과목은 문서유형·연도 폴더를 뺀 마지막 칸이다.
SECOND_ROOT_HEAD_RE = re.compile(r"\d\s*학기\s*(중간|기말)고사\s*기출")
SECOND_ROOT_TRACK_RE = re.compile(
    # 이수 구분·학년뿐 아니라 "창융특"처럼 분류 이름만 적힌 묶음 폴더도
    # 과목이 아니다(그 밑의 실제 과목 이름을 써야 한다)
    r"^(기본선택|심화선택|기본필수|심화필수|공통|\d학년|창융특|창의융합특강)$"
)


# 폴더 이름이 축약형이거나 오타인 경우. 왼쪽(공백 제거 기준)을 오른쪽으로 바꾼다.
# 축약형은 폴더에만 쓰이고 파일명에는 제대로 적혀 있는 경우가 많다.
SUBJECT_ALIASES = {
    "데공지능": "데이터와 인공지능",
    "공위적정": "공동체를 위한 적정기술 설계",
    "공위적성": "공동체를 위한 적정기술 설계",
    "정법": "정치와법",
    "확룰과통계": "확률과통계",       # 폴더 이름 오타(확률 -> 확룰)
    "기초통계학": "확률과통계",       # 같은 과목의 옛 이름
    "로봇공학기초실습2": "로봇공학실습2",
    "고급지구과학1,2": "고급지구과학",  # 두 과목을 한 폴더에 묶어둔 이름
    "양자정보특강": "양자정보특강1",     # 파일은 모두 양자정보특강1
    # 영어 표기로 적힌 파일이 섞여 있다 ("English Conversation I" = 영어회화1)
    "EnglishConversation1": "영어회화1",
    "EnglishConversation2": "영어회화2",
}

# 폴더 이름 끝에 시험 종류가 붙어버린 경우 ("국어1-중간" -> "국어1")
SUBJECT_EXAM_SUFFIX_RE = re.compile(r"[\s\-_]*(중간|기말)(고사)?$")
# 과목 이름 끝의 로마숫자는 아라비아 숫자로 통일한다 ("추상대수학 II" -> "추상대수학2")
SUBJECT_TRAILING_ROMAN_RE = re.compile(r"^(.*?)[\s]*(Ⅰ|Ⅱ|Ⅲ|Ⅳ|IV|III|II|I)$")
_ROMAN_TO_NUM = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4",
                 "I": "1", "II": "2", "III": "3", "IV": "4"}


def apply_subject_alias(subject):
    if not subject:
        return subject
    # 파일명에서 온 이름은 지저분한 경우가 많다.
    #   "창융특_분자건축" / "창융특4 최신화학연구논문읽기" -> 묶음 이름과 번호를 뗀다
    #   "(심리학)(최종)" -> 괄호와 꼬리표를 뗀다
    subject = re.sub(r"^(창의융합특강|창융특)\s*[0-9IVXⅠ-Ⅻ]*\s*[_\-\s]*", "", subject).strip()
    subject = re.sub(r"\((최종|수정|재시험)\)", "", subject).strip()
    # "생명과학3(2학년)"은 과목이 아니라 학년까지 적어둔 폴더 이름이다. 학년은
    # 파일명(subject_detail)에 남아 화면에서 따로 묶이므로 과목명에서는 뗀다.
    subject = re.sub(r"\s*\([1-3]\s*학년\)\s*$", "", subject).strip()
    if subject.startswith("(") and subject.endswith(")"):
        subject = subject[1:-1].strip()
    if not subject:
        return None
    # "국어1-중간"처럼 시험 종류가 붙어버린 폴더 이름을 먼저 정리
    stripped = SUBJECT_EXAM_SUFFIX_RE.sub("", subject).strip()
    if stripped and stripped != subject and not re.fullmatch(r"[\s\-_]*", stripped):
        subject = stripped
    # 과목 끝 로마숫자를 아라비아 숫자로 ("추상대수학 II" -> "추상대수학2")
    m = SUBJECT_TRAILING_ROMAN_RE.match(subject)
    if m and m.group(1).strip():
        subject = m.group(1).strip() + _ROMAN_TO_NUM[m.group(2)]
    key = re.sub(r"\s+", "", subject)
    if key in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[key]
    key2 = norm_subject(subject)
    return SUBJECT_ALIASES.get(key2, subject)


def derive_subject_second_root(folder_path):
    """분류가 없는 폴더 구조에서 과목을 뽑는다.
    '3학년 / 세계사 / 모범 답안 및 해설' 처럼 학년·문서유형·연도범위 폴더가
    섞여 있으므로 뒤에서부터 그것들을 건너뛰고 처음 나오는 이름을 쓴다.
    폴더에 과목이 아예 없는 경우(파일명에만 있는 경우)는 None을 돌려주고,
    호출한 쪽에서 파일명에서 뽑은 과목을 쓴다."""
    for seg in reversed(folder_path):
        s = seg.strip()
        if not s:
            continue
        if SUBJECT_SKIP_DOCTYPE_RE.match(s):
            continue
        if SUBJECT_SKIP_YEARRANGE_RE.match(s):
            continue
        if SECOND_ROOT_TRACK_RE.match(s):
            continue
        if SECOND_ROOT_HEAD_RE.search(s):
            continue
        # "2024_1학기 기말 모범답안"처럼 시험 회차를 적어둔 묶음 폴더도 과목이 아니다
        if re.search(r"\d{4}.*(중간|기말)", s):
            continue
        # "창융특 고체물리" -> "고체물리" (묶음 이름이 앞에 붙은 경우)
        for pre in ("창의융합특강", "창융특"):
            if s.startswith(pre + " "):
                s = s[len(pre):].strip()
                break
        return apply_subject_alias(re.sub(r"\s+", " ", s))
    return None


def fill_missing_categories(records):
    """분류가 없는 기록(기말고사 기출 쪽)을 과목 이름으로 채운다.
    지필고사 쪽에서 이미 '이 과목은 이 분류'라는 걸 알고 있으므로 그걸 쓴다."""
    from collections import Counter, defaultdict

    votes = defaultdict(Counter)
    for r in records:
        if r.get("category") and r.get("subject"):
            votes[norm_subject(r["subject"])][r["category"]] += 1
    table = {k: c.most_common(1)[0][0] for k, c in votes.items()}

    # 같은 과목인데 이름이 조금씩 다르게 적힌 경우가 많아서(현대문학은 "문학"
    # 안의 세부과목, 기초통계학=확률과통계, "창융특 고체물리"=고체물리,
    # 생명과학3(2학년)=생명과학3 …) 단계적으로 느슨하게 맞춰본다.
    detail_votes = defaultdict(Counter)
    for r in records:
        if r.get("category") and r.get("subject_detail"):
            detail_votes[norm_subject(r["subject_detail"])][r["category"]] += 1
    detail_table = {k: c.most_common(1)[0][0] for k, c in detail_votes.items()}

    def lookup(subject):
        cands = [subject]
        # "창융특 고체물리" / "창의융합특강 고체물리" 처럼 묶음 이름이 앞에 붙은 경우
        for pre in ("창융특", "창의융합특강"):
            if subject.startswith(pre):
                cands.append(subject[len(pre):].strip())
        # "생명과학3(2학년)" 처럼 괄호 설명이 붙은 경우
        cands.append(re.sub(r"\([^)]*\)", "", subject).strip())
        for c in cands:
            k = norm_subject(c)
            if k in table:
                return table[k]
            if k in detail_table:      # 세부과목 이름으로도 찾아본다(현대문학 등)
                return detail_table[k]
        # 부분 일치 (고급지구과학 ⊂ 고급지구과학1,2)
        k = norm_subject(subject)
        for known, cat in table.items():
            if k and (k in known or known in k):
                return cat
        # 폴더 이름에 오타가 있는 경우("확룰과 통계" = 확률과 통계).
        # 길이가 같고 한 글자만 다르면 같은 과목으로 본다.
        for known, cat in table.items():
            if len(known) == len(k) >= 3 and sum(a != b for a, b in zip(known, k)) == 1:
                return cat
        return None

    # "지필고사" 폴더에는 없고 다른 폴더에만 있는 과목이라 대응표로는 못 찾는다.
    # (객체지향프로그래밍은 정보 계열, 경제학은 사회 계열)
    EXTRA_CATEGORY = {
        "객체지향프로그래밍": "정보",
        "경제학": "사회",
        # 시험지를 열어보니 수필 고쳐쓰기·칼럼 쓰기 문제였다. 영작문이 아니라
        # 국어 작문이다(이름이 비슷해 외국어로 잡히고 있었음).
        "작문": "국어",
    }

    def category_from_path(r):
        direct = EXTRA_CATEGORY.get(re.sub(r"\s+", "", r.get("subject") or ""))
        if direct:
            return direct
        """대응표에 아예 없는 새 과목(객체지향프로그래밍 등)은 폴더 위치로 추정한다.
        '창융특' 폴더 밑에 있으면 창의융합특강이다."""
        for seg in r.get("folder_path") or []:
            s = seg.strip()
            if s in ("창융특", "창의융합특강") or s.startswith("창융특 "):
                return "창의융합특강"
        subj = r.get("subject") or ""
        if subj.startswith("창융특") or subj.startswith("창의융합특강"):
            return "창의융합특강"
        return None

    filled = unknown = 0
    for r in records:
        if r.get("category") or not r.get("subject"):
            continue
        # 확정해둔 과목은 대응표보다 먼저 본다. 안 그러면 이름이 비슷한 과목에
        # 부분 일치로 먼저 걸린다(작문 ⊂ 영작문 -> 외국어로 잘못 감).
        cat = EXTRA_CATEGORY.get(re.sub(r"\s+", "", r["subject"])) or lookup(r["subject"]) or category_from_path(r)
        if cat:
            r["category"] = cat
            filled += 1
        else:
            r["category"] = "(분류 미상)"
            unknown += 1
    return filled, unknown


def norm_subject(s):
    """과목 이름 비교용 정규화 - 띄어쓰기와 로마숫자 표기 차이를 없앤다."""
    s = re.sub(r"\s+", "", s or "")
    # 긴 것부터 바꿔야 한다. "I"를 먼저 바꾸면 "II"가 "11"이 돼버림.
    for a, b in (("Ⅳ", "4"), ("Ⅲ", "3"), ("Ⅱ", "2"), ("Ⅰ", "1"),
                 ("IV", "4"), ("III", "3"), ("II", "2"), ("I", "1")):
        s = s.replace(a, b)
    return s


# 사이트(index.html)가 실제로 쓰는 필드만 추린다. folder_path나 url 같은 건
# 길이가 길고 화면에서 안 쓰는데, 파일이 1만 개가 넘어가니 그대로 다 실으면
# data.js가 10MB를 넘어 첫 로딩이 눈에 띄게 느려진다.
# (전체 필드는 data.json에 그대로 남아 있고 review.html이 그걸 쓴다)
WEB_FIELDS = [
    "id", "filename", "category", "subject", "subject_detail",
    "year", "semester", "examtype", "doctype",
    "parsed_ok", "folder_mismatch", "duplicate_sibling_folder", "size", "md5",
]


# ---- 같은 과목 안에서 빈 칸 채우기 ------------------------------------------
# 문제지와 해설이 같은 시험인데도 파일명 표기가 서로 달라서 한쪽만 학기(또는 연도,
# 시험종류)를 못 읽는 경우가 많다. 예)
#   01_문제지_(중국어)_2015년 중간고사.pdf        -> 2015 / ?  / 중간고사
#   04_모범답안및해설(중국어)_2015년1중간고사.pdf -> 2015 / 1학기 / 중간고사
# 이러면 시험 키가 갈라져서 양쪽 다 "해설 없음 / 문제 없음"으로 뜬다.
# 그래서 값을 아는 형제 파일이 **딱 하나로 특정될 때만** 빈 칸을 옮겨 적는다.
# (후보가 둘 이상이면 어느 시험인지 알 수 없으므로 손대지 않는다.)
_EXAM_FIELDS = ("year", "semester", "examtype")


def unify_by_content(records):
    """내용이 완전히 같은(해시가 같은) 파일들은 같은 시험 것이다.

    같은 파일이 여러 폴더에 복사돼 있는데 폴더마다 이름이 조금씩 달라서,
    한 벌만 "2011_2기말..."로 읽혀 다른 시험으로 떨어져 나가는 일이 있다.
    (그러면 한쪽은 "문제 없음", 다른 쪽은 멀쩡한 짝으로 두 줄이 된다.)
    해시가 같으면 같은 파일이므로 다수결로 값을 맞춘다. 표지를 직접 보고
    확정한 것(MANUAL_OVERRIDES)은 표를 크게 쳐서 항상 이기게 한다.
    """
    from collections import Counter, defaultdict

    groups = defaultdict(list)
    for r in records:
        if r.get("md5"):
            groups[r["md5"]].append(r)

    changed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        votes = Counter()
        for r in group:
            key = (r.get("year"), r.get("semester"), r.get("examtype"))
            votes[key] += 10 if r["id"] in MANUAL_OVERRIDES else 1
        if len(votes) < 2:
            continue
        (best, top), (_, second) = votes.most_common(2)
        if top == second:
            continue          # 우열을 못 가리면 손대지 않는다
        for r in group:
            if (r.get("year"), r.get("semester"), r.get("examtype")) != best:
                r["year"], r["semester"], r["examtype"] = best
                changed += 1
    return changed


def fill_missing_exam_fields(records):
    by_subject = {}
    for r in records:
        by_subject.setdefault((r.get("category"), r.get("subject")), []).append(r)

    filled = 0
    for group in by_subject.values():
        # 세 값이 모두 있는 시험들만 "채워 넣을 정답 후보"로 삼는다
        complete = {
            tuple(r[f] for f in _EXAM_FIELDS)
            for r in group
            if all(r.get(f) for f in _EXAM_FIELDS)
        }
        if not complete:
            continue
        for r in group:
            known = {f: r.get(f) for f in _EXAM_FIELDS if r.get(f)}
            if len(known) == len(_EXAM_FIELDS) or not known:
                continue  # 이미 다 알거나, 아는 게 하나도 없어 단서가 없음
            cands = [
                key for key in complete
                if all(key[_EXAM_FIELDS.index(f)] == v for f, v in known.items())
            ]
            if len(cands) != 1:
                continue
            for i, f in enumerate(_EXAM_FIELDS):
                if not r.get(f):
                    r[f] = cands[0][i]
            r["filled_from_sibling"] = True
            filled += 1
    return filled


# ---- 내용이 없는 껍데기 파일 -------------------------------------------------
# 이름은 .pdf인데 실제로는 맥이 파일을 복사할 때 만드는 메타데이터 찌꺼기
# (AppleDouble - 파일 앞부분에 Mac OS X 서명이 들어있다)인 파일이 4개 있다.
# 4096바이트짜리 같은 내용 4벌이고 어떤 뷰어로도 열리지 않는다. 다음으로 작은
# 진짜 파일이 32KB라 크기만 봐도 확실히 구분된다.
# 같은 시험의 멀쩡한 문제지는 따로 있으니(물리학1 2012년 1학기 중간) 화면에서는 뺀다.
BROKEN_MD5 = {"99f5caf0747746a4d0f8bd979d9d305e"}


def is_broken(record):
    return record.get("md5") in BROKEN_MD5


def slim_for_web(records):
    return [{k: r.get(k) for k in WEB_FIELDS if r.get(k) is not None}
            for r in records if not is_broken(r)]


_SUBJ_NUM_RE = re.compile(r"^(.*?)([1-4])$")


def _base_and_num(subject):
    """'독서3' -> ('독서', '3'). 로마숫자도 숫자로 맞춰서 비교한다.
    '고급지구과학1,2'처럼 여러 번호를 묶어 적은 폴더는 번호를 뗀 이름만 돌려준다
    (어느 한 번호로 볼 수 없으니 파일명 쪽을 따르게 된다)."""
    s = norm_subject(subject or "")
    m = re.match(r"^(.*?)([1-4])(?:\s*[,·/]\s*[1-4])+$", s)
    if m:
        return (m.group(1), "")
    m = _SUBJ_NUM_RE.match(s)
    return (m.group(1), m.group(2)) if m else (s, "")


def split_numbered_variants(records):
    """폴더는 '독서1'인데 파일명은 '독서3'인 것들을 파일명 쪽으로 옮긴다.

    같은 이름에 번호만 다른 과목(독서1/독서3, 지구과학2/지구과학3 …)이
    한 폴더에 섞여 들어가 있는 경우가 많다. 이건 표기 흔들림이 아니라
    실제로 다른 과목이므로, 더 구체적인 파일명 쪽을 따른다.
    ('문학' 폴더 안의 '현대문학'처럼 이름 자체가 다른 건 건드리지 않는다 -
     그건 세부과목 묶음으로 화면에서 따로 보여주고 있다.)
    """
    # 먼저 "이 폴더 안에 실제로 번호가 여러 개 섞여 있는가"를 센다.
    # 번호 변형이 하나뿐이면(선형대수학 폴더에 선형대수학I만 있는 식) 표기 흔들림일
    # 뿐이라 나누면 안 된다. 나누면 5개짜리 과목이 따로 생겨버린다.
    from collections import defaultdict

    nums_in_folder = defaultdict(set)
    for r in records:
        detail, subject = r.get("subject_detail"), r.get("subject")
        if not detail or not subject:
            continue
        base_s, _ = _base_and_num(subject)
        base_d, num_d = _base_and_num(detail)
        if base_s and base_s == base_d and num_d:
            nums_in_folder[(r.get("category"), base_s)].add(num_d)

    moved = 0
    for r in records:
        detail, subject = r.get("subject_detail"), r.get("subject")
        if not detail or not subject:
            continue
        base_s, num_s = _base_and_num(subject)
        base_d, num_d = _base_and_num(detail)
        if not (base_s and base_s == base_d and num_d and num_s != num_d):
            continue
        # 폴더에 번호가 없더라도(고급지구과학) 안에 1과 2가 같이 있으면 나눈다
        if len(nums_in_folder[(r.get("category"), base_s)] | {num_s} - {""}) < 2:
            continue
        # 파일명 표기 그대로 쓰면 "중국어II" 같은 로마숫자 이름이 별도 과목으로
        # 남아버린다(같은 과목인 "중국어2"와 갈라져서 문제/해설이 따로 뜸).
        r["subject"] = apply_subject_alias(detail) or detail
        moved += 1
    return moved


# "문학" 폴더는 사실상 고전문학/현대문학/현대문학2/현대문학3를 한꺼번에 담아둔
# 통이다(278개 중 243개가 그렇다). 다른 최상위 폴더에는 같은 파일이 "고전문학",
# "현대문학"이라는 제 이름의 폴더로도 들어있어서, 그냥 두면 똑같은 시험이
# "문학" 줄과 "현대문학" 줄로 두 번 나오고 양쪽 다 "문제 없음"이 뜬다.
# 그래서 파일명에 과목이 분명히 적혀 있으면 그 이름 쪽으로 옮긴다.
# (전체 과목을 훑어본 결과 이런 "통 폴더"는 문학뿐이라 여기만 처리한다.)
CONTAINER_SUBJECTS = {"문학"}


def split_container_subjects(records):
    known = set()
    for r in records:
        if r.get("subject"):
            known.add((r.get("category"), norm_subject(r["subject"])))

    moved = 0
    for r in records:
        subject, detail = r.get("subject"), r.get("subject_detail")
        if subject not in CONTAINER_SUBJECTS or not detail:
            continue
        cand = apply_subject_alias(detail)
        if not cand or norm_subject(cand) == norm_subject(subject):
            continue
        if (r.get("category"), norm_subject(cand)) not in known:
            continue
        r["subject"] = cand
        moved += 1
    return moved


def canonicalize_subjects(records):
    """같은 과목인데 표기만 다른 것을 한 이름으로 합친다.
    띄어쓰기 차이('우주론 I' / '우주론I')뿐 아니라 로마숫자 차이도 본다 -
    두 최상위 폴더가 서로 '국어I'과 '국어1'처럼 다르게 적어놔서, 그냥 두면
    똑같은 시험이 과목이 다르다는 이유로 두 줄로 갈라진다.
    표기는 실제로 가장 많이 쓰인 쪽을 대표로 삼는다(이름을 임의로 뭉개지 않음)."""
    from collections import Counter, defaultdict

    variants = defaultdict(Counter)
    for r in records:
        subj = r.get("subject")
        if not subj:
            continue
        key = (r.get("category"), norm_subject(subj).lower())
        variants[key][subj] += 1

    # 대표 표기는 많이 쓰인 순으로 고르되, 같은 횟수면 로마숫자(고급지구과학II)보다
    # 아라비아 숫자(고급지구과학2)를 쓴다. 화면에서 과목 목록이 뒤섞여 보이지 않게.
    def pick(counter):
        return sorted(
            counter.items(),
            key=lambda kv: (-kv[1], bool(re.search(r"[ⅠⅡⅢⅣIV]", kv[0])), kv[0]),
        )[0][0]

    canonical = {k: pick(c) for k, c in variants.items()}
    for r in records:
        subj = r.get("subject")
        if not subj:
            continue
        key = (r.get("category"), norm_subject(subj).lower())
        r["subject"] = canonical.get(key, subj)


def parse_record(filename, folder_path, drive_id, layout="분류먼저"):
    fname_meta = parse_filename(filename)
    parsed_ok = fname_meta is not None
    if not parsed_ok:
        fname_meta = fallback_parse(filename)
    # 공백 허용 정규식(년 뒤 공백, "N학기" 등) 때문에 그룹에 앞뒤 공백이 낄 수 있어서 정리
    for k, v in list(fname_meta.items()):
        if isinstance(v, str):
            fname_meta[k] = v.strip()

    # 최상위 폴더마다 구조가 다르다.
    #   지필고사 : 분류(국어/물리/…) / 과목 / N학기 X고사 / …  → 맨 앞이 분류
    #   나머지   : 3학년 / 세계사 / 모범 답안 및 해설 / …      → 분류가 없음
    # 후자는 경로에 분류가 아예 없어서, 과목만 뽑아두고 분류는 나중에
    # (지필고사에서 얻은 과목→분류 대응표로) 채운다.
    # reprocess.py처럼 folder_path만 가지고 다시 계산할 때는 layout을 모르므로,
    # 경로 맨 앞이 분류(국어/물리/…)가 아니라 학년·이수구분·시험회차면
    # "분류없음" 구조로 본다.
    if layout != "분류없음" and folder_path and not CATEGORY_NAME_RE.match(folder_path[0].strip()):
        layout = "분류없음"

    if layout == "분류없음":
        category = None
        subject = derive_subject_second_root(folder_path)
        if not subject:
            # 폴더에 과목이 없고 파일명에만 있는 경우
            # ("2024_1학기 기말 모범답안 / 05_모범답안및해설_(문학)_2024년1기말.pdf")
            subject = fname_meta.get("subject_raw")
    else:
        category = folder_path[0] if len(folder_path) > 0 else None
        # "창융특"은 창의융합특강의 축약 표기라 분류 이름을 정식 명칭으로 통일한다
        if category == "창융특":
            category = "창의융합특강"
        subject = derive_subject(folder_path, category) if category else None
        # "창융특" 폴더처럼 경로에 분류 이름만 있고 과목이 없으면, 과목 이름이
        # 분류와 똑같아져 버린다. 이럴 땐 파일명에 적힌 과목을 쓴다.
        if subject and subject == category and fname_meta.get("subject_raw"):
            subject = apply_subject_alias(fname_meta["subject_raw"])
    folder_semester, folder_examtype = folder_semester_examtype(folder_path)

    fname_semester = fname_meta.get("semester")
    fname_examtype_raw = fname_meta.get("examtype")
    fname_examtype = (
        fname_examtype_raw + "고사"
        if (fname_examtype_raw and not fname_examtype_raw.endswith("고사"))
        else fname_examtype_raw
    )

    # 파일명의 "N중간"/"N기말"에서 N은 실제로 학기를 정확히 가리킴(1중간=1학기
    # 중간고사, 2중간=2학기 중간고사) - 학교에서 실제로 쓰는 규칙이라고 확인받음.
    # 예전엔 "2학기 폴더 안 파일의 91%가 파일명엔 1로 박혀있다"는 걸 "파일명이
    # 불안정하다"는 뜻으로 잘못 해석해서 폴더 값을 우선시했었는데, 실제로는
    # 그 반대였음 - "N학기 중간/기말고사"라고 이름 붙은 폴더 안에 실제로는 두
    # 학기 파일이 섞여 들어가 있는 경우가 많아서(폴더 쪽이 부정확), 폴더 값으로
    # 덮어쓰면 서로 다른 학기 시험이 한 시험으로 잘못 합쳐짐. 그래서 semester도
    # examtype과 마찬가지로 파일명을 우선시하고, 폴더 값은 파일명에서 못 뽑았을 때만 쓴다.
    semester = fname_semester or folder_semester
    examtype = fname_examtype or folder_examtype

    # "폴더 불일치" 플래그는 examtype(중간/기말) 불일치일 때만 켠다.
    # semester(학기 숫자) 불일치는 표시값 계산(위)에는 여전히 반영하지만 플래그
    # 대상에서는 뺀다 - 실측 결과 폴더 불일치 1444개 중 89%(1285개)가 "학기
    # 숫자만" 다른 경우였는데, 이건 실제 오류라기보다 "N학기 중간/기말고사"라는
    # 폴더 자체가 여러 학기 파일을 같이 담는 통합 보관함으로 쓰이는 경우가
    # 많아서 생기는 흔한 현상임 (사이트에 보이는 학기 값 자체는 이미 파일명
    # 기준으로 정확함). 이걸 다 플래그에 넣으면 "정리 필요" 필터가 전체의
    # 43%를 차지하게 돼서 정작 진짜 이상한 파일(시험종류 자체가 다른 159개)이
    # 묻혀버림.
    mismatch = bool(
        fname_examtype and folder_examtype and fname_examtype != folder_examtype
    )

    doctype = fname_meta.get("doctype")
    # 정규식이 잡은 doctype이 실제 문서유형 단어가 아닐 때가 있다. 예를 들어
    # "2024_2기말_창융특XXVII_일반상대론_문제지.pdf"는 칸이 하나 더 많아서
    # doctype 자리에 과목명("일반상대론")이 들어간다. 파일명 안에 문서유형
    # 단어가 분명히 보이면 그걸 우선한다.
    doctype = normalize_doctype(doctype)
    if not doctype or not any(w in doctype for w in ("문제", "답안", "해설", "정답")):
        kw = next((k for k in DOCTYPE_KEYWORDS if k in filename), None)
        if not kw:
            # "원안", "시험지"처럼 다르게 부른 이름도 파일명에서 찾아본다
            kw = next((normalize_doctype(w) for w in DOCTYPE_SYNONYMS if w in filename), None)
        if kw:
            doctype = kw

    if doctype is None:
        for seg in folder_path:
            if "문제지" in seg:
                doctype = "문제지"
                break
            if "답안" in seg or "해설" in seg:
                doctype = "모범답안및해설"
                break

    # 파일명 속 과목 표기(예: "고전문학"/"현대문학") - subject보다 세분화된 경우가
    # 있음 (한 폴더 안에 여러 세부과목이 섞여 있는 "문학" 케이스). subject/시험
    # 매칭(examKey)에는 안 쓰고, 화면에서 한 시험 줄에 버튼이 너무 많이 몰릴 때
    # 표시용 소그룹핑에만 쓴다 - subject_raw를 매칭 키에 넣으면 표기 흔들림
    # (고급물리학I/1/Ⅰ 등) 때문에 오히려 문제지/해설 페어가 더 많이 깨짐을
    # 실측으로 확인함(정상 페어 1414->1476인데 깨진 페어도 123->196으로 더 늘어남).
    subject_detail = fname_meta.get("subject_raw") or None

    rec = {
        "id": drive_id,
        "md5": MD5_CACHE.get(drive_id),
        "filename": filename,
        "category": category,
        "subject": subject,
        "subject_detail": subject_detail,
        "year": fname_meta.get("year"),
        "semester": semester,
        "examtype": examtype,
        "doctype": doctype,
        "seq": fname_meta.get("seq"),
        "paper": fname_meta.get("paper"),
        "note": fname_meta.get("suffix") or None,
        "parsed_ok": parsed_ok,
        "folder_mismatch": mismatch,
        "folder_path": folder_path,
        "url": f"https://drive.google.com/file/d/{drive_id}/view",
    }

    if drive_id in MANUAL_OVERRIDES:
        rec.update(MANUAL_OVERRIDES[drive_id])
        # 실제 PDF 표지를 열어서 확인한 값이라 최종 확정으로 취급 - 폴더 불일치
        # 계산도 지금 값(정답) 기준으로 다시 해서 "폴더 쪽이 틀렸다"는 신호가
        # 계속 정확하게 남게 한다.
        rec["parsed_ok"] = True
        # 위 mismatch 계산과 동일하게 examtype 불일치만 플래그로 취급
        _, folder_examtype = folder_semester_examtype(folder_path)
        rec["folder_mismatch"] = bool(folder_examtype and folder_examtype != rec["examtype"])

    return rec


# ---- 드라이브 크롤링 --------------------------------------------------------

def get_service():
    creds = None
    try:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    except FileNotFoundError:
        pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def list_children(service, folder_id):
    files = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            # md5Checksum은 드라이브가 이미 갖고 있는 값이라 파일을 받지 않아도
            # 그냥 얻을 수 있다. 이름만 다르고 내용은 같은 중복을 합치는 데 쓴다.
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, md5Checksum)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    # 드라이브에 올라온 이름이 NFD(자모 분리)인 경우가 섞여 있어서 전부 NFC로
    # 통일한다 - 안 그러면 정규식 속 리터럴 한글과 안 맞아 파싱이 실패한다.
    for f in files:
        f["name"] = unicodedata.normalize("NFC", f["name"])
    return files


def crawl(service, folder_id, folder_path, layout="분류먼저"):
    records = []
    children = list_children(service, folder_id)

    # 같은 부모 밑에 이름이 똑같은 폴더가 여러 개 있으면 인수인계 중 중복 생성된
    # 폴더일 가능성이 높음 -> 그 안의 모든 파일에 표시를 남긴다.
    folder_children = [c for c in children if c["mimeType"] == "application/vnd.google-apps.folder"]
    name_counts = {}
    for c in folder_children:
        name_counts[c["name"]] = name_counts.get(c["name"], 0) + 1
    duplicate_names = {name for name, cnt in name_counts.items() if cnt > 1}

    for child in children:
        if child["mimeType"] == "application/vnd.google-apps.folder":
            sub_records = crawl(service, child["id"], folder_path + [child["name"]], layout)
            if child["name"] in duplicate_names:
                for r in sub_records:
                    r["duplicate_sibling_folder"] = True
                    # 이름만으론 어느 중복 인스턴스인지 구분이 안 되므로 실제
                    # 폴더 ID를 남겨서 정리 보고서에서 인스턴스별로 묶을 수 있게 함
                    r["duplicate_folder_id"] = child["id"]
                    r["duplicate_folder_modified"] = child.get("modifiedTime")
            records.extend(sub_records)
        elif child["mimeType"] == "application/pdf":
            if child["name"].startswith("._"):
                # macOS 리소스 포크 잔여 파일(AppleDouble) - 실제 문서가 아님
                continue
            rec = parse_record(child["name"], folder_path, child["id"], layout)
            rec["duplicate_sibling_folder"] = False
            rec["duplicate_folder_id"] = None
            rec["duplicate_folder_modified"] = None
            rec["modified_time"] = child.get("modifiedTime")
            rec["size"] = int(child["size"]) if child.get("size") else None
            # 드라이브가 준 해시를 쓰고, 없으면 예전에 직접 받아 계산해둔 값을 쓴다
            rec["md5"] = child.get("md5Checksum") or MD5_CACHE.get(child["id"])
            records.append(rec)
    return records


def main():
    print("드라이브 인증 중... (브라우저 창이 열립니다)")
    service = get_service()
    print("크롤링 시작... (파일 수에 따라 몇 분 걸릴 수 있음)")
    records = []
    for label, root_id, layout in ROOT_FOLDERS:
        print(f"  [{label}] 훑는 중...")
        got = crawl(service, root_id, [], layout)
        print(f"  [{label}] {len(got)}개")
        records.extend(got)
    filled, unknown = fill_missing_categories(records)
    if filled or unknown:
        print(f"  분류가 없던 기록 {filled}개는 과목 이름으로 채움, {unknown}개는 못 찾음")
    moved = split_numbered_variants(records)
    if moved:
        print(f"  폴더와 파일명의 과목 번호가 다른 {moved}개는 파일명 쪽으로 옮김")
    canonicalize_subjects(records)
    cont = split_container_subjects(records)
    if cont:
        print(f"  '문학'처럼 여러 과목을 담고 있던 폴더에서 {cont}개를 제 과목으로 옮김")
    same = unify_by_content(records)
    if same:
        print(f"  내용이 같은 파일끼리 연도/학기를 맞춘 기록 {same}개")
    sib = fill_missing_exam_fields(records)
    if sib:
        print(f"  같은 과목의 형제 파일에서 빈 칸을 채운 기록 {sib}개")
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    # index.html은 CORS 문제 없이 그냥 더블클릭으로도 열리도록 JSON을 JS 변수로도 저장
    with open("data.js", "w", encoding="utf-8") as f:
        # 브라우저가 data.js를 캐시해서 옛날 데이터를 보고 있는 건지 화면에서
        # 바로 구분할 수 있도록 생성 시각도 같이 넣는다
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        f.write(f'var EXAM_DATA_VERSION = "{stamp}";\n')
        f.write("var EXAM_DATA = ")
        json.dump(slim_for_web(records), f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    total = len(records)
    unparsed = sum(1 for r in records if not r["parsed_ok"])
    mismatched = sum(1 for r in records if r["folder_mismatch"])
    duplicated = sum(1 for r in records if r.get("duplicate_sibling_folder"))
    print(f"완료: 총 {total}개 파일, data.json 생성됨")
    if unparsed:
        print(f"- {unparsed}개는 파일명 패턴이 안 맞아서 부분 정보만 채워짐 (parsed_ok=false)")
    if mismatched:
        print(f"- {mismatched}개는 폴더명과 파일명의 학기/시험종류가 서로 다름 (folder_mismatch=true)")
        print("  -> 잘못된 폴더에 들어간 파일일 가능성이 높으니 확인 추천")
    if duplicated:
        print(f"- {duplicated}개는 형제 폴더가 이름이 같아서 인수인계 중 중복 생성된 폴더로 추정됨 (duplicate_sibling_folder=true)")
        print("  -> 두 폴더 내용을 비교해서 병합/삭제 후보로 검토 추천")


if __name__ == "__main__":
    sys.exit(main())
