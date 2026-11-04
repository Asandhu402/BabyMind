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
    BM_WS_NOT_IMPLEMENTED = 3,
    BM_WS_IO_ERROR = 4,
    BM_WS_REPARSE_POINT = 5,
    BM_WS_NOT_DIRECTORY = 6,
    BM_WS_TOO_LARGE = 7,
    BM_WS_BUFFER_TOO_SMALL = 8
} bm_ws_status;

/* Lexical validation only; never use its result as filesystem authorization. */
BM_WS_API bm_ws_status bm_ws_validate_relative_path(
    const wchar_t* path, size_t length, int allow_empty);

/*
 * Opens a fixed local NTFS workspace by walking each component relative to a
 * pinned directory handle. The returned opaque handle must be closed.
 * UNC paths, non-fixed drives, non-NTFS volumes and reparse components fail.
 */
BM_WS_API bm_ws_status bm_ws_open_workspace_root(
    const wchar_t* absolute_path, void** out_root);
BM_WS_API void bm_ws_close_workspace_root(void* root);


typedef struct bm_ws_directory_entry {
    wchar_t name[256];
    uint32_t type; /* 0=file, 1=directory, 2=reparse point (never followed) */
} bm_ws_directory_entry;

/* Lists one directory only; an empty relative path selects the workspace root.
 * Capacity is limited to 200 entries. Reparse points are identified, never followed. */
BM_WS_API bm_ws_status bm_ws_list_directory(
    void* root, const wchar_t* relative_path, bm_ws_directory_entry* entries,
    size_t capacity, size_t* entries_written, int* truncated);

/* Reads through a handle opened relative to the pinned root/parent handles.
 * output_capacity must be at least max_bytes + 1 to detect oversized files. */
BM_WS_API bm_ws_status bm_ws_read_text(
    void* root, const wchar_t* relative_path, size_t max_bytes,
    uint8_t* output, size_t output_capacity, size_t* bytes_read);

/* Creates a new file exclusively. Existing files are never overwritten. */
BM_WS_API bm_ws_status bm_ws_create_new_text(
    void* root, const wchar_t* relative_path, const uint8_t* content,
    size_t content_bytes, size_t max_bytes);

#ifdef __cplusplus
}
#endif
