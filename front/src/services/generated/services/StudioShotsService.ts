/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_dict_str__Any__ } from '../models/ApiResponse_dict_str__Any__';
import type { ApiResponse_list_ShotExtractedCandidateRead__ } from '../models/ApiResponse_list_ShotExtractedCandidateRead__';
import type { ApiResponse_list_ShotExtractedDialogueCandidateRead__ } from '../models/ApiResponse_list_ShotExtractedDialogueCandidateRead__';
import type { ApiResponse_list_ShotRuntimeSummaryRead__ } from '../models/ApiResponse_list_ShotRuntimeSummaryRead__';
import type { ApiResponse_list_ShotVideoVersionRead__ } from '../models/ApiResponse_list_ShotVideoVersionRead__';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_PaginatedData_ShotLinkedAssetItem__ } from '../models/ApiResponse_PaginatedData_ShotLinkedAssetItem__';
import type { ApiResponse_PaginatedData_ShotRead__ } from '../models/ApiResponse_PaginatedData_ShotRead__';
import type { ApiResponse_ShotAssetsOverviewRead_ } from '../models/ApiResponse_ShotAssetsOverviewRead_';
import type { ApiResponse_ShotPreparationMutationResultRead_ } from '../models/ApiResponse_ShotPreparationMutationResultRead_';
import type { ApiResponse_ShotPreparationStateRead_ } from '../models/ApiResponse_ShotPreparationStateRead_';
import type { ApiResponse_ShotRead_ } from '../models/ApiResponse_ShotRead_';
import type { ApiResponse_ShotVideoPromptPreviewRead_ } from '../models/ApiResponse_ShotVideoPromptPreviewRead_';
import type { ApiResponse_ShotVideoReadinessRead_ } from '../models/ApiResponse_ShotVideoReadinessRead_';
import type { ApiResponse_StudioScriptExtractionDraft_ } from '../models/ApiResponse_StudioScriptExtractionDraft_';
import type { BatchCreateAssetsFromCandidatesRequest } from '../models/BatchCreateAssetsFromCandidatesRequest';
import type { ShotCreate } from '../models/ShotCreate';
import type { ShotExtractedCandidateLinkRequest } from '../models/ShotExtractedCandidateLinkRequest';
import type { ShotExtractedDialogueCandidateAcceptRequest } from '../models/ShotExtractedDialogueCandidateAcceptRequest';
import type { ShotPreparationLinkRequest } from '../models/ShotPreparationLinkRequest';
import type { ShotSkipExtractionUpdate } from '../models/ShotSkipExtractionUpdate';
import type { ShotUpdate } from '../models/ShotUpdate';
import type { ShotVideoVersionAdoptRequest } from '../models/ShotVideoVersionAdoptRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioShotsService {
    /**
     * 镜头列表（分页）
     * @returns ApiResponse_PaginatedData_ShotRead__ Successful Response
     * @throws ApiError
     */
    public static listShotsApiV1StudioShotsGet({
        chapterId,
        q,
        order,
        isDesc = false,
        page = 1,
        pageSize = 10,
    }: {
        /**
         * 按章节过滤
         */
        chapterId?: (string | null),
        /**
         * 关键字，过滤 title/script_excerpt
         */
        q?: (string | null),
        order?: (string | null),
        isDesc?: boolean,
        page?: number,
        pageSize?: number,
    }): CancelablePromise<ApiResponse_PaginatedData_ShotRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots',
            query: {
                'chapter_id': chapterId,
                'q': q,
                'order': order,
                'is_desc': isDesc,
                'page': page,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建镜头
     * @returns ApiResponse_ShotRead_ Successful Response
     * @throws ApiError
     */
    public static createShotApiV1StudioShotsPost({
        requestBody,
    }: {
        requestBody: ShotCreate,
    }): CancelablePromise<ApiResponse_ShotRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/shots',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 按章节获取镜头运行时任务态摘要
     * @returns ApiResponse_list_ShotRuntimeSummaryRead__ Successful Response
     * @throws ApiError
     */
    public static listShotRuntimeSummaryApiV1StudioShotsRuntimeSummaryGet({
        chapterId,
    }: {
        /**
         * 章节 ID
         */
        chapterId: string,
    }): CancelablePromise<ApiResponse_list_ShotRuntimeSummaryRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/runtime-summary',
            query: {
                'chapter_id': chapterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 分镜详情：按镜头关联拼装 StudioScriptExtractionDraft
     * @returns ApiResponse_StudioScriptExtractionDraft_ Successful Response
     * @throws ApiError
     */
    public static getShotExtractionDraftApiV1StudioShotsShotIdExtractionDraftGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_StudioScriptExtractionDraft_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/extraction-draft',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头提取候选项
     * @returns ApiResponse_list_ShotExtractedCandidateRead__ Successful Response
     * @throws ApiError
     */
    public static getShotExtractedCandidatesApiV1StudioShotsShotIdExtractedCandidatesGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_list_ShotExtractedCandidateRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/extracted-candidates',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头提取对白候选项
     * @returns ApiResponse_list_ShotExtractedDialogueCandidateRead__ Successful Response
     * @throws ApiError
     */
    public static getShotExtractedDialogueCandidatesApiV1StudioShotsShotIdExtractedDialogueCandidatesGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_list_ShotExtractedDialogueCandidateRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/extracted-dialogue-candidates',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头资产总览（已关联资产 + 提取候选）
     * @returns ApiResponse_ShotAssetsOverviewRead_ Successful Response
     * @throws ApiError
     */
    public static getShotAssetsOverviewApiApiV1StudioShotsShotIdAssetsOverviewGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_ShotAssetsOverviewRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/assets-overview',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头准备页聚合状态
     * @returns ApiResponse_ShotPreparationStateRead_ Successful Response
     * @throws ApiError
     */
    public static getShotPreparationStateApiApiV1StudioShotsShotIdPreparationStateGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_ShotPreparationStateRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/preparation-state',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 准备页关联现有实体并返回最新聚合状态
     * @returns ApiResponse_ShotPreparationMutationResultRead_ Successful Response
     * @throws ApiError
     */
    public static linkExistingAssetForPreparationApiApiV1StudioShotsShotIdPreparationLinkPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: ShotPreparationLinkRequest,
    }): CancelablePromise<ApiResponse_ShotPreparationMutationResultRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/shots/{shot_id}/preparation-link',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 预览镜头视频提示词
     * @returns ApiResponse_ShotVideoPromptPreviewRead_ Successful Response
     * @throws ApiError
     */
    public static previewShotVideoPromptApiV1StudioShotsShotIdVideoPromptPreviewGet({
        shotId,
        templateId,
        referenceMode = 'text_only',
    }: {
        shotId: string,
        /**
         * 指定视频提示词模板 ID；不传则使用默认模板
         */
        templateId?: (string | null),
        /**
         * 参考模式：first/last/key/first_last/first_last_key/text_only。默认 text_only 只渲染提示词本身；传真实模式时会连同该模式要求的参考帧一起渲染
         */
        referenceMode?: string,
    }): CancelablePromise<ApiResponse_ShotVideoPromptPreviewRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/video-prompt-preview',
            path: {
                'shot_id': shotId,
            },
            query: {
                'template_id': templateId,
                'reference_mode': referenceMode,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头视频生成准备度
     * @returns ApiResponse_ShotVideoReadinessRead_ Successful Response
     * @throws ApiError
     */
    public static getShotVideoReadinessApiApiV1StudioShotsShotIdVideoReadinessGet({
        shotId,
        referenceMode = 'text_only',
    }: {
        shotId: string,
        /**
         * 参考模式：first/last/key/first_last/first_last_key/text_only
         */
        referenceMode?: string,
    }): CancelablePromise<ApiResponse_ShotVideoReadinessRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/video-readiness',
            path: {
                'shot_id': shotId,
            },
            query: {
                'reference_mode': referenceMode,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头视频版本（抽卡历史）
     * 按创建时间倒序返回该镜头的全部视频版本，历史版本一律保留。
     * @returns ApiResponse_list_ShotVideoVersionRead__ Successful Response
     * @throws ApiError
     */
    public static listShotVideoVersionsApiApiV1StudioShotsShotIdVideoVersionsGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_list_ShotVideoVersionRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/video-versions',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 切换镜头当前采用的视频版本
     * 把镜头当前采用的视频切到指定历史版本；不删除任何旧版本文件。
     * @returns ApiResponse_ShotRead_ Successful Response
     * @throws ApiError
     */
    public static adoptShotVideoVersionApiApiV1StudioShotsShotIdVideoVersionsAdoptPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: ShotVideoVersionAdoptRequest,
    }): CancelablePromise<ApiResponse_ShotRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/shots/{shot_id}/video-versions/adopt',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 设置是否跳过镜头信息提取
     * @returns ApiResponse_ShotPreparationMutationResultRead_ Successful Response
     * @throws ApiError
     */
    public static updateShotSkipExtractionApiV1StudioShotsShotIdSkipExtractionPatch({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: ShotSkipExtractionUpdate,
    }): CancelablePromise<ApiResponse_ShotPreparationMutationResultRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/shots/{shot_id}/skip-extraction',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 确认并关联镜头提取候选项
     * @returns ApiResponse_ShotPreparationMutationResultRead_ Successful Response
     * @throws ApiError
     */
    public static linkExtractedCandidateApiV1StudioShotsExtractedCandidatesCandidateIdLinkPatch({
        candidateId,
        requestBody,
    }: {
        candidateId: number,
        requestBody: ShotExtractedCandidateLinkRequest,
    }): CancelablePromise<ApiResponse_ShotPreparationMutationResultRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/shots/extracted-candidates/{candidate_id}/link',
            path: {
                'candidate_id': candidateId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 忽略镜头提取候选项
     * @returns ApiResponse_ShotPreparationMutationResultRead_ Successful Response
     * @throws ApiError
     */
    public static ignoreExtractedCandidateApiV1StudioShotsExtractedCandidatesCandidateIdIgnorePatch({
        candidateId,
    }: {
        candidateId: number,
    }): CancelablePromise<ApiResponse_ShotPreparationMutationResultRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/shots/extracted-candidates/{candidate_id}/ignore',
            path: {
                'candidate_id': candidateId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 一键从提取候选项创建/关联资产（人物/场景/道具/服装）
     * 按章节遍历 pending 提取候选，批量创建资产实体并关联到分镜。
     *
     * ToonFlow 式「一键提取资产」：提取完成后一次性把人物/场景/道具/服装落库。
     * @returns ApiResponse_dict_str__Any__ Successful Response
     * @throws ApiError
     */
    public static batchCreateAssetsFromCandidatesApiV1StudioShotsExtractedCandidatesBatchCreateAssetsPost({
        requestBody,
    }: {
        requestBody: BatchCreateAssetsFromCandidatesRequest,
    }): CancelablePromise<ApiResponse_dict_str__Any__> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/shots/extracted-candidates/batch-create-assets',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 接受镜头提取对白候选项
     * @returns ApiResponse_ShotPreparationMutationResultRead_ Successful Response
     * @throws ApiError
     */
    public static acceptExtractedDialogueCandidateApiV1StudioShotsExtractedDialogueCandidatesCandidateIdAcceptPatch({
        candidateId,
        requestBody,
    }: {
        candidateId: number,
        requestBody?: (ShotExtractedDialogueCandidateAcceptRequest | null),
    }): CancelablePromise<ApiResponse_ShotPreparationMutationResultRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/accept',
            path: {
                'candidate_id': candidateId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 忽略镜头提取对白候选项
     * @returns ApiResponse_ShotPreparationMutationResultRead_ Successful Response
     * @throws ApiError
     */
    public static ignoreExtractedDialogueCandidateApiV1StudioShotsExtractedDialogueCandidatesCandidateIdIgnorePatch({
        candidateId,
    }: {
        candidateId: number,
    }): CancelablePromise<ApiResponse_ShotPreparationMutationResultRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/ignore',
            path: {
                'candidate_id': candidateId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头
     * @returns ApiResponse_ShotRead_ Successful Response
     * @throws ApiError
     */
    public static getShotApiV1StudioShotsShotIdGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_ShotRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新镜头
     * @returns ApiResponse_ShotRead_ Successful Response
     * @throws ApiError
     */
    public static updateShotApiV1StudioShotsShotIdPatch({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: ShotUpdate,
    }): CancelablePromise<ApiResponse_ShotRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/shots/{shot_id}',
            path: {
                'shot_id': shotId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除镜头
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteShotApiV1StudioShotsShotIdDelete({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/shots/{shot_id}',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取镜头关联的角色/道具/场景/服装（分页）
     * @returns ApiResponse_PaginatedData_ShotLinkedAssetItem__ Successful Response
     * @throws ApiError
     */
    public static listShotLinkedAssetsApiV1StudioShotsShotIdLinkedAssetsGet({
        shotId,
        page = 1,
        pageSize = 10,
    }: {
        shotId: string,
        page?: number,
        pageSize?: number,
    }): CancelablePromise<ApiResponse_PaginatedData_ShotLinkedAssetItem__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/shots/{shot_id}/linked-assets',
            path: {
                'shot_id': shotId,
            },
            query: {
                'page': page,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
