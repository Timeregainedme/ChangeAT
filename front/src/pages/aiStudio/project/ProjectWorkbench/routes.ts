export function getProjectChaptersPath(projectId: string) {
  return `/projects/${projectId}/chapters`
}

export function getChapterStudioPath(projectId: string, chapterId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/studio`
}

export function getChapterShotsPath(projectId: string, chapterId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/shots`
}

/** 章节检查页（参考图 → 分镜 → 对话 三段自查）。 */
export function getChapterReviewPath(projectId: string, chapterId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/review`
}

export function getChapterShotEditPath(projectId: string, chapterId: string, shotId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/shots/${shotId}/edit`
}

export function getProjectEditorPath(projectId: string) {
  return `/projects/${projectId}/editor`
}


/** 章节镜头看板（按「待确认 / 生成中 / 已就绪」分列）。 */
export function getChapterBoardPath(projectId: string, chapterId: string) {
  return `/projects/${projectId}/chapters/${chapterId}/board`
}
