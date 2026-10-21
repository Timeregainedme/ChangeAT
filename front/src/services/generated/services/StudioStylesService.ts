/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_ProjectStyleOptionRead__ } from '../models/ApiResponse_list_ProjectStyleOptionRead__';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_ProjectStyleOptionRead_ } from '../models/ApiResponse_ProjectStyleOptionRead_';
import type { ProjectStyleOptionCreate } from '../models/ProjectStyleOptionCreate';
import type { ProjectStyleOptionUpdate } from '../models/ProjectStyleOptionUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioStylesService {
    /**
     * 列出风格目录
     * @returns ApiResponse_list_ProjectStyleOptionRead__ Successful Response
     * @throws ApiError
     */
    public static listStylesApiV1StudioStylesGet(): CancelablePromise<ApiResponse_list_ProjectStyleOptionRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/styles',
        });
    }
    /**
     * 新增风格
     * @returns ApiResponse_ProjectStyleOptionRead_ Successful Response
     * @throws ApiError
     */
    public static createStyleApiV1StudioStylesPost({
        requestBody,
    }: {
        requestBody: ProjectStyleOptionCreate,
    }): CancelablePromise<ApiResponse_ProjectStyleOptionRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/styles',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 修改风格
     * @returns ApiResponse_ProjectStyleOptionRead_ Successful Response
     * @throws ApiError
     */
    public static updateStyleApiV1StudioStylesStyleIdPatch({
        styleId,
        requestBody,
    }: {
        styleId: string,
        requestBody: ProjectStyleOptionUpdate,
    }): CancelablePromise<ApiResponse_ProjectStyleOptionRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/styles/{style_id}',
            path: {
                'style_id': styleId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除风格
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteStyleApiV1StudioStylesStyleIdDelete({
        styleId,
    }: {
        styleId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/styles/{style_id}',
            path: {
                'style_id': styleId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
