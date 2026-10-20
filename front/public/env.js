// 本地开发默认值；部署时由 nginx 动态生成 /env.js 覆盖。
// GOOGLE_CLIENT_ID 为公开信息（Client Secret 只存后端），可安全下发。
window.__ENV = window.__ENV || {
  BACKEND_URL: 'http://localhost:8000',
  GOOGLE_CLIENT_ID: '',
}
