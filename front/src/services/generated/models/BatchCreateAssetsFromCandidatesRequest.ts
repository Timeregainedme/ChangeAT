/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 一键从提取候选创建/关联资产的请求体。
 */
export type BatchCreateAssetsFromCandidatesRequest = {
    /**
     * 章节 ID：遍历该章节下所有 pending 提取候选
     */
    chapter_id: string;
    /**
     * 候选类型过滤（character/scene/prop/costume）；缺省处理全部类型
     */
    types?: (Array<string> | null);
};

