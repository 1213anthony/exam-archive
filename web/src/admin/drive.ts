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

// 다른 폴더로 옮긴다(잘못 분류된 파일 정리용). 드라이브에서 파일은 부모가 여러 개일 수
// 있어서 "이동"은 새 부모를 더하고 옛 부모를 빼는 식으로 한다.
export async function moveFile(token: string, id: string, addParent: string, removeParent: string): Promise<void> {
  const url = `${API}${encodeURIComponent(id)}?addParents=${encodeURIComponent(addParent)}&removeParents=${encodeURIComponent(removeParent)}`;
  const r = await fetch(url, {
    method: 'PATCH',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error(`이동 실패 (${r.status}) ${t.slice(0, 120)}`);
  }
}

export async function whoAmI(token: string): Promise<string> {
  const r = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', { headers: { Authorization: 'Bearer ' + token } });
  if (!r.ok) throw new Error('계정 정보를 못 읽음');
  const j = await r.json();
  return j.email as string;
}
