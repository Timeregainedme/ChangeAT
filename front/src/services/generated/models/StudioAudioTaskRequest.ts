/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Studio 专用音频任务请求体：可选模型 ID，不传则用默认音频模型；供应商由模型反查。
 */
export type StudioAudioTaskRequest = {
    /**
     * 音频模型 ID；不传则使用默认音频模型
     */
    model_id?: (string | null);
    /**
     * 待合成文本
     */
    text: string;
    /**
     * 音色 ID；不传则由供应商使用默认音色
     */
    voice?: (string | null);
    /**
     * 音色来源：preset=预置音色、custom=复刻音色；不传则按模型名推断
     */
    voice_source?: ('preset' | 'custom' | null);
    /**
     * 语种，如 zh / en / ja；不传默认中文
     */
    language?: (string | null);
    /**
     * 语速倍率，仅大于 0 时下发
     */
    speed?: (number | null);
    /**
     * 情感描述文本
     */
    emotion?: (string | null);
    /**
     * 输出音频格式
     */
    format?: string;
    /**
     * 业务关联类型
     */
    relation_type?: string;
    /**
     * 业务关联实体 ID
     */
    relation_entity_id?: string;
    /**
     * 可选：归属项目 ID，用于登记文件使用位置
     */
    project_id?: (string | null);
    /**
     * 可选：归属章节 ID
     */
    chapter_id?: (string | null);
    /**
     * 可选：归属镜头 ID
     */
    shot_id?: (string | null);
};

