-- 012-rewrite-prompt-templates.sql
-- 提示词改造第 2 档：C0/C1/C2 资产模板整改 + B1 帧模板入 DB。
-- 由 backend/scripts/gen_prompt_templates_sql.py 生成，请勿手工编辑。
-- 幂等：已存在同类别则 UPDATE，不存在则 INSERT。
-- 注意：video_prompt 故意不播种 —— 视频提示词走 IR → H3 渲染器（A1）。

SET NAMES utf8mb4;

-- ===== actor_image_front =====
UPDATE `prompt_templates` SET `name` = '演员正面图片提示词', `preview` = '演员正面定妆照', `content` = '{{ style_pack }}

电影级演员定妆照，正面平视半身，纯色中性背景，脚下有自然接触阴影：
{{ description }}

画面要求：
- 正面平视机位，双眼直视镜头，肩线水平，构图居中偏上
- 面部细节清晰可辨：眼型、眉形、鼻梁、唇形、下颌线与发际线交代明确
- 柔和均匀的主光加一侧补光，面部无硬阴影、无油光、无过曝
- 服装平整，发型完整，不出现手持道具
- 写实皮肤质感，保留真实毛孔与细纹，不做磨皮
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'actor_image_front';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'actor_image_front', '演员正面图片提示词', '演员正面定妆照', '{{ style_pack }}

电影级演员定妆照，正面平视半身，纯色中性背景，脚下有自然接触阴影：
{{ description }}

画面要求：
- 正面平视机位，双眼直视镜头，肩线水平，构图居中偏上
- 面部细节清晰可辨：眼型、眉形、鼻梁、唇形、下颌线与发际线交代明确
- 柔和均匀的主光加一侧补光，面部无硬阴影、无油光、无过曝
- 服装平整，发型完整，不出现手持道具
- 写实皮肤质感，保留真实毛孔与细纹，不做磨皮
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'actor_image_front');

-- ===== actor_image_other =====
UPDATE `prompt_templates` SET `name` = '演员侧面/后面图片提示词', `preview` = '演员非正面视角', `content` = '{{ style_pack }}

与正面定妆照完全同一个人，身份严格一致：相同脸型、五官比例、发型、发色、肤色与年龄：
{{ description }}

视角完全切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不得残留任何正面元素（不出现正脸、不出现双眼直视镜头）
- 头部、颈部与肩部的朝向符合该视角，透视与轮廓正确，无面部扭曲
- 站位、景别、光线与背景承接正面定妆照，人物比例一致
- 不出现手持道具，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'actor_image_other';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'actor_image_other', '演员侧面/后面图片提示词', '演员非正面视角', '{{ style_pack }}

与正面定妆照完全同一个人，身份严格一致：相同脸型、五官比例、发型、发色、肤色与年龄：
{{ description }}

视角完全切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不得残留任何正面元素（不出现正脸、不出现双眼直视镜头）
- 头部、颈部与肩部的朝向符合该视角，透视与轮廓正确，无面部扭曲
- 站位、景别、光线与背景承接正面定妆照，人物比例一致
- 不出现手持道具，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'actor_image_other');

-- ===== character_image_front =====
UPDATE `prompt_templates` SET `name` = '角色正面图片提示词', `preview` = '角色正面定妆照（身份锁定）', `content` = '{{ style_pack }}

角色定妆照，正面平视半身，纯色中性背景，脚下有自然接触阴影。

身份参考（严格锁定，不得改动）：
- 若提供了参考图，参考图中的人物即为本角色「{{ name }}」的身份基准
- 参考图只约束长相、发型、发色、肤色、体型与年龄，不得换脸、不得改变发型发色与年龄感
- 若参考图包含服装，则沿用该服装，服装颜色与款式不得改变
{{ description }}

画面要求：
- 正面平视机位，双眼直视镜头，肩线水平，构图居中偏上
- 柔和均匀的主光加一侧补光，面部无硬阴影、无油光、无过曝
- 写实皮肤质感，保留真实毛孔与细纹，不做磨皮
- 不出现手持道具，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'character_image_front';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'character_image_front', '角色正面图片提示词', '角色正面定妆照（身份锁定）', '{{ style_pack }}

