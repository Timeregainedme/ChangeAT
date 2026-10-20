/**
 * 实体合并弹窗（通用）。
 *
 * 解决的问题：
 *   提取阶段 LLM 命名不稳定，同一个实体可能落库成两条（例如
 *   「护工工作服」与「护工护理工作服」）。用户需要把其中一条合并到另一条，
 *   图片 / 项目关联 / 镜头关联 / 提取候选都要跟着迁移。
 *
 * 交互约定：
 *   - 用户先选「保留的那一条」（target），再选「被合并掉的那一条」（source）；
 *   - 合并是**不可逆**的（source 记录会被删除），因此需要二次确认文案；
 *   - 合并完成后展示迁移统计，便于核对是否达到预期。
 *
 * 该组件只负责 UI 与一次 API 调用，具体迁移规则在后端
 * `services/studio/entity_merge.py`，互通依赖 OpenAPI 生成的 client。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Modal, Select, Space, Typography, message } from 'antd'
import { StudioEntitiesService } from '../../../../services/generated'
import type { EntityMergePairResult } from '../../../../services/generated'

const { Text } = Typography

export type MergeOption = { id: string; name: string }

export type EntityMergeModalProps = {
  open: boolean
  /** 实体类型：actor / character / scene / prop / costume */
  entityType: 'actor' | 'character' | 'scene' | 'prop' | 'costume'
  /** 展示用中文名，如「服装」 */
  entityLabel: string
  /** 拉取候选列表；支持关键字，用于下拉搜索 */
  loadOptions: (keyword: string) => Promise<MergeOption[]>
  onCancel: () => void
  /** 合并成功后回调，调用方应刷新列表 */
  onMerged?: (result: EntityMergePairResult) => void
}

export function EntityMergeModal({
  open,
  entityType,
  entityLabel,
  loadOptions,
  onCancel,
  onMerged,
}: EntityMergeModalProps) {
  const [options, setOptions] = useState<MergeOption[]>([])
  const [optionsLoading, setOptionsLoading] = useState(false)
  const [sourceId, setSourceId] = useState<string | undefined>()
  const [targetId, setTargetId] = useState<string | undefined>()
  const [merging, setMerging] = useState(false)

  /** 拉取可合并的实体列表（下拉搜索走同一入口）。 */
  // 用 ref 持有最新的 loadOptions：父组件常以内联函数传入，直接进依赖会导致
  // 每次渲染都重跑 effect（进而无限刷新），因此固定回调、只更新引用。
  const loadOptionsRef = useRef(loadOptions)
  useEffect(() => {
    loadOptionsRef.current = loadOptions
  }, [loadOptions])

  const fetchOptions = useCallback(async (keyword: string) => {
    setOptionsLoading(true)
    try {
      const items = await loadOptionsRef.current(keyword)
      setOptions(items)
    } catch {
      setOptions([])
    } finally {
      setOptionsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    setSourceId(undefined)
    setTargetId(undefined)
    void fetchOptions('')
  }, [open, fetchOptions])

  const sourceName = options.find((o) => o.id === sourceId)?.name ?? ''
  const targetName = options.find((o) => o.id === targetId)?.name ?? ''
  const canMerge = Boolean(sourceId && targetId && sourceId !== targetId) && !merging

  /**
   * 执行合并。
   *
   * 失败信息直接透出后端 detail（例如「不能把实体合并到它自己」），
   * 让用户知道是操作问题而不是系统故障。
   */
  const handleMerge = async () => {
    if (!sourceId || !targetId) return
    if (sourceId === targetId) {
      message.warning('保留项与被合并项不能是同一条')
      return
    }
    setMerging(true)
    try {
      const resp = await StudioEntitiesService.mergeEntityPairApiV1StudioEntitiesEntityTypeMergePost({
        entityType,
        requestBody: { source_id: sourceId, target_id: targetId },
      })
      const result = (resp.data ?? null) as EntityMergePairResult | null
      const stats = result
        ? `图片迁移 ${result.images_moved ?? 0} 张（重复丢弃 ${result.images_dropped ?? 0} 张）、` +
          `关联迁移 ${result.links_moved ?? 0} 条（重复丢弃 ${result.links_dropped ?? 0} 条）、` +
          `候选重指向 ${result.candidates_repointed ?? 0} 条`
        : ''
      message.success(`已把「${sourceName}」合并到「${targetName}」${stats ? `：${stats}` : ''}`)
      if (result) onMerged?.(result)
      onCancel()
    } catch (error) {
      message.error(error instanceof Error ? `合并失败：${error.message}` : '合并失败')
    } finally {
      setMerging(false)
    }
  }

  return (
    <Modal
      title={`合并${entityLabel}`}
      open={open}
      onCancel={onCancel}
      onOk={() => void handleMerge()}
      okText="确认合并"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !canMerge, loading: merging }}
      destroyOnClose
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type="warning"
          showIcon
          message="合并不可逆"
          description={
            <div className="text-xs leading-6">
              「被合并项」的图片、项目/镜头关联、提取候选会全部迁到「保留项」，然后**删除被合并项本身**。
              若需要留存被合并项的元信息，请先截图或记录。
            </div>
          }
        />

        <div>
          <Text strong>① 保留这一条（合并到这里）</Text>
          <Select
            className="w-full mt-1"
            showSearch
            allowClear
            placeholder={`搜索并选择要保留的${entityLabel}`}
            value={targetId}
            loading={optionsLoading}
            filterOption={false}
            onSearch={(kw) => void fetchOptions(kw)}
            onChange={(val) => setTargetId(val)}
            options={options.map((o) => ({ value: o.id, label: o.name }))}
          />
        </div>

        <div>
          <Text strong>② 合并掉这一条（合并后删除）</Text>
          <Select
            className="w-full mt-1"
            showSearch
            allowClear
            placeholder={`搜索并选择要被合并掉的${entityLabel}`}
            value={sourceId}
            loading={optionsLoading}
            filterOption={false}
            onSearch={(kw) => void fetchOptions(kw)}
            onChange={(val) => setSourceId(val)}
            options={options
              .filter((o) => o.id !== targetId)
              .map((o) => ({ value: o.id, label: o.name }))}
          />
        </div>

        {sourceId && targetId && sourceId === targetId ? (
          <Alert type="error" showIcon message="保留项与被合并项不能是同一条" />
        ) : null}

        {sourceName && targetName && sourceId !== targetId ? (
          <Alert
            type="info"
            showIcon
            message="即将执行"
            description={
              <div className="text-xs">
                把「{sourceName}」合并到「{targetName}」，然后删除「{sourceName}」。
              </div>
            }
          />
        ) : null}
      </Space>
    </Modal>
  )
}

export default EntityMergeModal
