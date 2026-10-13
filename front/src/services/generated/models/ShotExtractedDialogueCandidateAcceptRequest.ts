/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DialogueLineMode } from './DialogueLineMode';
export type ShotExtractedDialogueCandidateAcceptRequest = {
    /**
     * 写入对白行时使用的排序；为空则使用候选排序
     */
    index?: (number | null);
    /**
     * 接受时可覆盖对白文本
     */
    text?: (string | null);
    /**
     * 接受时可覆盖对白模式
     */
    line_mode?: (DialogueLineMode | null);
    /**
     * 接受时可覆盖情绪/语气；为空则沿用候选上的情绪
     */
    emotion?: (string | null);
    /**
     * 接受时可覆盖说话角色名称
     */
    speaker_name?: (string | null);
    /**
     * 接受时可覆盖听者角色名称
     */
    target_name?: (string | null);
};

