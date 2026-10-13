/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 当前默认音频模型对应的 TTS 参数选项。
 */
export type AudioGenerationOptionsRead = {
    /**
     * 供应商稳定键
     */
    provider: string;
    /**
     * 默认音频模型 ID
     */
    model_id: string;
    /**
     * 默认音频模型名称
     */
    model_name: string;
    /**
     * 当前模型支持的输出格式
     */
    supported_formats?: Array<string>;
    /**
     * 是否支持指定音色
     */
    supports_voice?: boolean;
    /**
     * 是否支持复刻音色
     */
    supports_custom_voice?: boolean;
    /**
     * 是否支持调节语速
     */
    supports_speed?: boolean;
    /**
     * 最小语速倍率
     */
    min_speed?: number;
    /**
     * 最大语速倍率
     */
    max_speed?: number;
    /**
     * 是否支持情感描述
     */
    supports_emotion?: boolean;
    /**
     * 情感描述最大字符数
     */
    max_emotion_chars?: number;
    /**
     * 是否支持指定语种
     */
    supports_language?: boolean;
    /**
     * 待合成文本最大字符数
     */
    max_text_chars?: number;
};

