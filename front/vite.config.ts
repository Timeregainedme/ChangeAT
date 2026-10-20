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
    // 单个 chunk 超过 600KB 时告警，便于持续观察首屏体积
    chunkSizeWarningLimit: 600,
    // 不使用自定义 manualChunks：
    // 实测在 300ms RTT 的国际链路上，过细的手动分包会因「额外请求数」
    // 抵消掉并行下载的收益（每个 chunk 至少多一次往返）。
    // 依赖路由级 lazy 后，Vite 默认分包已能把各页面切成独立 chunk，
    // 首屏只保留 React + antd 核心 + 登录页 + 项目列表。
  },
})
