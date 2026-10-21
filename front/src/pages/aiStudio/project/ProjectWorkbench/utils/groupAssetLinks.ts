/**
 * 项目资产关联的分组工具。
 *
 * 背景：`project_*_links` 是按「项目 / 章节 / 镜头」三个层级分别落行的，
 * 同一个场景被 4 个镜头引用就会有 4 行关联。资产页直接把链接列表渲染出来，
 * 用户看到的是同一张图重复 4 次、名字也一样——看起来像「重复资产」，
 * 实际只是一个资产的多处关联。
 *
 * 这里统一按资产 ID 分组：一个资产只出现在一页上，关联网格用「关联 N 处」表达。
 */
export interface AssetLinkGroup<L> {
  /** 分组键 = 资产 ID */
  key: string
  assetId: string
  /** 该资产的全部关联行（至少一条） */
  links: L[]
  /** 首条关联，用于取缩略图等「行级」字段（同一资产各行的图应一致） */
  primary: L
}

/**
 * 按资产 ID 分组，保留首次出现的顺序。
 *
 * 顺序很重要：后端返回按更新时间排序，分组后如果按 ID 排序会打乱用户熟悉的顺序。
 */
export function groupLinksByAsset<L>(links: L[], getAssetId: (link: L) => string): AssetLinkGroup<L>[] {
  const map = new Map<string, AssetLinkGroup<L>>()

  for (const link of links) {
    const assetId = getAssetId(link)
    if (!assetId) continue

    const existing = map.get(assetId)
    if (existing) {
      existing.links.push(link)
    } else {
      map.set(assetId, { key: assetId, assetId, links: [link], primary: link })
    }
  }

  return Array.from(map.values())
}

/** 分页切片：对分组后的资产分页，而不是对原始关联行分页。 */
export function paginateGroups<G>(groups: G[], page: number, pageSize: number): G[] {
  const start = (page - 1) * pageSize
  return groups.slice(start, start + pageSize)
}