角色定妆照，正面平视半身，纯色中性背景，脚下有自然接触阴影。

身份参考（严格锁定，不得改动）：
- 若提供了参考图，参考图中的人物即为本角色「{{ name }}」的身份基准
- 参考图只约束长相、发型、发色、肤色、体型与年龄，不得换脸、不得改变发型发色与年龄感
- 若参考图包含服装，则沿用该服装，服装颜色与款式不得改变
{{ description }}

画面要求：
- 正面平视机位，双眼直视镜头，肩线水平，构图居中偏上
- 柔和均匀的主光加一侧补光，面部无硬阴影、无油光、无过曝
- 写实皮肤质感，保留真实毛孔与细纹，不做磨皮
- 不出现手持道具，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'character_image_front');

-- ===== character_image_other =====
UPDATE `prompt_templates` SET `name` = '角色侧面/后面图片提示词', `preview` = '角色非正面视角（身份锁定）', `content` = '{{ style_pack }}

与角色正面定妆照完全同一个人，身份严格一致：相同脸型、五官比例、发型、发色、肤色、年龄与服装。

视角完全切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不得残留任何正面元素（不出现正脸、不出现双眼直视镜头）
- 头部、颈部与肩部的朝向符合该视角，透视与轮廓正确，无面部扭曲
- 站位、景别、光线与背景承接正面定妆照，人物比例一致
- 不出现手持道具，画面内不出现文字、标识与水印
{{ description }}
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'character_image_other';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'character_image_other', '角色侧面/后面图片提示词', '角色非正面视角（身份锁定）', '{{ style_pack }}

与角色正面定妆照完全同一个人，身份严格一致：相同脸型、五官比例、发型、发色、肤色、年龄与服装。

视角完全切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不得残留任何正面元素（不出现正脸、不出现双眼直视镜头）
- 头部、颈部与肩部的朝向符合该视角，透视与轮廓正确，无面部扭曲
- 站位、景别、光线与背景承接正面定妆照，人物比例一致
- 不出现手持道具，画面内不出现文字、标识与水印
{{ description }}
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'character_image_other');

-- ===== prop_image_front =====
UPDATE `prompt_templates` SET `name` = '道具图片提示词', `preview` = '高质量道具特写', `content` = '{{ style_pack }}

道具特写，主体居中，简洁环境背景：
{{ description }}

画面要求：
- 镜头方向：正面；道具完整入画，不被裁切，不出现手持痕迹
- 材质交代明确：金属反光、皮革纹理、玻璃折射、布料纤维与磨损细节可见
- 柔和的侧上方主光，轮廓光勾边，主体与背景分离清楚
- 除道具本身外不加多余元素，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'prop_image_front';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'prop_image_front', '道具图片提示词', '高质量道具特写', '{{ style_pack }}

道具特写，主体居中，简洁环境背景：
{{ description }}

画面要求：
- 镜头方向：正面；道具完整入画，不被裁切，不出现手持痕迹
- 材质交代明确：金属反光、皮革纹理、玻璃折射、布料纤维与磨损细节可见
- 柔和的侧上方主光，轮廓光勾边，主体与背景分离清楚
- 除道具本身外不加多余元素，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'prop_image_front');

-- ===== prop_image_other =====
UPDATE `prompt_templates` SET `name` = '道具侧面/后面图片提示词', `preview` = '道具非正面视角', `content` = '{{ style_pack }}

与正面图完全同一个道具，形制、颜色、材质与磨损状态严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不残留正面特征
- 透视正确，结构关系合理，比例与正面图一致
- 光线与背景承接正面图，材质表现保持一致
- 不出现手持痕迹，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'prop_image_other';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'prop_image_other', '道具侧面/后面图片提示词', '道具非正面视角', '{{ style_pack }}

与正面图完全同一个道具，形制、颜色、材质与磨损状态严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不残留正面特征
- 透视正确，结构关系合理，比例与正面图一致
- 光线与背景承接正面图，材质表现保持一致
- 不出现手持痕迹，画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'prop_image_other');

