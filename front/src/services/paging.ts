/**
 * 分页列表「取全量」的共用辅助。
 *
 * 为什么需要它：后端每个分页接口都用 `Query(10, ge=1, le=100)` 限制 `page_size`，
 * 前端若为了省事直接传 200 / 500，FastAPI 会在进入业务逻辑之前就返回 422
 * （`query.page_size: Input should be less than or equal to 100`）。而调用方通常只在
 * catch 里静默清空列表，于是表面症状是「页面无缘无故空了 / 概览加载失败」，很难归因。
 * 所以正确的做法不是把 page_size 调大，而是按上限顺序翻页。
 */

/** 后端分页接口允许的最大 `page_size`（见各路由的 `Query(10, ge=1, le=100)`）。 */
export const MAX_PAGE_SIZE = 100

/** 单次取全量允许翻的最大页数：后端 `total` 异常时不至于无限循环。 */
const MAX_PAGES = 50

/** 调用方从 generated client 响应里抽出的本页数据。 */
export type PagedSlice<T> = {
  items: T[]
  /** 后端给出的最大页码；缺失时退化为「本页不足一页即结束」。 */
  maxPage?: number
}

/**
 * 顺序翻页取全量。
 *
 * 之所以让调用方自己抽出 `items` / `maxPage`，而不是直接吃 generated client 的响应对象：
 * 每个端点生成的响应类型都不同（`ApiResponsePaginatedDataActorRead` 等），
 * 统一在辅助函数里解构需要为每个端点写一遍类型，反而更脆。
 *
 * @param loadPage 接收 1 基页码与每页条数，返回本页条目
 * @returns 按页序拼接的全部条目
 * @throws 任一页请求失败时原样抛出，由调用方决定降级方式（本辅助不吞异常）
 */
export async function fetchAllPages<T>(
  loadPage: (page: number, pageSize: number) => Promise<PagedSlice<T>>,
): Promise<T[]> {
  const all: T[] = []
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const { items, maxPage } = await loadPage(page, MAX_PAGE_SIZE)
    all.push(...items)
    if (typeof maxPage === 'number' && maxPage > 0) {
      if (page >= maxPage) break
      continue
    }
    // 后端没给 max_page 时，用「本页不足一整页」判断已到末页。
    if (items.length < MAX_PAGE_SIZE) break
  }
  return all
}
