// 기출문제 아카이브 - 15분마다 GitHub에 "드라이브 바뀐 거 있나 확인해봐"를 보낸다.
// GitHub 자체 스케줄은 실제로 몇 시간에 한 번꼴로만 돌아서, 정확한 주기는
// 구글 Apps Script 시간 트리거로 맞춘다. 실제 확인/크롤링은 GitHub Actions가 한다
// (.github/workflows/crawl.yml, mode=detect) - 바뀐 게 없으면 몇 초 만에 끝난다.
//
// 설치 (script.google.com, 아무 구글 계정이나 가능 - 드라이브 권한은 안 씀):
//   1) 새 프로젝트를 만들고 이 코드를 Code.gs에 통째로 붙여넣기
//   2) 왼쪽 톱니(프로젝트 설정) > 스크립트 속성 > 속성 추가
//        이름: GITHUB_TOKEN   값: exam-archive 레포 Actions 쓰기 권한 토큰
//   3) 위쪽 함수 선택에서 setup 고르고 실행 > 권한 승인
// 토큰이 만료되면 실행이 실패하고 구글이 실패 알림 메일을 보낸다 -> 새 토큰으로 2)만 다시.

const REPO = '1213anthony/exam-archive';
const WORKFLOW = 'crawl.yml';

function checkDrive() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('스크립트 속성에 GITHUB_TOKEN이 없습니다');
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches',
    {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: { mode: 'detect' } }),
      muteHttpExceptions: true,
    }
  );
  if (res.getResponseCode() !== 204) {
    throw new Error('GitHub 요청 실패 ' + res.getResponseCode() + ': ' + res.getContentText().slice(0, 200));
  }
}

// 처음 한 번만 실행: 15분마다 checkDrive가 돌게 트리거를 만들고, 바로 한 번 돌려본다
function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('checkDrive').timeBased().everyMinutes(15).create();
  checkDrive();
}
