#include "workspace_broker.h"

#include <cassert>
#include <cwchar>
#include <iostream>
#include <string>

static bm_ws_status validate(const wchar_t* value, int allow_empty = 0) {
    return bm_ws_validate_relative_path(value, std::wcslen(value), allow_empty);
}

int main() {
    assert(validate(L"src/main.py") == BM_WS_OK);
    assert(validate(L"docs/guide.md") == BM_WS_OK);
    assert(validate(L"folder/file name.txt") == BM_WS_OK);
    assert(validate(L"", 1) == BM_WS_OK);
    assert(validate(L"") == BM_WS_INVALID_RELATIVE_PATH);

    assert(validate(L"../outside.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/../outside.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"./file.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"/rooted.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder//file.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"..\\outside.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"C:/Windows/win.ini") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/stream.txt:secret") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/CON.txt") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/LPT1.log") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/name.") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/name ") == BM_WS_INVALID_RELATIVE_PATH);
    assert(validate(L"folder/<bad>.txt") == BM_WS_INVALID_RELATIVE_PATH);

    const std::wstring too_long(501, L'a');
    assert(bm_ws_validate_relative_path(too_long.c_str(), too_long.size(), 0) == BM_WS_INVALID_RELATIVE_PATH);
    assert(bm_ws_validate_relative_path(nullptr, 1, 0) == BM_WS_INVALID_ARGUMENT);
    assert(bm_ws_open_workspace_root(L"C:\\workspace") == BM_WS_NOT_IMPLEMENTED);
    assert(bm_ws_read_text(L"file.txt", 1024) == BM_WS_NOT_IMPLEMENTED);
    assert(bm_ws_create_new_text(L"new.txt", nullptr, 0, 1024) == BM_WS_NOT_IMPLEMENTED);

    std::wcout << L"Native workspace lexical validation tests passed. "
                  L"Filesystem operations remain disabled.\n";
    return 0;
}
