/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Google 登录请求。
 *
 * `credential` 由 Google Identity Services 在浏览器端签发（ID Token，JWT）。
 * 后端只做校验与账号匹配，不接受前端自报的 email，避免伪造身份。
 */
export type GoogleLoginRequest = {
    /**
     * Google ID Token（GIS 返回的 credential）
     */
    credential: string;
};

