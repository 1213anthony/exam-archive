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
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three', '@react-three/fiber', '@react-three/drei'],
        },
      },
    },
  },
  test: {
    environment: 'node',
  },
} as any);
