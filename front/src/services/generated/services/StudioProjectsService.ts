/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_PaginatedData_ProjectRead__ } from '../models/ApiResponse_PaginatedData_ProjectRead__';
import type { ApiResponse_ProjectCharacterRecurrenceRead_ } from '../models/ApiResponse_ProjectCharacterRecurrenceRead_';
import type { ApiResponse_ProjectProductionReadinessRead_ } from '../models/ApiResponse_ProjectProductionReadinessRead_';
import type { ApiResponse_ProjectRead_ } from '../models/ApiResponse_ProjectRead_';
import type { ApiResponse_ProjectStyleOptionsRead_ } from '../models/ApiResponse_ProjectStyleOptionsRead_';
import type { ProjectCreate } from '../models/ProjectCreate';
import type { ProjectUpdate } from '../models/ProjectUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioProjectsService {
    /**
     * 获取项目风格候选项
     * @returns ApiResponse_ProjectStyleOptionsRead_ Successful Response
     * @throws ApiError
     */
    public static getProjectStyleOptionsApiV1StudioProjectsStyleOptionsGet(): CancelablePromise<ApiResponse_ProjectStyleOptionsRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/projects/style-options',
        });
    }
    /**
     * 项目列表（分页）
     * @returns ApiResponse_PaginatedData_ProjectRead__ Successful Response
     * @throws ApiError
     */
    public static listProjectsApiV1StudioProjectsGet({
        q,
        order,
        isDesc = false,
        page = 1,
        pageSize = 10,
    }: {
        /**
         * 关键字，过滤 name/description
         */
        q?: (string | null),
        /**
         * 排序字段
         */
        order?: (string | null),
        /**
         * 是否倒序
         */
        isDesc?: boolean,
        page?: number,
        pageSize?: number,
    }): CancelablePromise<ApiResponse_PaginatedData_ProjectRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/projects',
            query: {
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
     * 创建项目
     * @returns ApiResponse_ProjectRead_ Successful Response
     * @throws ApiError
     */
    public static createProjectApiV1StudioProjectsPost({
        requestBody,
    }: {
        requestBody: ProjectCreate,
    }): CancelablePromise<ApiResponse_ProjectRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/projects',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取项目
     * @returns ApiResponse_ProjectRead_ Successful Response
     * @throws ApiError
     */
    public static getProjectApiV1StudioProjectsProjectIdGet({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_ProjectRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/projects/{project_id}',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新项目
     * @returns ApiResponse_ProjectRead_ Successful Response
     * @throws ApiError
     */
    public static updateProjectApiV1StudioProjectsProjectIdPatch({
        projectId,
        requestBody,
    }: {
        projectId: string,
        requestBody: ProjectUpdate,
    }): CancelablePromise<ApiResponse_ProjectRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/projects/{project_id}',
            path: {
                'project_id': projectId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除项目
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteProjectApiV1StudioProjectsProjectIdDelete({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/projects/{project_id}',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 项目开工预检
     * 开工前一次性检查：默认模型与 API Key、比例、每角色音色、分镜参考图、提取确认。
     *
     * 只读聚合，不修改任何状态；返回 `ready=false` 时逐项给出缺失原因。
     * @returns ApiResponse_ProjectProductionReadinessRead_ Successful Response
     * @throws ApiError
     */
    public static getProjectProductionReadinessApiApiV1StudioProjectsProjectIdProductionReadinessGet({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_ProjectProductionReadinessRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/projects/{project_id}/production-readiness',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 角色跨集出现情况
     * 回答「这个项目里哪些角色是主角级、需要绑定演员」。
     *
     * 为什么单独一个端点而不是塞进角色列表：要不要绑演员取决于角色出现在几集里，
     * 而章节数必须经 `shot_character_links ⋈ shots` 才能算出来。做成一次项目级只读查询，
     * 前端在新建/编辑角色时就能把「仅 1 集，可不绑」与「跨 N 集，建议绑」直接标在卡片上。
     * @returns ApiResponse_ProjectCharacterRecurrenceRead_ Successful Response
     * @throws ApiError
     */
    public static getProjectCharacterRecurrenceApiApiV1StudioProjectsProjectIdCharacterRecurrenceGet({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_ProjectCharacterRecurrenceRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/projects/{project_id}/character-recurrence',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
