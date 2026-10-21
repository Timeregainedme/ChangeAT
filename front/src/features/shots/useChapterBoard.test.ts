import { describe, expect, it } from 'vitest'
import { getColumnOf, type BoardShot } from './useChapterBoard'

/**
 * 看板分列规则是这一页的核心业务判断：
 * 运行中优先于确认状态，否则「生成中」的镜头会被错误地提示去补确认信息。
 */
function makeShot(overrides: Partial<BoardShot>): BoardShot {
  return {
    id: 's1',
    index: 1,
    title: '镜头 1',
    status: 'pending',
    skipExtraction: false,
    scriptExcerpt: '',
    runtime: { hasActiveTasks: false, activeTaskCount: 0 },
    extraction: { state: 'extracted_empty', pendingAssets: 0, pendingDialogues: 0 },
    ...overrides,
  }
}

describe('getColumnOf', () => {
  it('有运行中任务时优先归入「生成中」', () => {
    const shot = makeShot({ status: 'pending', runtime: { hasActiveTasks: true, activeTaskCount: 3 } })
    expect(getColumnOf(shot)).toBe('running')
  })

  it('确认完成且无任务时归入「已就绪」', () => {
    expect(getColumnOf(makeShot({ status: 'ready' }))).toBe('ready')
  })

  it('未确认且无任务时归入「待确认」', () => {
    expect(getColumnOf(makeShot({ status: 'pending' }))).toBe('pending')
  })
})
