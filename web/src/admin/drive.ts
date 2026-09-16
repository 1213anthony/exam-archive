// 브라우저에서 드라이브 API를 직접 부른다(서버 없음). 완전 삭제는 절대 하지 않고
// 휴지통 이동(trashed=true)만 한다. 드라이브 휴지통에서 30일 안에 되돌릴 수 있다.

const API = 'https://www.googleapis.com/drive/v3/files/';

export interface FileMeta {
  id: string; name: string; canTrash: boolean; owner: string; trashed: boolean;
}

export async function getMeta(token: string, id: string): Promise<FileMeta> {
  const r = await fetch(API + encodeURIComponent(id) + '?fields=id,name,trashed,capabilities(canTrash),owners(emailAddress)', {
    headers: { Authorization: 'Bearer ' + token },
  });
  if (!r.ok) throw new Error(`메타데이터 조회 실패 (${r.status})`);
  const j = await r.json();
  return {
    id: j.id, name: j.name, trashed: !!j.trashed,
    canTrash: !!(j.capabilities && j.capabilities.canTrash),
    owner: (j.owners && j.owners[0] && j.owners[0].emailAddress) || '(알 수 없음)',
  };
}

export async function trash(token: string, id: string): Promise<void> {
  const r = await fetch(API + encodeURIComponent(id), {
    method: 'PATCH',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ trashed: true }),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error(`휴지통 이동 실패 (${r.status}) ${t.slice(0, 120)}`);
  }
}

export async function untrash(token: string, id: string): Promise<void> {
  const r = await fetch(API + encodeURIComponent(id), {
    method: 'PATCH',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ trashed: false }),
  });
  if (!r.ok) throw new Error(`복구 실패 (${r.status})`);
}

export async function whoAmI(token: string): Promise<string> {
  const r = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', { headers: { Authorization: 'Bearer ' + token } });
  if (!r.ok) throw new Error('계정 정보를 못 읽음');
  const j = await r.json();
  return j.email as string;
}
