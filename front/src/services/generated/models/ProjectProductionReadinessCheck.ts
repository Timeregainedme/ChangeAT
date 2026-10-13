/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 开工预检单项结果。
 */
export type ProjectProductionReadinessCheck = {
    /**
     * 检查项标识
     */
    key: string;
    /**
     * 检查项名称
     */
    label?: string;
    /**
     * 该项是否通过
     */
    ok: boolean;
    /**
     * 结果说明；未通过时给出可执行的修复指引
     */
    message?: string;
    /**
     * 该项补充数据
     */
    detail?: Record<string, any>;
};

