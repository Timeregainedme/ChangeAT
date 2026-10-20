/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 对外暴露的用户信息（不含 password_hash）。
 */
export type UserRead = {
    id: number;
    username: string;
    display_name?: (string | null);
    is_active: boolean;
    email?: (string | null);
    avatar_url?: (string | null);
    auth_provider?: string;
    created_at?: (string | null);
};

