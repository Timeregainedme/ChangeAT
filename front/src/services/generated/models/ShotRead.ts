/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotExtractionSummaryRead } from './ShotExtractionSummaryRead';
import type { ShotStatus } from './ShotStatus';
export type ShotRead = {
    /**
     * 镜头 ID
     */
    id: string;
    /**
     * 所属章节 ID
     */
    chapter_id: string;
    /**
     * 镜头序号（章节内唯一）
     */
    index: number;
    /**
     * 镜头标题
     */
    title: string;
    /**
     * 缩略图 URL/路径
     */
    thumbnail?: string;
    /**
     * 镜头状态
     */
    status?: ShotStatus;
    /**
     * 是否明确跳过信息提取
     */
    skip_extraction?: boolean;
    /**
     * 剧本摘录
     */
    script_excerpt?: string;
    /**
     * 已生成视频关联的文件 ID（files.id，type=video）
     */
    generated_video_file_id?: (string | null);
    /**
     * 分镜级已生成音频关联的文件 ID（files.id，type=audio）
     */
    generated_audio_file_id?: (string | null);
    /**
     * 最近一次完成信息提取的时间
     */
    last_extracted_at?: (string | null);
    /**
     * 镜头提取状态摘要
     */
    extraction: ShotExtractionSummaryRead;
};

