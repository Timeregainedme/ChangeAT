import { QueryClient } from '@tanstack/react-query'

/**
 * 全局 QueryClient。
 *
 * 默认值按「长任务工作台」的场景调过，而不是照抄文档默认值：
 *   - retry: 1 —— 生成类接口失败通常是真的失败，重试两次只会拖慢错误反馈；
 *   - refetchOnWindowFocus: false —— 用户切窗口去剪片时不该触发大批请求；
 *   - staleTime: 30s —— 项目/章节列表这类数据在 30s 内重复进入不必重拉。
 * 需要更激进刷新的查询（如任务进度）在各自的 hook 里单独覆盖。
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      gcTime: 5 * 60_000,
    },
    mutations: {
      retry: 0,
    },
  },
})

/**
 * 统一 query key 的构造出口。
 *
 * 把 key 收敛到一处，避免不同页面写成 ['shots'] 和 ['shot-list'] 各查一份缓存，
 * 也方便后续做「某个项目下所有查询一起失效」这类批量操作。
 */
export const queryKeys = {
  projects: ['projects'] as const,
  project: (projectId: string) => ['project', projectId] as const,
  chapters: (projectId: string) => ['chapters', projectId] as const,
  chapter: (projectId: string, chapterId: string) => ['chapter', projectId, chapterId] as const,
  shots: (chapterId: string) => ['shots', chapterId] as const,
  shot: (shotId: string) => ['shot', shotId] as const,
  tasks: ['tasks'] as const,
}
