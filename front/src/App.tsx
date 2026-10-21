import { Suspense, lazy, type FC } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Spin } from 'antd'
import AppShell from './app/shell/AppShell'
import RequireAuth from './components/RequireAuth'
import Login from './pages/Login'
import ProjectListPage from './features/projects/ProjectListPage'
import './App.css'

/**
 * 路由级代码分割。
 *
 * 为什么只把「首屏路径」保留为静态导入：
 *   - Login：未登录时直接进入，必须最快可用。
 *   - AppShell：所有内页共用，拆出去反而多一次串行请求。
 *   - ProjectListPage：登录后的第一个页面，静态引入避免「登录完再等一次」。
 *
 * 其余重页面（章节工作室 / 分镜编辑 / 视频剪辑 / 模型管理等）改为 lazy，
 * 让首屏只下载当前路径真正需要的代码。
 * 在 RTT 约 300ms 的国际链路上，首屏体积从 ~1.8MB 降到几百 KB 的收益
 * 远大于多一次 chunk 请求的成本。
 *
 * 注意：ChapterShotsPage / ChapterShotEditPage 是具名导出，需要显式映射 default。
 */
const ProjectWorkbench = lazy(() => import('./pages/aiStudio/project/ProjectWorkbench'))
const RoleDetailPage = lazy(() => import('./pages/aiStudio/project/ProjectWorkbench/RoleDetailPage'))
const ChapterStudio = lazy(() => import('./pages/aiStudio/chapter/ChapterStudio'))
const ChapterReviewPage = lazy(() =>
  import('./pages/aiStudio/review/ChapterReviewPage').then((m) => ({ default: m.ChapterReviewPage })),
)
const AssetManager = lazy(() => import('./pages/aiStudio/assets/AssetManager'))
const ActorAssetEditPage = lazy(() => import('./pages/aiStudio/assets/ActorAssetEditPage.tsx'))
const SceneAssetEditPage = lazy(() => import('./pages/aiStudio/assets/SceneAssetEditPage.tsx'))
const PropAssetEditPage = lazy(() => import('./pages/aiStudio/assets/PropAssetEditPage.tsx'))
const CostumeAssetEditPage = lazy(() => import('./pages/aiStudio/assets/CostumeAssetEditPage.tsx'))
const PromptTemplateManager = lazy(() => import('./pages/aiStudio/prompts/PromptTemplateManager'))
const VideoEditor = lazy(() => import('./pages/aiStudio/editor/VideoEditor'))
const ModelManagement = lazy(() => import('./pages/aiStudio/models/ModelManagement'))
const VoiceManager = lazy(() => import('./pages/aiStudio/voice/VoiceManager'))
const ShotBoardPage = lazy(() => import('./features/shots/ShotBoardPage'))
const ChapterShotsPage = lazy(() =>
  import('./pages/aiStudio/shots/ChapterShotsPage').then((m) => ({ default: m.ChapterShotsPage })),
)
const ChapterShotEditPage = lazy(() =>
  import('./pages/aiStudio/shots/ChapterShotEditPage').then((m) => ({ default: m.ChapterShotEditPage })),
)
const FileManagerPage = lazy(() => import('./features/files/FileManagerPage'))
const Settings = lazy(() => import('./pages/Settings'))
const NotFound = lazy(() => import('./pages/NotFound'))

/**
 * 设计系统预览页：只在开发环境注册。
 *
 * 用三元而不是在 JSX 里写 `{import.meta.env.DEV && ...}`：
 * 生产构建时 `import.meta.env.DEV` 被静态替换为 false，
 * 整条分支连同动态 import 一起被裁掉，不会额外产出 chunk。
 */
const DesignPreview = import.meta.env.DEV ? lazy(() => import('./app/design-preview')) : null

/** chunk 加载中的占位：保持整页高度，避免布局跳动。 */
const RouteFallback: FC = () => (
  <div className="min-h-[60vh] flex items-center justify-center">
    <Spin size="large" tip="加载中…" />
  </div>
)

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          {/* 登录页不需要守卫，否则死循环 */}
          <Route path="/login" element={<Login />} />

          {/* 设计系统预览页：仅开发环境存在 */}
          {DesignPreview ? <Route path="/design" element={<DesignPreview />} /> : null}

          {/* 其余页面统一要求登录 */}
          <Route
            path="/"
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="/projects" replace />} />
            <Route path="projects" element={<ProjectListPage />} />
            <Route path="projects/:projectId" element={<ProjectWorkbench />} />
            <Route path="projects/:projectId/roles/:characterId/edit" element={<RoleDetailPage />} />
            <Route path="projects/:projectId/chapters/:chapterId/prep/*" element={<Navigate to="../shots" replace />} />
            <Route path="projects/:projectId/chapters/:chapterId/studio" element={<ChapterStudio />} />
            <Route path="projects/:projectId/chapters/:chapterId/review" element={<ChapterReviewPage />} />
            <Route path="projects/:projectId/chapters/:chapterId/shots/:shotId/edit" element={<ChapterShotEditPage />} />
            <Route path="projects/:projectId/chapters/:chapterId/shots" element={<ChapterShotsPage />} />
            <Route path="projects/:projectId/chapters/:chapterId/board" element={<ShotBoardPage />} />
            <Route path="projects/:projectId/chapters/:chapterId/prep-drafts" element={<Navigate to="../shots" replace />} />
            <Route path="projects/:projectId/editor" element={<VideoEditor />} />
            <Route path="assets" element={<AssetManager />} />
            <Route path="files" element={<FileManagerPage />} />
            <Route path="assets/actors/:actorImageId/edit" element={<ActorAssetEditPage />} />
            <Route path="assets/scenes/:sceneId/edit" element={<SceneAssetEditPage />} />
            <Route path="assets/props/:propId/edit" element={<PropAssetEditPage />} />
            <Route path="assets/costumes/:costumeId/edit" element={<CostumeAssetEditPage />} />
            <Route path="prompts" element={<PromptTemplateManager />} />
            <Route path="models" element={<ModelManagement />} />
            <Route path="voices" element={<VoiceManager />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App