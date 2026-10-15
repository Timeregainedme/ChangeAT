/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 一键批量资产参考图生成请求体。
 */
export type BatchAssetImageTaskRequest = {
    /**
     * 目标项目 ID；批量任务只处理该项目下的资产，必填
     */
    project_id: string;
    /**
     * 资产类型：character / scene / prop / costume
     */
    asset_type: string;
    /**
     * 目标资产 ID 列表；缺省为该类型在当前项目下的全部资产
     */
    asset_ids?: (Array<string> | null);
};

