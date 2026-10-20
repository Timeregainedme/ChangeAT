import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  server: {
    port: 7788,
    open: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // 静态资源目录改为 static（默认是 assets）。
    // 原因：前端有 /assets 路由（资产管理的子页面，如 /assets/costumes/:id/edit），
    // 与默认的 dist/assets/ 目录同名；nginx 的 location /assets/ 优先级高于 SPA
    // fallback，导致这些前端路由被当成静态文件请求而 404。
    assetsDir: 'static',
    // 单个 chunk 超过 600KB 时告警，便于持续观察首屏体积
    chunkSizeWarningLimit: 600,
    // 不使用自定义 manualChunks：
    // 实测在 300ms RTT 的国际链路上，过细的手动分包会因「额外请求数」
    // 抵消掉并行下载的收益（每个 chunk 至少多一次往返）。
    // 依赖路由级 lazy 后，Vite 默认分包已能把各页面切成独立 chunk，
    // 首屏只保留 React + antd 核心 + 登录页 + 项目列表。
  },
})
