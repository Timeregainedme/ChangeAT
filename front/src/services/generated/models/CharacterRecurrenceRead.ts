/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 单个角色的跨集出现情况。
 *
 * 存在的意义：角色要不要绑定演员取决于它出现在几集里 —— 跨集反复出现的必须绑，
 * 只在一集内出现的不需要（用户口径 m09145）。把章节数直接给前端，编辑角色时就能标出来。
 */
export type CharacterRecurrenceRead = {
    /**
     * 角色 ID
     */
    character_id: string;
    /**
     * 该角色出现的去重章节（集）数
     */
    chapter_count: number;
    /**
     * 是否为跨集反复出现的主角级角色（需要绑定演员）
     */
    recurring: boolean;
};

