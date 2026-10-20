package handler

import (
	"fmt"
	"strconv"
)

// parsePagination 解析并校验分页参数。
//
// **必须严格解析，不能静默回退默认值**：Python 侧用 FastAPI 的
// `Query(ge=1, le=100)` 声明，非法输入会返回 422；如果 Go 侧把
// `page_size=abc` 当成 10 处理，前端会拿到第一页却以为翻页生效了 ——
// 这种「不报错的错误」比直接失败更难排查。
//
// 返回的 message 复刻 FastAPI 的校验文案（`query.page_size: Input should be ...`），
// 目的是让切流前后的 422 响应逐字节一致，影子对比不用逐条解释差异。
func parsePagination(rawPage, rawPageSize string) (page int, pageSize int, errMessage string) {
	page = 1
	pageSize = 10

	if v, err := parsePositiveInt(rawPage); err != nil {
		return 0, 0, fmt.Sprintf("query.page: %s", err.Error())
	} else if v != nil {
		page = *v
	}
	if page < 1 {
		return 0, 0, "query.page: Input should be greater than or equal to 1"
	}

	if v, err := parsePositiveInt(rawPageSize); err != nil {
		return 0, 0, fmt.Sprintf("query.page_size: %s", err.Error())
	} else if v != nil {
		pageSize = *v
	}
	if pageSize < 1 {
		return 0, 0, "query.page_size: Input should be greater than or equal to 1"
	}
	if pageSize > 100 {
		return 0, 0, "query.page_size: Input should be less than or equal to 100"
	}

	return page, pageSize, ""
}

// parsePositiveInt 解析可选整型参数。
//
// 返回 (nil, nil) 表示「未提供」，调用方使用默认值；
// 返回 (nil, err) 表示「提供了但不合法」，必须当作 422 而不是回退默认。
func parsePositiveInt(raw string) (*int, error) {
	if raw == "" {
		return nil, nil
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return nil, fmt.Errorf("Input should be a valid integer, unable to parse string as an integer")
	}
	return &v, nil
}

// parsePaginationWithDefault 与 parsePagination 相同，但可指定 page_size 默认值。
//
// 任务列表的 page_size 默认是 20，而项目/章节是 10 —— 与 Python 各路由的
// Query 默认值保持一致，避免切流后前端拿到的条数变化。
func parsePaginationWithDefault(rawPage, rawPageSize string, defaultPageSize int) (page int, pageSize int, errMessage string) {
	page = 1
	pageSize = defaultPageSize

	if v, err := parsePositiveInt(rawPage); err != nil {
		return 0, 0, "query.page: " + err.Error()
	} else if v != nil {
		page = *v
	}
	if page < 1 {
		return 0, 0, "query.page: Input should be greater than or equal to 1"
	}

	if v, err := parsePositiveInt(rawPageSize); err != nil {
		return 0, 0, "query.page_size: " + err.Error()
	} else if v != nil {
		pageSize = *v
	}
	if pageSize < 1 {
		return 0, 0, "query.page_size: Input should be greater than or equal to 1"
	}
	if pageSize > 100 {
		return 0, 0, "query.page_size: Input should be less than or equal to 100"
	}
	return page, pageSize, ""
}
