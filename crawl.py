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
ROOT_FOLDERS = [
    ("지필고사", "1_W8bDBPF5zGU3B9JuAt5g2Ycsjq7VpkH"),
    ("기말고사 기출", "11A09DJOktS1l6f3ilFuGdGF5ZnZHpSxO"),
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
# O) "11-1한국사기말고사문제.pdf" (두 자리 연도-학기 축약형, 20xx로 간주)
PATTERN_O = re.compile(
    r"^(?P<yy>\d{2})-(?P<semester>\d)(?P<subject_raw>[^0-9]+?)(?P<examtype>중간|기말)고사(?P<doctype>.+)\.pdf$"
)
# F) 2011~2014년 옛날 파일: "역학1모범답안201101중간.pdf" (과목+문서유형+연도+월(01/02로
#    학기를 나타냄)+중간/기말, 구분자 없음)
PATTERN_F = re.compile(
    r"^(?P<subject_raw>.+?)(?P<doctype>모범답안및해설|모범답안|모법답안|문제지|시험지)"
    r"(?P<year>\d{4})(?P<sem2>0[12])(?P<examtype>중간|기말)(?P<suffix>.*)\.pdf$"
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
# 순서 중요: 더 구체적인(오탈자 특정) 패턴을 먼저, 느슨한 패턴을 나중에 시도한다.
PATTERNS = [
    PATTERN_A, PATTERN_B, PATTERN_C, PATTERN_D, PATTERN_E,
    PATTERN_I, PATTERN_L, PATTERN_M, PATTERN_N, PATTERN_O,
    PATTERN_F, PATTERN_G, PATTERN_H, PATTERN_J, PATTERN_K,
]

FOLDER_EXAM_RE = re.compile(r"(?P<semester>\d)학기\s*(?P<examtype>중간|기말)고사")
YEAR_ANYWHERE_RE = re.compile(r"(\d{4})년")
# "년" 바로 뒤가 아니어도(예: "2011학년도...", 구분자 없이 붙어쓴 옛날 파일) 최소한
# 연도 후보는 건지도록 하는 2차 fallback. 19xx/20xx 범위로 오탐 위험을 줄인다.
BARE_YEAR_RE = re.compile(r"((?:19|20)\d{2})")
# 완전 파싱은 안 돼도 "중간"/"기말" 단어와 그 앞의 학기 숫자가 파일명에 그냥 텍스트로
# 보이는 경우가 있음 - 이럴 땐 폴더명보다 이 값을 믿는 게 낫다(폴더명이 실제로 자주
# 틀리다는 걸 확인했기 때문). 예: 파일명엔 분명히 "중간"이라고 쓰여 있는데 폴더는
# "기말고사"인 경우, 폴더 대신 파일명 쪽을 신뢰해야 함.
SEM_EXAMTYPE_ANYWHERE_RE = re.compile(r"(?<!\d)(?P<semester>\d)\s*학?기?\s*(?P<examtype>중간|기말)")
EXAMTYPE_ANYWHERE_RE = re.compile(r"(중간|기말)")
DOCTYPE_KEYWORDS = [
    "모범답안및해설", "모범답안", "해설", "정답지", "답안지", "문제지",
    # 아래 둘은 오타("모법답안" 등)나 "전자기-문제.pdf"처럼 축약된 이름을 위한
    # 넓은 catch-all - 위의 구체적인 키워드가 먼저 매칭되므로 순서상 안전함
    "답안", "문제",
]


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
            return groups
    return None


def fallback_parse(filename):
    year_m = YEAR_ANYWHERE_RE.search(filename) or BARE_YEAR_RE.search(filename)
    doctype = next((kw for kw in DOCTYPE_KEYWORDS if kw in filename), None)
    sem_ex_m = SEM_EXAMTYPE_ANYWHERE_RE.search(filename)
    if sem_ex_m:
        semester, examtype = sem_ex_m.group("semester"), sem_ex_m.group("examtype")
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
SUBJECT_SKIP_YEARRANGE_RE = re.compile(r"^\d{4}\s*년")
# 폴더에서 실제로 쓰이는 분류 축약어(과목명이 아니라 묶음 폴더)
CATEGORY_ALIASES = {"창의융합특강": ["창융특"]}


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
        return re.sub(r"\s+", " ", s)
    return category


# "기말고사 기출" 쪽 경로 판별과 과목 추출.
# 경로가 "1학기 기말고사 기출 / 기본선택 / 물리학3 / 문제지" 처럼 생겨서,
# 분류(국어/물리/…)가 아예 없고 대신 이수 구분(기본선택/심화선택/N학년)이 온다.
# 과목은 문서유형·연도 폴더를 뺀 마지막 칸이다.
SECOND_ROOT_HEAD_RE = re.compile(r"\d\s*학기\s*(중간|기말)고사\s*기출")
SECOND_ROOT_TRACK_RE = re.compile(r"^(기본선택|심화선택|기본필수|심화필수|공통|\d학년)$")


def derive_subject_second_root(folder_path):
    for seg in reversed(folder_path[1:]):
        s = seg.strip()
        if SUBJECT_SKIP_DOCTYPE_RE.match(s):
            continue
        if SUBJECT_SKIP_YEARRANGE_RE.match(s):
            continue
        if SECOND_ROOT_TRACK_RE.match(s):
            continue
        return re.sub(r"\s+", " ", s)
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
        # 마지막으로 부분 일치 (고급지구과학 ⊂ 고급지구과학1,2)
        k = norm_subject(subject)
        for known, cat in table.items():
            if k and (k in known or known in k):
                return cat
        return None

    filled = unknown = 0
    for r in records:
        if r.get("category") or not r.get("subject"):
            continue
        cat = lookup(r["subject"])
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

    canonical = {k: c.most_common(1)[0][0] for k, c in variants.items()}
    for r in records:
        subj = r.get("subject")
        if not subj:
            continue
        key = (r.get("category"), norm_subject(subj).lower())
        r["subject"] = canonical.get(key, subj)


def parse_record(filename, folder_path, drive_id):
    fname_meta = parse_filename(filename)
    parsed_ok = fname_meta is not None
    if not parsed_ok:
        fname_meta = fallback_parse(filename)
    # 공백 허용 정규식(년 뒤 공백, "N학기" 등) 때문에 그룹에 앞뒤 공백이 낄 수 있어서 정리
    for k, v in list(fname_meta.items()):
        if isinstance(v, str):
            fname_meta[k] = v.strip()

    # 두 최상위 폴더의 구조가 다르다.
    #   지필고사      : 분류(국어/물리/…) / 과목 / N학기 X고사 / …   → 맨 앞이 분류
    #   기말고사 기출 : N학기 기말고사 기출 / 기본선택 / 과목 / 문제지 → 분류가 없음
    # 후자는 경로에 분류가 아예 없어서, 과목만 뽑아두고 분류는 나중에
    # (지필고사에서 얻은 과목→분류 대응표로) 채운다.
    if folder_path and SECOND_ROOT_HEAD_RE.search(folder_path[0]):
        category = None
        subject = derive_subject_second_root(folder_path)
    else:
        category = folder_path[0] if len(folder_path) > 0 else None
        subject = derive_subject(folder_path, category) if category else None
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
    if not doctype or not any(w in doctype for w in ("문제", "답안", "해설", "정답")):
        kw = next((k for k in DOCTYPE_KEYWORDS if k in filename), None)
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


def crawl(service, folder_id, folder_path):
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
            sub_records = crawl(service, child["id"], folder_path + [child["name"]])
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
            rec = parse_record(child["name"], folder_path, child["id"])
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
    for label, root_id in ROOT_FOLDERS:
        print(f"  [{label}] 훑는 중...")
        got = crawl(service, root_id, [])
        print(f"  [{label}] {len(got)}개")
        records.extend(got)
    filled, unknown = fill_missing_categories(records)
    if filled or unknown:
        print(f"  분류가 없던 기록 {filled}개는 과목 이름으로 채움, {unknown}개는 못 찾음")
    canonicalize_subjects(records)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    # index.html은 CORS 문제 없이 그냥 더블클릭으로도 열리도록 JSON을 JS 변수로도 저장
    with open("data.js", "w", encoding="utf-8") as f:
        # 브라우저가 data.js를 캐시해서 옛날 데이터를 보고 있는 건지 화면에서
        # 바로 구분할 수 있도록 생성 시각도 같이 넣는다
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        f.write(f'var EXAM_DATA_VERSION = "{stamp}";\n')
        f.write("var EXAM_DATA = ")
        json.dump(records, f, ensure_ascii=False)
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
