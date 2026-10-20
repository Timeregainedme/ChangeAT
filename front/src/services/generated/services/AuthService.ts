/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_dict_ } from '../models/ApiResponse_dict_';
import type { ApiResponse_TokenResponse_ } from '../models/ApiResponse_TokenResponse_';
import type { ApiResponse_UserRead_ } from '../models/ApiResponse_UserRead_';
import type { LoginRequest } from '../models/LoginRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AuthService {
    /**
     * 账号密码登录
     * 校验账号密码并签发访问令牌。
     * @returns ApiResponse_TokenResponse_ Successful Response
     * @throws ApiError
     */
    public static loginApiV1AuthLoginPost({
        requestBody,
    }: {
        requestBody: LoginRequest,
    }): CancelablePromise<ApiResponse_TokenResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/login',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 当前登录用户
     * 返回当前 token 对应的用户信息，用于前端校验登录态是否仍有效。
     * @returns ApiResponse_UserRead_ Successful Response
     * @throws ApiError
     */
    public static meApiV1AuthMeGet(): CancelablePromise<ApiResponse_UserRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/me',
        });
    }
    /**
     * 登出（前端丢弃 token 即可，此接口仅用于统一调用）
     * @returns ApiResponse_dict_ Successful Response
     * @throws ApiError
     */
    public static logoutApiV1AuthLogoutPost(): CancelablePromise<ApiResponse_dict_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/logout',
        });
    }
}
