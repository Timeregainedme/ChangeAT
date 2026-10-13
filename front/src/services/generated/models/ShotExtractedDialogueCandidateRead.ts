/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DialogueLineMode } from './DialogueLineMode';
import type { ShotDialogueCandidateStatus } from './ShotDialogueCandidateStatus';
export type ShotExtractedDialogueCandidateRead = {
    /**
     * 对白候选项 ID
     */
    id: number;
    /**
     * 所属镜头 ID
     */
    shot_id: string;
    /**
     * 镜头内对白候选排序
     */
    index: number;
    /**
     * 提取出的对白文本
     */
    text: string;
    /**
     * 对白模式
     */
    line_mode: DialogueLineMode;
    /**
     * 情绪/语气（来自脚本提取），确认后带入台词行
     */
    emotion?: (string | null);
    /**
     * 说话角色名称
     */
    speaker_name?: (string | null);
    /**
     * 听者角色名称
     */
    target_name?: (string | null);
    /**
     * 对白候选确认状态
     */
    candidate_status: ShotDialogueCandidateStatus;
    /**
     * 已接受后关联的对白行 ID
     */
    linked_dialog_line_id?: (number | null);
    /**
     * 候选来源
     */
    source: string;
    /**
     * 候选附加信息
     */
    payload?: Record<string, any>;
    /**
     * 确认时间
     */
    confirmed_at?: (string | null);
    /**
     * 创建时间
     */
    created_at: string;
    /**
     * 更新时间
     */
    updated_at: string;
};

