/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 实体合并结果统计。
 *
 * 字段语义：
 * - images_moved：迁到目标实体名下的图片数
 * - images_dropped：预留字段，当前始终为 0（不主动删图，避免误删有效素材）
 * - links_moved：迁到目标实体的关联数
 * - links_dropped：因目标已存在同一作用域关联而删除的重复关联数
 * - candidates_repointed：指向目标的提取候选数
 */
export type EntityMergePairResult = {
    /**
     * 实体类型：actor/character/scene/prop/costume
     */
    entity_type: string;
    /**
     * 被删除的实体 ID
     */
    source_id: string;
    /**
     * 保留的实体 ID
     */
    target_id: string;
    /**
     * 迁移的图片数
     */
    images_moved?: number;
    /**
     * 丢弃的图片数（当前始终为 0）
     */
    images_dropped?: number;
    /**
     * 迁移的关联数
     */
    links_moved?: number;
    /**
     * 因重复而删除的关联数
     */
    links_dropped?: number;
    /**
     * 重新指向目标实体的提取候选数
     */
    candidates_repointed?: number;
};

