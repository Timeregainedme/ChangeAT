/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserRead } from './UserRead';
/**
 * 登录成功后的令牌与用户信息。
 */
export type TokenResponse = {
    access_token: string;
    token_type?: string;
    /**
     * 有效期（秒）
     */
    expires_in: number;
    user: UserRead;
};

