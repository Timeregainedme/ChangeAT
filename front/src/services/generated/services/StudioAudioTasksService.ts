/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_VoiceItem__ } from '../models/ApiResponse_list_VoiceItem__';
import type { ApiResponse_TaskCreated_ } from '../models/ApiResponse_TaskCreated_';
import type { StudioAudioTaskRequest } from '../models/StudioAudioTaskRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioAudioTasksService {
    /**
     * Create Speech Task
     * 创建语音合成任务（异步轮询）。
     *
     * 参数在请求期即按供应商能力校验（评审 R-20），非法参数返回 422 而不是先建任务再失败。
     * @returns ApiResponse_TaskCreated_ Successful Response
     * @throws ApiError
     */
    public static createSpeechTaskApiV1StudioAudioTasksSpeechPost({
        requestBody,
    }: {
        requestBody: StudioAudioTaskRequest,
    }): CancelablePromise<ApiResponse_TaskCreated_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/audio-tasks/speech',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Audio Voices
     * 查询供应商可用音色（当前仅优云智算 IndexTTS 支持）。
     * @returns ApiResponse_list_VoiceItem__ Successful Response
     * @throws ApiError
     */
    public static listAudioVoicesApiV1StudioAudioTasksVoicesGet({
        modelId,
        kind = 'preset',
    }: {
        /**
         * 音频模型 ID；不传则使用默认音频模型
         */
        modelId?: (string | null),
        /**
         * 音色类型：preset 或 custom
         */
        kind?: string,
    }): CancelablePromise<ApiResponse_list_VoiceItem__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/audio-tasks/voices',
            query: {
                'model_id': modelId,
                'kind': kind,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
