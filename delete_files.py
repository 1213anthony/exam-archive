"""
선택한 기출문제 파일을 구글 드라이브 휴지통으로 보내기
====================================================
index.html에서 체크박스로 고른 뒤 "삭제 목록 내보내기"를 누르면 받아지는
to_delete.txt를 읽어서, 해당 파일들을 드라이브 휴지통으로 옮긴다.

안전장치
--------
- **완전 삭제가 아니라 휴지통으로 이동**한다(trashed=true). 드라이브 휴지통에서
  30일 안에는 그대로 복구할 수 있고, 이 스크립트로도 되돌릴 수 있다.
- crawl.py가 쓰는 token.json(읽기 전용)은 건드리지 않는다. 쓰기 권한은
  token_write.json에 따로 받아두므로, 크롤러는 앞으로도 절대 쓰기를 못 한다.
- 지우기 전에 목록을 전부 보여주고, 사용자가 직접 "삭제"라고 타이핑해야 진행된다.
- 실제로 지운 내역은 delete_log.jsonl에 한 줄씩 남는다(되돌릴 때 필요).

사용법
------
    python delete_files.py to_delete.txt          # 목록 확인 후 휴지통으로
    python delete_files.py to_delete.txt --dry-run  # 뭐가 지워질지만 보기
    python delete_files.py --undo delete_log.jsonl  # 마지막 삭제 되돌리기

처음 한 번은 브라우저가 열려서 로그인/권한 승인을 해야 한다(쓰기 권한이라
읽기 전용 때와 별도로 승인이 필요함).
"""
import argparse
import datetime
import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 파일을 휴지통으로 보내려면 읽기 전용으로는 안 되고 쓰기 권한이 필요하다.
WRITE_SCOPES = ["https://www.googleapis.com/auth/drive"]
WRITE_TOKEN = "token_write.json"
LOG_PATH = "delete_log.jsonl"


def get_service():
    creds = None
    if os.path.exists(WRITE_TOKEN):
        creds = Credentials.from_authorized_user_file(WRITE_TOKEN, WRITE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                sys.exit("credentials.json이 없습니다. crawl.py 때 쓰던 파일을 같은 폴더에 두세요.")
            print("드라이브 쓰기 권한 승인이 필요합니다. 브라우저가 열립니다...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", WRITE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(WRITE_TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def load_targets(path):
    """to_delete.txt 읽기. '파일ID<TAB>파일명' 또는 파일ID만 있는 줄 모두 허용."""
    targets = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            targets.append({"id": parts[0].strip(), "name": parts[1].strip() if len(parts) > 1 else ""})
    return targets


def confirm(prompt, expect):
    try:
        answer = input(prompt).strip()
    except EOFError:
        return False
    return answer == expect


def do_trash(targets, dry_run):
    print(f"\n다음 {len(targets)}개 파일을 드라이브 휴지통으로 보냅니다:\n")
    for i, t in enumerate(targets, 1):
        print(f"  {i:3d}. {t['name'] or t['id']}")

    if dry_run:
        # 목록만 보는 단계에서는 드라이브에 접속조차 하지 않는다(권한 승인도 불필요)
        print("\n[--dry-run] 실제로는 아무것도 지우지 않았습니다. 드라이브에 접속도 하지 않았습니다.")
        return

    # 여기서부터 실제 쓰기 - 확인을 받은 뒤에야 인증한다

    print("\n※ 완전 삭제가 아니라 휴지통으로 갑니다. 드라이브 휴지통에서 되돌릴 수 있고,")
    print(f"   이 스크립트로도 되돌릴 수 있습니다:  python delete_files.py --undo {LOG_PATH}")
    if not confirm('\n정말 진행하려면 "삭제" 라고 입력하세요: ', "삭제"):
        sys.exit("취소했습니다. 아무것도 지우지 않았습니다.")

    service = get_service()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    done = failed = 0
    with open(LOG_PATH, "a", encoding="utf-8") as log:
        for t in targets:
            try:
                # 파일 정보를 먼저 확보해둔다(되돌릴 때 뭐였는지 알아야 하니까)
                meta = service.files().get(fileId=t["id"], fields="id,name,parents").execute()
                service.files().update(fileId=t["id"], body={"trashed": True}).execute()
                log.write(json.dumps(
                    {"at": stamp, "action": "trash", "id": meta["id"],
                     "name": meta.get("name"), "parents": meta.get("parents")},
                    ensure_ascii=False) + "\n")
                done += 1
                print(f"  휴지통으로 이동: {meta.get('name')}")
            except Exception as e:
                failed += 1
                print(f"  실패: {t['name'] or t['id']} - {e}")

    print(f"\n완료: {done}개 이동, {failed}개 실패")
    if done:
        print(f"내역은 {LOG_PATH}에 기록했습니다.")
        print("사이트에 반영하려면 크롤링을 다시 돌리세요:  python crawl.py")


def do_undo(log_path):
    if not os.path.exists(log_path):
        sys.exit(f"{log_path}가 없습니다.")
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    trashed = [e for e in entries if e.get("action") == "trash"]
    if not trashed:
        sys.exit("되돌릴 삭제 기록이 없습니다.")

    last_at = trashed[-1]["at"]
    batch = [e for e in trashed if e["at"] == last_at]
    print(f"\n{last_at}에 휴지통으로 보낸 {len(batch)}개를 복구합니다:\n")
    for e in batch:
        print(f"  - {e.get('name')}")
    if not confirm('\n복구하려면 "복구" 라고 입력하세요: ', "복구"):
        sys.exit("취소했습니다.")

    service = get_service()
    done = 0
    for e in batch:
        try:
            service.files().update(fileId=e["id"], body={"trashed": False}).execute()
            done += 1
            print(f"  복구됨: {e.get('name')}")
        except Exception as ex:
            print(f"  실패: {e.get('name')} - {ex}")
    print(f"\n{done}개 복구 완료")


def main():
    ap = argparse.ArgumentParser(description="선택한 파일을 드라이브 휴지통으로 보냅니다")
    ap.add_argument("list_file", nargs="?", help="삭제할 파일 목록(to_delete.txt)")
    ap.add_argument("--dry-run", action="store_true", help="실제로 지우지 않고 목록만 확인")
    ap.add_argument("--undo", metavar="LOG", help="마지막 삭제를 되돌림(delete_log.jsonl)")
    args = ap.parse_args()

    if args.undo:
        do_undo(args.undo)
        return
    if not args.list_file:
        ap.error("삭제할 목록 파일을 지정하세요 (예: python delete_files.py to_delete.txt)")

    targets = load_targets(args.list_file)
    if not targets:
        sys.exit("목록이 비어 있습니다.")
    do_trash(targets, args.dry_run)


if __name__ == "__main__":
    main()
