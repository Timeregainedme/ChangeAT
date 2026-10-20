/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProjectStyle } from './ProjectStyle';
import type { ProjectVisualStyle } from './ProjectVisualStyle';
export type ProjectRead = {
    /**
     * 项目名称
     */
    name: string;
    /**
     * 项目简介
     */
    description?: string;
    /**
     * 题材/风格
     */
    style: ProjectStyle;
    /**
     * 画面表现形式
     */
    visual_style?: ProjectVisualStyle;
    /**
     * 随机种子
     */
    seed?: number;
    /**
     * 是否统一风格
     */
    unify_style?: boolean;
    /**
     * 进度百分比（0-100）
     */
    progress?: number;
    /**
     * 项目级默认视频比例；分镜未覆盖时生效
     */
    default_video_ratio?: (string | null);
    /**
     * 项目级默认图片比例；为空时回落到视频比例
     */
    default_image_ratio?: (string | null);
    /**
     * 项目级默认图片分辨率档位（standard/high）；为空时回落到提供方默认档位
     */
    default_image_resolution_profile?: (string | null);
    /**
     * 视频生成时是否自动带上镜头台词已生成的配音作为参考音频（true=使用，false=纯画面参考）
     */
    use_dialog_audio_as_reference?: boolean;
    /**
     * 聚合统计（JSON）
     */
    stats?: Record<string, any>;
    id: string;
    /**
     * 所属工作区 ID
     */
    workspace_id: string;
    /**
     * 创建者账号 ID
     */
    created_by?: (number | null);
};

