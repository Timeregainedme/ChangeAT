/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 实体合并请求：把 source 合并进 target。
 */
export type EntityMergeRequest = {
    /**
     * 被合并掉的实体 ID（合并完成后该记录被删除）
     */
    source_id: string;
    /**
     * 保留的实体 ID（图片、关联、候选都会迁移到它）
     */
    target_id: string;
};

