/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_ProjectTimelineRead_ } from '../models/ApiResponse_ProjectTimelineRead_';
import type { ApiResponse_TimelineExportRead_ } from '../models/ApiResponse_TimelineExportRead_';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioTimelineService {
    /**
     * 项目时间线（按章节顺序聚合的分镜片段）
     * @returns ApiResponse_ProjectTimelineRead_ Successful Response
     * @throws ApiError
     */
    public static getProjectTimelineApiApiV1StudioTimelineProjectsProjectIdGet({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_ProjectTimelineRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/timeline/projects/{project_id}',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 导出成片（ffmpeg 拼接全部镜头视频）
     * @returns ApiResponse_TimelineExportRead_ Successful Response
     * @throws ApiError
     */
    public static exportProjectTimelineApiApiV1StudioTimelineProjectsProjectIdExportPost({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_TimelineExportRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/timeline/projects/{project_id}/export',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