-- ===== scene_image_front =====
UPDATE `prompt_templates` SET `name` = '场景图片提示词', `preview` = '高质量电影场景', `content` = '{{ style_pack }}

电影级场景定景画面，竖屏构图，空间层次清楚：
{{ description }}

画面要求：
- 镜头方向：正面；画面正中为场景主体区域，前中后景分明
- 光源方向明确，环境氛围自然（雾、雨丝、光斑、尘埃等按需出现）
- 空间尺度合理，建筑与陈设结构正确，透视不畸变
- 为演员留出可站立的表演空间，地面与墙面材质细节清楚
- 画面内不出现文字、标识与水印，不出现人物正脸特写
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'scene_image_front';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'scene_image_front', '场景图片提示词', '高质量电影场景', '{{ style_pack }}

电影级场景定景画面，竖屏构图，空间层次清楚：
{{ description }}

画面要求：
- 镜头方向：正面；画面正中为场景主体区域，前中后景分明
- 光源方向明确，环境氛围自然（雾、雨丝、光斑、尘埃等按需出现）
- 空间尺度合理，建筑与陈设结构正确，透视不畸变
- 为演员留出可站立的表演空间，地面与墙面材质细节清楚
- 画面内不出现文字、标识与水印，不出现人物正脸特写
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'scene_image_front');

-- ===== scene_image_other =====
UPDATE `prompt_templates` SET `name` = '场景侧面/后面图片提示词', `preview` = '同一场景的其他机位', `content` = '{{ style_pack }}

与正面定景画面完全同一场景，空间结构、陈设与光线条件严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 同一空间内的另一个机位，墙、地面、门窗与陈设的相对位置必须自洽
- 不出现与正面图矛盾的结构，不新增主要陈设
- 光线方向相对场景保持一致，色温与氛围延续
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'scene_image_other';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'scene_image_other', '场景侧面/后面图片提示词', '同一场景的其他机位', '{{ style_pack }}

与正面定景画面完全同一场景，空间结构、陈设与光线条件严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 同一空间内的另一个机位，墙、地面、门窗与陈设的相对位置必须自洽
- 不出现与正面图矛盾的结构，不新增主要陈设
- 光线方向相对场景保持一致，色温与氛围延续
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'scene_image_other');

-- ===== costume_image_front =====
UPDATE `prompt_templates` SET `name` = '服装图片提示词', `preview` = '高质量服装呈现', `content` = '{{ style_pack }}

服装整体呈现，完整全身穿着，简洁中性背景：
{{ description }}

画面要求：
- 服装为画面主体，占画面三分之二以上，版型与剪裁交代清楚
- 布料纹理、车线、钮扣、拉链、金属配件与褶皱细节清晰可见
- 柔和的正面主光加侧向补光，服装颜色还原准确，无偏色
- 画面内不出现文字、标识与水印，不出现人物面部特写分散注意力
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'costume_image_front';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'costume_image_front', '服装图片提示词', '高质量服装呈现', '{{ style_pack }}

服装整体呈现，完整全身穿着，简洁中性背景：
{{ description }}

画面要求：
- 服装为画面主体，占画面三分之二以上，版型与剪裁交代清楚
- 布料纹理、车线、钮扣、拉链、金属配件与褶皱细节清晰可见
- 柔和的正面主光加侧向补光，服装颜色还原准确，无偏色
- 画面内不出现文字、标识与水印，不出现人物面部特写分散注意力
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'costume_image_front');

-- ===== costume_image_other =====
UPDATE `prompt_templates` SET `name` = '服装侧面/后面图片提示词', `preview` = '同一套服装的其他视角', `content` = '{{ style_pack }}

与正面服装图完全同一套服装，版型、颜色、材质与细节严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不残留正面特征
- 同一件衣服的侧面/背面结构合理，接缝、开衩与配饰位置自洽
- 光线与背景承接正面图，布料质感与颜色保持一致
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'costume_image_other';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'costume_image_other', '服装侧面/后面图片提示词', '同一套服装的其他视角', '{{ style_pack }}

与正面服装图完全同一套服装，版型、颜色、材质与细节严格一致：
{{ description }}

