/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type TimelineStatsRead = {
    clip_count: number;
    total_duration: number;
    clips_with_video: number;
    clips_missing_video: number;
    clips_with_audio: number;
    /**
     * 全部片段都有视频时才可导出成片
     */
    exportable: boolean;
};

