/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_dict_ } from '../models/ApiResponse_dict_';
import type { ApiResponse_TokenResponse_ } from '../models/ApiResponse_TokenResponse_';
import type { ApiResponse_UserRead_ } from '../models/ApiResponse_UserRead_';
import type { GoogleLoginRequest } from '../models/GoogleLoginRequest';
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
     * Google 登录（Google Identity Services ID Token）
     * 用前端 GIS 取得的 ID Token 登录。
     *
     * 流程：
     * 1. 服务端向 Google 校验 ID Token（受众、签发方、邮箱验证状态）；
     * 2. 按 Google 邮箱名单过滤（`GOOGLE_ALLOWED_EMAILS` 为空时放行全部已验证邮箱）；
     * 3. 按 google_sub / email 找到或创建账号；
     * 4. 签发与本地登录相同的 JWT，前端无需区分登录方式。
     *
     * 任何身份信息都来自 Google 的校验结果，不采信请求体里的自报字段。
     * @returns ApiResponse_TokenResponse_ Successful Response
     * @throws ApiError
     */
    public static loginWithGoogleApiV1AuthGooglePost({
        requestBody,
    }: {
        requestBody: GoogleLoginRequest,
    }): CancelablePromise<ApiResponse_TokenResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/google',
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
