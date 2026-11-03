#include "workspace_broker.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cwchar>
#include <iostream>
#include <string>
#include <vector>

#define CHECK(expression) do { if (!(expression)) { std::wcerr << L"CHECK failed at line " << __LINE__ << L"\n"; return __LINE__; } } while (false)

static bm_ws_status validate(const wchar_t* value, int allow_empty = 0) {
    return bm_ws_validate_relative_path(value, std::wcslen(value), allow_empty);
}

int main() {
    CHECK(validate(L"src/main.py") == BM_WS_OK);
    CHECK(validate(L"docs/guide.md") == BM_WS_OK);
    CHECK(validate(L"folder/file name.txt") == BM_WS_OK);
    CHECK(validate(L"", 1) == BM_WS_OK);
    CHECK(validate(L"") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"../outside.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/../outside.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"./file.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"/rooted.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder//file.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"..\\outside.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"C:/Windows/win.ini") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/stream.txt:secret") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/CON.txt") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/LPT1.log") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/name.") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/name ") == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(validate(L"folder/<bad>.txt") == BM_WS_INVALID_RELATIVE_PATH);

    const std::wstring too_long(501, L'a');
    CHECK(bm_ws_validate_relative_path(too_long.c_str(), too_long.size(), 0) == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(bm_ws_validate_relative_path(nullptr, 1, 0) == BM_WS_INVALID_ARGUMENT);

    wchar_t temp[MAX_PATH]{};
    CHECK(GetTempPathW(MAX_PATH, temp) != 0);
    wchar_t candidate[MAX_PATH]{};
    CHECK(GetTempFileNameW(temp, L"bmw", 0, candidate) != 0);
    CHECK(DeleteFileW(candidate) != 0);
    CHECK(CreateDirectoryW(candidate, nullptr) != 0);
    std::wstring root_path(candidate);
    const std::wstring nested = root_path + L"\\nested";
    CHECK(CreateDirectoryW(nested.c_str(), nullptr) != 0);

    void* root = nullptr;
    CHECK(bm_ws_open_workspace_root(root_path.c_str(), &root) == BM_WS_OK);
    CHECK(root != nullptr);

    const uint8_t payload[] = {'B','a','b','y','M','i','n','d'};
    CHECK(bm_ws_create_new_text(root, L"nested/hello.txt", payload, sizeof(payload), 1024) == BM_WS_OK);
    uint8_t output[1025]{};
    size_t bytes_read = 0;
    CHECK(bm_ws_read_text(root, L"nested/hello.txt", 1024, output, sizeof(output), &bytes_read) == BM_WS_OK);
    CHECK(bytes_read == sizeof(payload));
    CHECK(std::string(reinterpret_cast<char*>(output), bytes_read) == "BabyMind");

    CHECK(bm_ws_create_new_text(root, L"nested/hello.txt", payload, sizeof(payload), 1024) == BM_WS_IO_ERROR);
    CHECK(bm_ws_read_text(root, L"../outside.txt", 1024, output, sizeof(output), &bytes_read) == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(bm_ws_read_text(root, L"nested/absent.txt", 1024, output, sizeof(output), &bytes_read) == BM_WS_IO_ERROR);
    CHECK(bm_ws_read_text(root, L"nested/hello.txt", 1024, output, 4, &bytes_read) == BM_WS_TOO_LARGE);

    bm_ws_close_workspace_root(root);
    CHECK(DeleteFileW((nested + L"\\hello.txt").c_str()) != 0);
    CHECK(RemoveDirectoryW(nested.c_str()) != 0);
    CHECK(RemoveDirectoryW(root_path.c_str()) != 0);

    std::wcout << L"Handle-relative workspace tests passed. Python integration remains disabled.\n";
    return 0;
}
