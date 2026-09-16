import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'node:path';

// data.js는 리포 루트에 있고(크롤러가 만든다) 번들에 넣지 않는다.
// 개발 서버에서는 루트의 파일을 그대로 흘려보내 준다.
function serveRootDataJs(): Plugin {
  const file = path.resolve(__dirname, '..', 'data.js');
  return {
    name: 'serve-root-data-js',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url && req.url.split('?')[0].endsWith('/data.js')) {
          res.setHeader('content-type', 'text/javascript; charset=utf-8');
          fs.createReadStream(file).pipe(res);
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), serveRootDataJs()],
  // GitHub Pages: https://1213anthony.github.io/exam-archive/
  base: '/exam-archive/',
  build: {
    // 빌드 결과를 리포 루트에 바로 쓴다. 지금 배포 방식(main 브랜치 루트를
    // Pages로 서빙)을 그대로 쓰기 위해서다. 루트의 다른 파일은 건드리지 않는다.
    outDir: path.resolve(__dirname, '..'),
    emptyOutDir: false,
    // three.js는 Galaxy를 lazy import 할 때만 같이 내려오게 둔다(수동 청크로 떼면
    // 진입 HTML에 modulepreload가 붙어 목록 모드 사용자도 1MB를 받게 된다).
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: 'node',
  },
} as any);
