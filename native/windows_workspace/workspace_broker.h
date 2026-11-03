#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define BM_WS_API __declspec(dllexport)
#else
#define BM_WS_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum bm_ws_status {
    BM_WS_OK = 0,
    BM_WS_INVALID_ARGUMENT = 1,
    BM_WS_INVALID_RELATIVE_PATH = 2,
    BM_WS_NOT_IMPLEMENTED = 3
} bm_ws_status;

/*
 * Validates the lexical form of a relative Windows workspace path.
 *
 * This is input hygiene only. It does NOT access the filesystem and does NOT
 * establish containment, protect against reparse points, or prevent races.
 * A successful result must never be treated as authorization to open a path.
 *
 * Accepted separator: forward slash only. Empty path is valid only when
 * allow_empty is nonzero (for operations targeting the workspace root).
 */
BM_WS_API bm_ws_status bm_ws_validate_relative_path(
    const wchar_t* path,
    size_t length,
    int allow_empty
);

/*
 * Filesystem operations intentionally remain unavailable in this prototype.
 * These entry points are reserved so future bindings cannot accidentally
 * substitute Python path-based operations.
 */
BM_WS_API bm_ws_status bm_ws_open_workspace_root(const wchar_t* absolute_path);
BM_WS_API bm_ws_status bm_ws_read_text(const wchar_t* relative_path, size_t max_bytes);
BM_WS_API bm_ws_status bm_ws_create_new_text(
    const wchar_t* relative_path,
    const uint8_t* content,
    size_t content_bytes,
    size_t max_bytes
);

#ifdef __cplusplus
}
#endif
