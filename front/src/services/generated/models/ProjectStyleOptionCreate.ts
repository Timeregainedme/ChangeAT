/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 新增风格。
 */
export type ProjectStyleOptionCreate = {
    /**
     * 所属画面表现形式
     */
    visual_style: string;
    /**
     * 风格名称
     */
    name: string;
    /**
     * 面向用户的说明
     */
    description?: string;
    /**
     * 同组内排序；不传则排到末尾
     */
    sort_order?: (number | null);
};

