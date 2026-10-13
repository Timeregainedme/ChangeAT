/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProjectProductionReadinessCheck } from './ProjectProductionReadinessCheck';
/**
 * 项目开工预检报告（只读聚合，不修改任何状态）。
 */
export type ProjectProductionReadinessRead = {
    /**
     * 项目 ID
     */
    project_id: string;
    /**
     * 是否全部通过，可以开工
     */
    ready: boolean;
    /**
     * 检查项明细
     */
    checks?: Array<ProjectProductionReadinessCheck>;
    /**
     * 项目当前规模统计
     */
    stats?: Record<string, any>;
};

