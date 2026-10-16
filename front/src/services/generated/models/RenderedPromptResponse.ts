/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type RenderedPromptResponse = {
    /**
     * 渲染后的提示词（已套用模板与变量替换）
     */
    prompt: string;
    /**
     * 参考图 file_id 列表（自动选择；顺序有效）
     */
    images?: Array<string>;
    /**
     * 参考图缺失说明。为空表示参考图完整；非空时必须在前端显著展示 —— 角色图会引用所绑演员图与服装图，任一侧缺失（未绑定 / 所绑资产还没出图）时生成仍会成功，但结果与设定不一致，属于必须让用户在发起前看到的信息。
     */
    reference_warnings?: Array<string>;
};

