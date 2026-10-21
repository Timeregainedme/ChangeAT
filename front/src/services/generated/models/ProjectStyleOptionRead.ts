/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 风格目录项。
 */
export type ProjectStyleOptionRead = {
    id: string;
    /**
     * 所属画面表现形式（现实/动漫…）
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
     * 同组内排序
     */
    sort_order?: number;
};

