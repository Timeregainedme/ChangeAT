/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 当前默认视频模型对应的生成参数选项。
 */
export type VideoGenerationOptionsRead = {
    /**
     * 供应商稳定键
     */
    provider: string;
    /**
     * 默认视频模型 ID
     */
    model_id: string;
    /**
     * 默认视频模型名称
     */
    model_name: string;
    /**
     * 当前模型允许的比例选项
     */
    allowed_ratios?: Array<string>;
    /**
     * 当前模型默认比例
     */
    default_ratio: string;
    /**
     * 当前模型允许的分辨率档位（如 768p/2k）；为空表示该供应商不暴露分辨率参数
     */
    allowed_resolutions?: Array<string>;
    /**
     * 当前模型默认分辨率档位；为空表示由供应商自身决定
     */
    default_resolution?: (string | null);
};

