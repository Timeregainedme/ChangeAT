/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_dict_str__Any__ } from '../models/ApiResponse_dict_str__Any__';
import type { ApiResponse_RenderedPromptResponse_ } from '../models/ApiResponse_RenderedPromptResponse_';
import type { ApiResponse_RenderedShotFramePromptRead_ } from '../models/ApiResponse_RenderedShotFramePromptRead_';
import type { ApiResponse_TaskCreated_ } from '../models/ApiResponse_TaskCreated_';
import type { BatchAssetImageTaskRequest } from '../models/BatchAssetImageTaskRequest';
import type { ShotFrameImageTaskRequest } from '../models/ShotFrameImageTaskRequest';
import type { ShotFramePromptRenderRequest } from '../models/ShotFramePromptRenderRequest';
import type { StudioImageTaskRequest } from '../models/StudioImageTaskRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioImageTasksService {
    /**
     * 演员图片生成（任务版）
     * 为指定演员创建图片生成任务，并通过 `GenerationTaskLink` 关联。
     * @returns ApiResponse_TaskCreated_ Successful Response
     * @throws ApiError
     */
    public static createActorImageGenerationTaskApiV1StudioImageTasksActorsActorIdImageTasksPost({
        actorId,
        requestBody,
    }: {
        actorId: string,
        requestBody: StudioImageTaskRequest,
    }): CancelablePromise<ApiResponse_TaskCreated_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/actors/{actor_id}/image-tasks',
            path: {
                'actor_id': actorId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 演员图片提示词渲染
     * @returns ApiResponse_RenderedPromptResponse_ Successful Response
     * @throws ApiError
     */
    public static renderActorImagePromptApiV1StudioImageTasksActorsActorIdRenderPromptPost({
        actorId,
        requestBody,
    }: {
        actorId: string,
        requestBody: StudioImageTaskRequest,
    }): CancelablePromise<ApiResponse_RenderedPromptResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/actors/{actor_id}/render-prompt',
            path: {
                'actor_id': actorId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 道具/场景/服装图片生成（任务版）
     * 为道具/场景/服装创建图片生成任务。
     *
     * - asset_type: prop / scene / costume
     * - path 参数 asset_id 为对应资产 ID
     * - body.image_id 必须为该资产下对应图片表记录的 ID（PropImage/SceneImage/CostumeImage）
     * @returns ApiResponse_TaskCreated_ Successful Response
     * @throws ApiError
     */
    public static createAssetImageGenerationTaskApiV1StudioImageTasksAssetsAssetTypeAssetIdImageTasksPost({
        assetType,
        assetId,
        requestBody,
    }: {
        assetType: string,
        assetId: string,
        requestBody: StudioImageTaskRequest,
    }): CancelablePromise<ApiResponse_TaskCreated_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/assets/{asset_type}/{asset_id}/image-tasks',
            path: {
                'asset_type': assetType,
                'asset_id': assetId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 道具/场景/服装图片提示词渲染
     * @returns ApiResponse_RenderedPromptResponse_ Successful Response
     * @throws ApiError
     */
    public static renderAssetImagePromptApiV1StudioImageTasksAssetsAssetTypeAssetIdRenderPromptPost({
        assetType,
        assetId,
        requestBody,
    }: {
        assetType: string,
        assetId: string,
        requestBody: StudioImageTaskRequest,
    }): CancelablePromise<ApiResponse_RenderedPromptResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/assets/{asset_type}/{asset_id}/render-prompt',
            path: {
                'asset_type': assetType,
                'asset_id': assetId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 角色图片生成（任务版）
     * 为角色创建图片生成任务（对应 CharacterImage 业务）。
     *
     * - path 参数 character_id 为 Character.id
     * - body.image_id 必须为该角色下的 CharacterImage.id
     * @returns ApiResponse_TaskCreated_ Successful Response
     * @throws ApiError
     */
    public static createCharacterImageGenerationTaskApiV1StudioImageTasksCharactersCharacterIdImageTasksPost({
        characterId,
        requestBody,
    }: {
        characterId: string,
        requestBody: StudioImageTaskRequest,
    }): CancelablePromise<ApiResponse_TaskCreated_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/characters/{character_id}/image-tasks',
            path: {
                'character_id': characterId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 角色图片提示词渲染
     * @returns ApiResponse_RenderedPromptResponse_ Successful Response
     * @throws ApiError
     */
    public static renderCharacterImagePromptApiV1StudioImageTasksCharactersCharacterIdRenderPromptPost({
        characterId,
        requestBody,
    }: {
        characterId: string,
        requestBody: StudioImageTaskRequest,
    }): CancelablePromise<ApiResponse_RenderedPromptResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/characters/{character_id}/render-prompt',
            path: {
                'character_id': characterId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 一键批量生成资产参考图（人物/场景/道具/服装）
     * 为指定项目下指定类型资产（缺省全部）批量创建图片生成任务。
     *
     * 对每个资产自动选取 front 优先的图片槽位并生成提示词（复用资产图渲染逻辑），
     * 返回 {"tasks": [{asset_id, task_id, prompt}], "skipped": [...]}。
     *
     * 响应语义（评审 D-12）：本端点声明 `status_code=201`（批量创建了资源），因此必须用
     * `created_response` 让响应体 `code=201` 与 HTTP 状态码一致；此前误用 `success_response`
     * （固定 `code=200`）会出现「201 状态 + 200 业务码」的自相矛盾。
     * `success_response` 是全局公共函数，保持其默认 `code=200` 不动，避免影响其它 200 路由。
     * @returns ApiResponse_dict_str__Any__ Successful Response
     * @throws ApiError
     */
    public static createBatchAssetImageTasksApiV1StudioImageTasksAssetsBatchImageTasksPost({
        requestBody,
    }: {
        requestBody: BatchAssetImageTaskRequest,
    }): CancelablePromise<ApiResponse_dict_str__Any__> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/assets/batch-image-tasks',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 镜头分镜帧图片生成（任务版）
     * 为镜头分镜帧图片生成任务（基于 `shot_id + frame_type` 自动定位数据）。
     * @returns ApiResponse_TaskCreated_ Successful Response
     * @throws ApiError
     */
    public static createShotFrameImageGenerationTaskApiV1StudioImageTasksShotShotIdFrameImageTasksPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: ShotFrameImageTaskRequest,
    }): CancelablePromise<ApiResponse_TaskCreated_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/shot/{shot_id}/frame-image-tasks',
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
     * 镜头分镜帧提示词渲染
     * @returns ApiResponse_RenderedShotFramePromptRead_ Successful Response
     * @throws ApiError
     */
    public static renderShotFramePromptApiV1StudioImageTasksShotShotIdFrameRenderPromptPost({
        shotId,
        requestBody,
    }: {
        shotId: string,
        requestBody: ShotFramePromptRenderRequest,
    }): CancelablePromise<ApiResponse_RenderedShotFramePromptRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/image-tasks/shot/{shot_id}/frame-render-prompt',
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
}
