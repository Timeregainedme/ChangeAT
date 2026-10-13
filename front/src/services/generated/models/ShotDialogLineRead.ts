/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DialogueLineMode } from './DialogueLineMode';
export type ShotDialogLineRead = {
    /**
     * 对话行 ID
     */
    id: number;
    /**
     * 所属镜头细节 ID
     */
    shot_detail_id: string;
    /**
     * 行号（镜头内排序）
     */
    index?: number;
    /**
     * 台词内容
     */
    text: string;
    /**
     * 对白模式
     */
    line_mode?: DialogueLineMode;
    /**
     * 说话角色 ID
     */
    speaker_character_id?: (string | null);
    /**
     * 听者角色 ID
     */
    target_character_id?: (string | null);
    /**
     * 说话角色名称（用于回填关联；可空）
     */
    speaker_name?: (string | null);
    /**
     * 听者角色名称（用于回填关联；可空）
     */
    target_name?: (string | null);
    /**
     * 该台词行已生成音频关联的文件 ID（files.id，type=audio）
     */
    generated_audio_file_id?: (string | null);
};

