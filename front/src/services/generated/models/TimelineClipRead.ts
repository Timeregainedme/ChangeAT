/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TimelineDialogRead } from './TimelineDialogRead';
import type { TimelineFrameRead } from './TimelineFrameRead';
/**
 * 时间线上的一个片段（= 一个镜头）。
 */
export type TimelineClipRead = {
    shot_id: string;
    chapter_id: string;
    chapter_index: number;
    chapter_title: string;
    index: number;
    title: string;
    status: string;
    /**
     * 秒；取自 ShotDetail.duration，缺失为 0
     */
    duration?: number;
    /**
     * 在成片中的起始秒
     */
    start?: number;
    /**
     * 在成片中的结束秒
     */
    end?: number;
    /**
     * 当前采用的视频文件 ID；为空表示还没生成
     */
    video_file_id?: (string | null);
    /**
     * 分镜级配音文件 ID
     */
    audio_file_id?: (string | null);
    thumbnail?: string;
    frames?: Array<TimelineFrameRead>;
    dialogs?: Array<TimelineDialogRead>;
};

