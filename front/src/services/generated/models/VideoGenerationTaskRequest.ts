/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 视频生成任务请求。
 */
export type VideoGenerationTaskRequest = {
    /**
     * 镜头 ID
     */
    shot_id: string;
    /**
     * 参考模式：first | last | key | first_last | first_last_key | text_only | reference；reference 为参考图模式（不使用分镜帧，参考图取自有序 IR 参考列表）
     */
    reference_mode: 'first' | 'last' | 'key' | 'first_last' | 'first_last_key' | 'text_only' | 'reference';
    /**
     * 视频提示词（text_only / reference 必填）
     */
    prompt?: (string | null);
    /**
     * 参考图 file_id 列表；帧模式数量需与 reference_mode 严格匹配，reference 模式由服务端按 IR 参考列表覆盖
     */
    images?: Array<string>;
    /**
     * 参考音频 file_id 列表（配音产物）。仅 reference 模式生效；会以对象存储公开 URL 提交给供应商（音频不支持 base64）。约束：最多 3 个，且必须同时存在参考图——音频不能单独使用。
     */
    reference_audio_file_ids?: Array<string>;
    /**
     * 视频画幅比例，如 16:9 / 9:16；不传则继承分镜的 override_video_ratio，再继承项目的 default_video_ratio
     */
    ratio?: ('16:9' | '4:3' | '1:1' | '3:4' | '9:16' | '21:9' | null);
    /**
     * 是否使用供应商平台自带的提示词优化，默认关闭
     */
    use_context_ir?: boolean;
    /**
     * 平台提示词优化所用的 skill 标识，仅在 use_context_ir=true 时生效
     */
    skill_id?: (string | null);
};

