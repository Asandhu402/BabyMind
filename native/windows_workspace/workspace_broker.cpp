#include "workspace_broker.h"

#include <algorithm>
#include <cwctype>
#include <string_view>

namespace {

bool is_reserved_device_name(std::wstring_view component) {
    const size_t dot = component.find(L'.');
    std::wstring_view stem = component.substr(0, dot);
    std::wstring folded;
    folded.reserve(stem.size());
    for (wchar_t ch : stem) {
        folded.push_back(static_cast<wchar_t>(std::towupper(ch)));
    }

    if (folded == L"CON" || folded == L"PRN" || folded == L"AUX" || folded == L"NUL") {
        return true;
    }
    if (folded.size() == 4 &&
        (folded.compare(0, 3, L"COM") == 0 || folded.compare(0, 3, L"LPT") == 0) &&
        folded[3] >= L'1' && folded[3] <= L'9') {
        return true;
    }
    return false;
}

bool valid_component(std::wstring_view component) {
    if (component.empty() || component == L"." || component == L"..") {
        return false;
    }
    if (component.size() > 255 || component.back() == L'.' || component.back() == L' ') {
        return false;
    }
    if (is_reserved_device_name(component)) {
        return false;
    }

    for (wchar_t ch : component) {
        if (ch < 0x20 || ch == L'<' || ch == L'>' || ch == L':' ||
            ch == L'"' || ch == L'|' || ch == L'?' || ch == L'*' ||
            ch == L'\\') {
            return false;
        }
    }
    return true;
}

}  // namespace

extern "C" BM_WS_API bm_ws_status bm_ws_validate_relative_path(
    const wchar_t* path,
    size_t length,
    int allow_empty
) {
    if (path == nullptr && length != 0) {
        return BM_WS_INVALID_ARGUMENT;
    }
    if (length > 500) {
        return BM_WS_INVALID_RELATIVE_PATH;
    }
    if (length == 0) {
        return allow_empty ? BM_WS_OK : BM_WS_INVALID_RELATIVE_PATH;
    }
    if (path == nullptr || path[0] == L'/' || path[length - 1] == L'/') {
        return BM_WS_INVALID_RELATIVE_PATH;
    }

    size_t component_start = 0;
    for (size_t index = 0; index <= length; ++index) {
        if (index == length || path[index] == L'/') {
            const std::wstring_view component(path + component_start, index - component_start);
            if (!valid_component(component)) {
                return BM_WS_INVALID_RELATIVE_PATH;
            }
            component_start = index + 1;
        }
    }
    return BM_WS_OK;
}

extern "C" BM_WS_API bm_ws_status bm_ws_open_workspace_root(const wchar_t* absolute_path) {
    (void)absolute_path;
    return BM_WS_NOT_IMPLEMENTED;
}

extern "C" BM_WS_API bm_ws_status bm_ws_read_text(
    const wchar_t* relative_path,
    size_t max_bytes
) {
    (void)relative_path;
    (void)max_bytes;
    return BM_WS_NOT_IMPLEMENTED;
}

extern "C" BM_WS_API bm_ws_status bm_ws_create_new_text(
    const wchar_t* relative_path,
    const uint8_t* content,
    size_t content_bytes,
    size_t max_bytes
) {
    (void)relative_path;
    (void)content;
    (void)content_bytes;
    (void)max_bytes;
    return BM_WS_NOT_IMPLEMENTED;
}
