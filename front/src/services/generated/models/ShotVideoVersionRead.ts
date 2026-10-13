/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 镜头视频生成的一个版本（一次抽卡尝试）。
 *
 * 版本列表按创建时间倒序返回，`is_current` 标记当前采用的版本；
 * 历史版本一律保留，可随时切回。
 */
export type ShotVideoVersionRead = {
    /**
     * 视频生成任务 ID
     */
    task_id: string;
    /**
     * 该版本产出的视频文件 ID（files.id）
     */
    file_id?: (string | null);
    /**
     * 任务状态：pending/running/succeeded/failed/cancelled
     */
    status: string;
    /**
     * 是否为当前采用的版本
     */
    is_current?: boolean;
    /**
     * 该版本使用的画幅
     */
    ratio?: (string | null);
    /**
     * 该版本时长（秒）
     */
    seconds?: (number | null);
    /**
     * 该版本实际提交给模型的提示词
     */
    prompt?: (string | null);
    /**
     * 失败原因（仅失败版本有值）
     */
    error?: (string | null);
    /**
     * 创建时间
     */
    created_at?: (string | null);
};

