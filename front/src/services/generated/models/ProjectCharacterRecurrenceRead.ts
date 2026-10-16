/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CharacterRecurrenceRead } from './CharacterRecurrenceRead';
/**
 * 项目下全部角色的跨集出现情况（只读）。
 */
export type ProjectCharacterRecurrenceRead = {
    /**
     * 项目 ID
     */
    project_id: string;
    /**
     * 判定为主角级所需的最少章节数
     */
    min_chapters: number;
    /**
     * 角色明细
     */
    items?: Array<CharacterRecurrenceRead>;
};