视角切换为：{{ view_angle }}
- 只呈现该视角应有的信息，不残留正面特征
- 同一件衣服的侧面/背面结构合理，接缝、开衩与配饰位置自洽
- 光线与背景承接正面图，布料质感与颜色保持一致
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'costume_image_other');

-- ===== combined =====
UPDATE `prompt_templates` SET `name` = '通用兜底图片提示词', `preview` = '无专用类别时的通用画面模板', `content` = '{{ style_pack }}

高质量{{ visual_style }}画面主体：
{{ description }}

画面要求：
- 主体明确、构图稳定，主体占画面主要面积
- 光线方向明确，材质与纹理表现到位
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', `variables` = CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'combined';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'combined', '通用兜底图片提示词', '无专用类别时的通用画面模板', '{{ style_pack }}

高质量{{ visual_style }}画面主体：
{{ description }}

画面要求：
- 主体明确、构图稳定，主体占画面主要面积
- 光线方向明确，材质与纹理表现到位
- 画面内不出现文字、标识与水印
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}', CAST('["name", "description", "tags", "visual_style", "style", "view_angle", "quality_level", "format", "style_pack", "negative_prompt"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'combined');

-- ===== frame_head_prompt =====
UPDATE `prompt_templates` SET `name` = '镜头首帧提示词模板', `preview` = '分镜首帧基础提示词（后台可编辑）', `content` = '你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**首帧基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：优先描述镜头开始时最先看到的画面建立信息，强调开场定场、主体初始状态与进入情境的第一印象；只表现触发瞬间或最初反应，不要直接写成后续完成动作、最终姿态或情绪爆发完成态。
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 首帧 基础提示词，JSON：{{"prompt": "..."}}）
', `variables` = CAST('["script_excerpt", "title", "visual_style", "style", "unify_style", "camera_shot", "angle", "movement", "atmosphere", "shot_description", "mood_tags", "vfx_type", "vfx_note", "duration", "scene_id", "dialog_summary", "action_beats", "action_beat_phases", "selected_action_beat_phase", "selected_action_beat_text", "character_context", "scene_context", "prop_context", "costume_context", "subject_priority", "previous_shot_title", "previous_shot_script_excerpt", "previous_shot_end_state", "next_shot_title", "next_shot_script_excerpt", "next_shot_start_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "frame_specific_guidance", "director_command_summary", "retry_guidance"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'frame_head_prompt';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'frame_head_prompt', '镜头首帧提示词模板', '分镜首帧基础提示词（后台可编辑）', '你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**首帧基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：优先描述镜头开始时最先看到的画面建立信息，强调开场定场、主体初始状态与进入情境的第一印象；只表现触发瞬间或最初反应，不要直接写成后续完成动作、最终姿态或情绪爆发完成态。
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 首帧 基础提示词，JSON：{{"prompt": "..."}}）
', CAST('["script_excerpt", "title", "visual_style", "style", "unify_style", "camera_shot", "angle", "movement", "atmosphere", "shot_description", "mood_tags", "vfx_type", "vfx_note", "duration", "scene_id", "dialog_summary", "action_beats", "action_beat_phases", "selected_action_beat_phase", "selected_action_beat_text", "character_context", "scene_context", "prop_context", "costume_context", "subject_priority", "previous_shot_title", "previous_shot_script_excerpt", "previous_shot_end_state", "next_shot_title", "next_shot_script_excerpt", "next_shot_start_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "frame_specific_guidance", "director_command_summary", "retry_guidance"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'frame_head_prompt');

-- ===== frame_tail_prompt =====
UPDATE `prompt_templates` SET `name` = '镜头尾帧提示词模板', `preview` = '分镜尾帧基础提示词（后台可编辑）', `content` = '你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**尾帧基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：优先描述镜头结束时最终停留的画面状态，强调动作收束、人物结束姿态、视线落点或情绪余韵。
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 尾帧 基础提示词，JSON：{{"prompt": "..."}}）
', `variables` = CAST('["script_excerpt", "title", "visual_style", "style", "unify_style", "camera_shot", "angle", "movement", "atmosphere", "shot_description", "mood_tags", "vfx_type", "vfx_note", "duration", "scene_id", "dialog_summary", "action_beats", "action_beat_phases", "selected_action_beat_phase", "selected_action_beat_text", "character_context", "scene_context", "prop_context", "costume_context", "subject_priority", "previous_shot_title", "previous_shot_script_excerpt", "previous_shot_end_state", "next_shot_title", "next_shot_script_excerpt", "next_shot_start_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "frame_specific_guidance", "director_command_summary", "retry_guidance"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'frame_tail_prompt';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'frame_tail_prompt', '镜头尾帧提示词模板', '分镜尾帧基础提示词（后台可编辑）', '你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**尾帧基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：优先描述镜头结束时最终停留的画面状态，强调动作收束、人物结束姿态、视线落点或情绪余韵。
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 尾帧 基础提示词，JSON：{{"prompt": "..."}}）
', CAST('["script_excerpt", "title", "visual_style", "style", "unify_style", "camera_shot", "angle", "movement", "atmosphere", "shot_description", "mood_tags", "vfx_type", "vfx_note", "duration", "scene_id", "dialog_summary", "action_beats", "action_beat_phases", "selected_action_beat_phase", "selected_action_beat_text", "character_context", "scene_context", "prop_context", "costume_context", "subject_priority", "previous_shot_title", "previous_shot_script_excerpt", "previous_shot_end_state", "next_shot_title", "next_shot_script_excerpt", "next_shot_start_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "frame_specific_guidance", "director_command_summary", "retry_guidance"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'frame_tail_prompt');

-- ===== frame_key_prompt =====
UPDATE `prompt_templates` SET `name` = '镜头关键帧提示词模板', `preview` = '分镜关键帧基础提示词（后台可编辑）', `content` = '你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**关键帧基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：优先捕捉镜头中最具代表性、最有戏剧张力或信息密度最高的瞬间，不必平均描述整个过程。
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 关键帧 基础提示词，JSON：{{"prompt": "..."}}）
', `variables` = CAST('["script_excerpt", "title", "visual_style", "style", "unify_style", "camera_shot", "angle", "movement", "atmosphere", "shot_description", "mood_tags", "vfx_type", "vfx_note", "duration", "scene_id", "dialog_summary", "action_beats", "action_beat_phases", "selected_action_beat_phase", "selected_action_beat_text", "character_context", "scene_context", "prop_context", "costume_context", "subject_priority", "previous_shot_title", "previous_shot_script_excerpt", "previous_shot_end_state", "next_shot_title", "next_shot_script_excerpt", "next_shot_start_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "frame_specific_guidance", "director_command_summary", "retry_guidance"]' AS JSON), `is_default` = 1, `is_system` = 1, `updated_at` = NOW() WHERE `category` = 'frame_key_prompt';
INSERT INTO `prompt_templates` (`id`, `category`, `name`, `preview`, `content`, `variables`, `is_default`, `is_system`, `created_at`, `updated_at`) SELECT UUID(), 'frame_key_prompt', '镜头关键帧提示词模板', '分镜关键帧基础提示词（后台可编辑）', '你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**关键帧基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：优先捕捉镜头中最具代表性、最有戏剧张力或信息密度最高的瞬间，不必平均描述整个过程。
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 关键帧 基础提示词，JSON：{{"prompt": "..."}}）
', CAST('["script_excerpt", "title", "visual_style", "style", "unify_style", "camera_shot", "angle", "movement", "atmosphere", "shot_description", "mood_tags", "vfx_type", "vfx_note", "duration", "scene_id", "dialog_summary", "action_beats", "action_beat_phases", "selected_action_beat_phase", "selected_action_beat_text", "character_context", "scene_context", "prop_context", "costume_context", "subject_priority", "previous_shot_title", "previous_shot_script_excerpt", "previous_shot_end_state", "next_shot_title", "next_shot_script_excerpt", "next_shot_start_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "frame_specific_guidance", "director_command_summary", "retry_guidance"]' AS JSON), 1, 1, NOW(), NOW() FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `prompt_templates` WHERE `category` = 'frame_key_prompt');
