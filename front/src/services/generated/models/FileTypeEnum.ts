/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 文件类型，取值与 DB 模型 ``app.models.types.FileType`` 保持一致。
 *
 * 注意：这里**必须**包含 ``audio``。库里存在音频文件（TTS 产出的
 * ``generated-audios/...``），枚举缺项会让文件列表的响应序列化整体失败并
 * 返回 400（整表失败，不是跳过该行）。
 */
export type FileTypeEnum = 'image' | 'video' | 'audio';
