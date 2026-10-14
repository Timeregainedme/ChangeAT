/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 一键批量资产参考图生成请求体。
 */
export type BatchAssetImageTaskRequest = {
    /**
     * 资产类型：character / scene / prop / costume
     */
    asset_type: string;
    /**
     * 目标资产 ID 列表；缺省为该类型全部资产
     */
    asset_ids?: (Array<string> | null);
};

