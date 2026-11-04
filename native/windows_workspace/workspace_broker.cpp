#include "workspace_broker.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winternl.h>

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <cwctype>
#include <string>
#include <string_view>
#include <vector>

#ifndef FILE_OPEN_REPARSE_POINT
#define FILE_OPEN_REPARSE_POINT 0x00200000
#endif
#ifndef FILE_NON_DIRECTORY_FILE
#define FILE_NON_DIRECTORY_FILE 0x00000040
#endif
#ifndef FILE_DIRECTORY_FILE
#define FILE_DIRECTORY_FILE 0x00000001
#endif
#ifndef FILE_SYNCHRONOUS_IO_NONALERT
#define FILE_SYNCHRONOUS_IO_NONALERT 0x00000020
#endif
#ifndef FILE_OPEN
#define FILE_OPEN 0x00000001
#endif
#ifndef FILE_CREATE
#define FILE_CREATE 0x00000002
#endif

extern "C" BM_WS_API uint32_t bm_ws_abi_version(void) { return 1; }

namespace {
constexpr size_t kMaxPathChars = 500;
constexpr size_t kMaxReadBytes = 16 * 1024 * 1024;
constexpr size_t kMaxCreateBytes = 1024 * 1024;

// Bound every NUL-terminated string received through the native ABI before
// constructing std::wstring or passing it to path validation. This prevents
// an unterminated caller buffer from triggering an unbounded wcslen scan.
bool bounded_wide_length(const wchar_t* value, size_t maximum, size_t* length) {
    if (value == nullptr || length == nullptr) return false;
    for (size_t i = 0; i <= maximum; ++i) {
        if (value[i] == L'\0') {
            *length = i;
            return true;
        }
    }
    return false;
}

class UniqueHandle {
public:
    explicit UniqueHandle(HANDLE value = INVALID_HANDLE_VALUE) : value_(value) {}
    ~UniqueHandle() { reset(); }
    UniqueHandle(const UniqueHandle&) = delete;
    UniqueHandle& operator=(const UniqueHandle&) = delete;
    UniqueHandle(UniqueHandle&& other) noexcept : value_(other.release()) {}
    UniqueHandle& operator=(UniqueHandle&& other) noexcept {
        if (this != &other) reset(other.release());
        return *this;
    }
    HANDLE get() const { return value_; }
    HANDLE release() {
        HANDLE value = value_;
        value_ = INVALID_HANDLE_VALUE;
        return value;
    }
    void reset(HANDLE value = INVALID_HANDLE_VALUE) {
        if (value_ != INVALID_HANDLE_VALUE && value_ != nullptr) CloseHandle(value_);
        value_ = value;
    }
    bool valid() const { return value_ != INVALID_HANDLE_VALUE && value_ != nullptr; }
private:
    HANDLE value_;
};

bool is_reserved_device_name(std::wstring_view component) {
    const size_t dot = component.find(L'.');
    const auto stem = component.substr(0, dot);
    std::wstring folded;
    folded.reserve(stem.size());
    for (wchar_t ch : stem) folded.push_back(static_cast<wchar_t>(std::towupper(ch)));
    if (folded == L"CON" || folded == L"PRN" || folded == L"AUX" || folded == L"NUL") return true;
    return folded.size() == 4 &&
        (folded.compare(0, 3, L"COM") == 0 || folded.compare(0, 3, L"LPT") == 0) &&
        folded[3] >= L'1' && folded[3] <= L'9';
}

bool valid_component(std::wstring_view component) {
    if (component.empty() || component == L"." || component == L".." ||
        component.size() > 255 || component.back() == L'.' || component.back() == L' ' ||
        is_reserved_device_name(component)) return false;
    for (wchar_t ch : component) {
        if (ch < 0x20 || ch == L'<' || ch == L'>' || ch == L':' || ch == L'"' ||
            ch == L'|' || ch == L'?' || ch == L'*' || ch == L'\\' || ch == L'/') return false;
    }
    return true;
}

bool is_reparse_or_wrong_type(HANDLE handle, bool want_directory, bm_ws_status* status) {
    FILE_ATTRIBUTE_TAG_INFO tag{};
    if (!GetFileInformationByHandleEx(handle, FileAttributeTagInfo, &tag, sizeof(tag))) {
        *status = BM_WS_IO_ERROR;
        return true;
    }
    if ((tag.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        *status = BM_WS_REPARSE_POINT;
        return true;
    }
    const bool is_directory = (tag.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
    if (is_directory != want_directory) {
        *status = BM_WS_NOT_DIRECTORY;
        return true;
    }
    return false;
}

using NtCreateFileFunction = NTSTATUS (NTAPI*)(
    PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES, PIO_STATUS_BLOCK,
    PLARGE_INTEGER, ULONG, ULONG, ULONG, ULONG, PVOID, ULONG);

NtCreateFileFunction resolve_nt_create_file() {
    static NtCreateFileFunction function = []() -> NtCreateFileFunction {
        HMODULE module = GetModuleHandleW(L"ntdll.dll");
        if (module == nullptr) return nullptr;
        FARPROC address = GetProcAddress(module, "NtCreateFile");
#pragma warning(push)
#pragma warning(disable: 4191)
        NtCreateFileFunction resolved = reinterpret_cast<NtCreateFileFunction>(address);
#pragma warning(pop)
        return resolved;
    }();
    return function;
}

bool nt_open_relative(HANDLE parent, std::wstring_view component,
                      ACCESS_MASK access, ULONG disposition, ULONG options,
                      ULONG share_access, UniqueHandle* output) {
    if (component.empty() || component.size() > 255) return false;
    std::wstring name(component);
    UNICODE_STRING unicode_name{};
    unicode_name.Buffer = name.data();
    unicode_name.Length = static_cast<USHORT>(name.size() * sizeof(wchar_t));
    unicode_name.MaximumLength = unicode_name.Length;

    OBJECT_ATTRIBUTES attributes{};
    attributes.Length = sizeof(attributes);
    attributes.RootDirectory = parent;
    attributes.ObjectName = &unicode_name;
    attributes.Attributes = OBJ_CASE_INSENSITIVE;

    IO_STATUS_BLOCK io_status{};
    HANDLE opened = INVALID_HANDLE_VALUE;
    const NtCreateFileFunction create_file = resolve_nt_create_file();
    if (create_file == nullptr) return false;
    const NTSTATUS status = create_file(
        &opened, access | SYNCHRONIZE, &attributes, &io_status, nullptr,
        FILE_ATTRIBUTE_NORMAL, share_access,
        disposition, options | FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT,
        nullptr, 0);
    if (status < 0) return false;
    output->reset(opened);
    return true;
}

bm_ws_status open_parent(void* root_value, const wchar_t* relative_path,
                         UniqueHandle* parent, std::wstring* leaf) {
    if (root_value == nullptr || relative_path == nullptr || leaf == nullptr) return BM_WS_INVALID_ARGUMENT;
    size_t length = 0;
    if (!bounded_wide_length(relative_path, kMaxPathChars, &length) ||
        bm_ws_validate_relative_path(relative_path, length, 0) != BM_WS_OK)
        return BM_WS_INVALID_RELATIVE_PATH;

    std::vector<std::wstring> components;
    size_t start = 0;
    for (size_t i = 0; i <= length; ++i) {
        if (i == length || relative_path[i] == L'/') {
            components.emplace_back(relative_path + start, i - start);
            start = i + 1;
        }
    }
    if (components.empty()) return BM_WS_INVALID_RELATIVE_PATH;

    // Duplicate the caller's root handle; never transfer or close caller ownership.
    UniqueHandle current;
    HANDLE duplicate = INVALID_HANDLE_VALUE;
    if (!DuplicateHandle(GetCurrentProcess(), reinterpret_cast<HANDLE>(root_value),
                         GetCurrentProcess(), &duplicate, 0, FALSE,
                         DUPLICATE_SAME_ACCESS)) return BM_WS_IO_ERROR;
    current.reset(duplicate);

    for (size_t i = 0; i + 1 < components.size(); ++i) {
        UniqueHandle next;
        if (!nt_open_relative(current.get(), components[i],
                FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES, FILE_OPEN,
                FILE_DIRECTORY_FILE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &next)) return BM_WS_IO_ERROR;
        bm_ws_status status = BM_WS_OK;
        if (is_reparse_or_wrong_type(next.get(), true, &status)) return status;
        current = std::move(next);
    }
    *leaf = components.back();
    *parent = std::move(current);
    return BM_WS_OK;
}

bm_ws_status open_root_component(HANDLE parent, const std::wstring& component,
                                 UniqueHandle* child) {
    if (!valid_component(component)) return BM_WS_INVALID_RELATIVE_PATH;
    if (!nt_open_relative(parent, component,
            FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES, FILE_OPEN,
            FILE_DIRECTORY_FILE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, child)) return BM_WS_IO_ERROR;
    bm_ws_status status = BM_WS_OK;
    if (is_reparse_or_wrong_type(child->get(), true, &status)) return status;
    return BM_WS_OK;
}

bm_ws_status open_directory_handle(void* root_value, const wchar_t* relative_path,
                                   UniqueHandle* directory) {
    if (root_value == nullptr || relative_path == nullptr || directory == nullptr)
        return BM_WS_INVALID_ARGUMENT;
    size_t length = 0;
    if (!bounded_wide_length(relative_path, kMaxPathChars, &length) ||
        bm_ws_validate_relative_path(relative_path, length, 1) != BM_WS_OK)
        return BM_WS_INVALID_RELATIVE_PATH;
    HANDLE duplicate = INVALID_HANDLE_VALUE;
    if (!DuplicateHandle(GetCurrentProcess(), reinterpret_cast<HANDLE>(root_value),
                         GetCurrentProcess(), &duplicate, 0, FALSE,
                         DUPLICATE_SAME_ACCESS)) return BM_WS_IO_ERROR;
    UniqueHandle current(duplicate);
    if (length == 0) {
        *directory = std::move(current);
        return BM_WS_OK;
    }
    size_t start = 0;
    for (size_t i = 0; i <= length; ++i) {
        if (i != length && relative_path[i] != L'/') continue;
        std::wstring component(relative_path + start, i - start);
        if (!valid_component(component)) return BM_WS_INVALID_RELATIVE_PATH;
        UniqueHandle next;
        if (!nt_open_relative(current.get(), component,
                FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES, FILE_OPEN,
                FILE_DIRECTORY_FILE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &next))
            return BM_WS_IO_ERROR;
        bm_ws_status status = BM_WS_OK;
        if (is_reparse_or_wrong_type(next.get(), true, &status)) return status;
        current = std::move(next);
        start = i + 1;
    }
    *directory = std::move(current);
    return BM_WS_OK;
}

} // namespace

extern "C" BM_WS_API bm_ws_status bm_ws_validate_relative_path(
    const wchar_t* path, size_t length, int allow_empty) {
    if (path == nullptr && length != 0) return BM_WS_INVALID_ARGUMENT;
    if (length > kMaxPathChars) return BM_WS_INVALID_RELATIVE_PATH;
    if (length == 0) return allow_empty ? BM_WS_OK : BM_WS_INVALID_RELATIVE_PATH;
    if (path == nullptr || path[0] == L'/' || path[length - 1] == L'/') return BM_WS_INVALID_RELATIVE_PATH;
    size_t start = 0;
    for (size_t i = 0; i <= length; ++i) {
        if (i == length || path[i] == L'/') {
            if (!valid_component(std::wstring_view(path + start, i - start))) return BM_WS_INVALID_RELATIVE_PATH;
            start = i + 1;
        }
    }
    return BM_WS_OK;
}

extern "C" BM_WS_API bm_ws_status bm_ws_open_workspace_root(
    const wchar_t* absolute_path, void** out_root) {
    if (absolute_path == nullptr || out_root == nullptr) return BM_WS_INVALID_ARGUMENT;
    *out_root = nullptr;
    size_t length = 0;
    if (!bounded_wide_length(absolute_path, kMaxPathChars, &length))
        return BM_WS_INVALID_ARGUMENT;
    const std::wstring absolute(absolute_path, length);
    if (length < 4 || length > kMaxPathChars || absolute_path[1] != L':' ||
        absolute_path[2] != L'\\' || !((absolute_path[0] >= L'A' && absolute_path[0] <= L'Z') ||
        (absolute_path[0] >= L'a' && absolute_path[0] <= L'z'))) return BM_WS_INVALID_ARGUMENT;

    wchar_t volume_root[] = L"C:\\";
    volume_root[0] = absolute_path[0];
    if (GetDriveTypeW(volume_root) != DRIVE_FIXED) return BM_WS_INVALID_ARGUMENT;
    wchar_t filesystem[MAX_PATH]{};
    if (!GetVolumeInformationW(volume_root, nullptr, 0, nullptr, nullptr, nullptr,
                               filesystem, MAX_PATH) || _wcsicmp(filesystem, L"NTFS") != 0) {
        return BM_WS_INVALID_ARGUMENT;
    }

    std::wstring extended_root = L"\\\\?\\";
    extended_root += volume_root;
    UniqueHandle current(CreateFileW(extended_root.c_str(),
        FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (!current.valid()) return BM_WS_IO_ERROR;
    bm_ws_status status = BM_WS_OK;
    if (is_reparse_or_wrong_type(current.get(), true, &status)) return status;

    size_t start = 3;
    if (start == length) return BM_WS_INVALID_ARGUMENT; // Never grant a volume root as a workspace.
    while (start < length) {
        size_t end = absolute.find(L'\\', start);
        if (end == std::wstring::npos) end = length;
        if (end == start) return BM_WS_INVALID_ARGUMENT;
        std::wstring component(absolute_path + start, end - start);
        if (!valid_component(component)) return BM_WS_INVALID_ARGUMENT;
        UniqueHandle next;
        status = open_root_component(current.get(), component, &next);
        if (status != BM_WS_OK) return status;
        current = std::move(next);
        start = end + 1;
        if (end == length) break;
    }
    *out_root = current.release();
    return BM_WS_OK;
}

extern "C" BM_WS_API void bm_ws_close_workspace_root(void* root) {
    if (root != nullptr) CloseHandle(reinterpret_cast<HANDLE>(root));
}


extern "C" BM_WS_API bm_ws_status bm_ws_list_directory(
    void* root, const wchar_t* relative_path, bm_ws_directory_entry* entries,
    size_t capacity, size_t* entries_written, int* truncated) {
    if (entries_written == nullptr || truncated == nullptr ||
        (entries == nullptr && capacity != 0)) return BM_WS_INVALID_ARGUMENT;
    *entries_written = 0;
    *truncated = 0;
    if (capacity == 0 || capacity > 200) return BM_WS_INVALID_ARGUMENT;

    UniqueHandle directory;
    bm_ws_status status = open_directory_handle(root, relative_path, &directory);
    if (status != BM_WS_OK) return status;

    alignas(FILE_ID_BOTH_DIR_INFO) BYTE buffer[64 * 1024]{};
    FILE_INFO_BY_HANDLE_CLASS info_class = FileIdBothDirectoryRestartInfo;
    for (;;) {
        if (!GetFileInformationByHandleEx(directory.get(), info_class,
                                           buffer, static_cast<DWORD>(sizeof(buffer)))) {
            const DWORD error = GetLastError();
            if (error == ERROR_NO_MORE_FILES) break;
            return BM_WS_IO_ERROR;
        }
        info_class = FileIdBothDirectoryInfo;
        size_t offset = 0;
        for (;;) {
            if (offset > sizeof(buffer) - sizeof(FILE_ID_BOTH_DIR_INFO))
                return BM_WS_IO_ERROR;
            const auto* item = reinterpret_cast<const FILE_ID_BOTH_DIR_INFO*>(buffer + offset);
            const size_t header_bytes = offsetof(FILE_ID_BOTH_DIR_INFO, FileName);
            if ((item->FileNameLength % sizeof(wchar_t)) != 0 ||
                item->FileNameLength > 255 * sizeof(wchar_t) ||
                header_bytes + item->FileNameLength > sizeof(buffer) - offset)
                return BM_WS_IO_ERROR;
            const size_t chars = item->FileNameLength / sizeof(wchar_t);
            const std::wstring_view name(item->FileName, chars);
            if (name != L"." && name != L"..") {
                if (*entries_written == capacity) {
                    *truncated = 1;
                    return BM_WS_OK;
                }
                bm_ws_directory_entry& output = entries[*entries_written];
                std::memset(&output, 0, sizeof(output));
                if (chars != 0) std::memcpy(output.name, item->FileName, item->FileNameLength);
                if ((item->FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                    output.type = 2;
                else if ((item->FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
                    output.type = 1;
                else
                    output.type = 0;
                ++(*entries_written);
            }
            if (item->NextEntryOffset == 0) break;
            if (item->NextEntryOffset < header_bytes + item->FileNameLength ||
                item->NextEntryOffset > sizeof(buffer) - offset)
                return BM_WS_IO_ERROR;
            offset += item->NextEntryOffset;
        }
    }
    return BM_WS_OK;
}

extern "C" BM_WS_API bm_ws_status bm_ws_read_text(
    void* root, const wchar_t* relative_path, size_t max_bytes,
    uint8_t* output, size_t output_capacity, size_t* bytes_read) {
    if (bytes_read == nullptr || output == nullptr) return BM_WS_INVALID_ARGUMENT;
    *bytes_read = 0;
    if (max_bytes == 0 || max_bytes > kMaxReadBytes) return BM_WS_TOO_LARGE;
    if (output_capacity < max_bytes + 1) return BM_WS_BUFFER_TOO_SMALL;
    UniqueHandle parent;
    std::wstring leaf;
    bm_ws_status status = open_parent(root, relative_path, &parent, &leaf);
    if (status != BM_WS_OK) return status;

    UniqueHandle file;
    if (!nt_open_relative(parent.get(), leaf, FILE_READ_DATA | FILE_READ_ATTRIBUTES,
                          FILE_OPEN, FILE_NON_DIRECTORY_FILE, FILE_SHARE_READ, &file)) return BM_WS_IO_ERROR;
    if (is_reparse_or_wrong_type(file.get(), false, &status)) return status;

    size_t total = 0;
    while (total < max_bytes + 1) {
        DWORD received = 0;
        const DWORD request = static_cast<DWORD>(max_bytes + 1 - total);
        if (!ReadFile(file.get(), output + total, request, &received, nullptr)) return BM_WS_IO_ERROR;
        if (received == 0) break;
        total += received;
    }
    if (total > max_bytes) return BM_WS_TOO_LARGE;
    *bytes_read = total;
    return BM_WS_OK;
}

extern "C" BM_WS_API bm_ws_status bm_ws_create_new_text(
    void* root, const wchar_t* relative_path, const uint8_t* content,
    size_t content_bytes, size_t max_bytes) {
    if (content == nullptr && content_bytes != 0) return BM_WS_INVALID_ARGUMENT;
    if (max_bytes == 0 || max_bytes > kMaxCreateBytes || content_bytes > max_bytes) return BM_WS_TOO_LARGE;
    UniqueHandle parent;
    std::wstring leaf;
    bm_ws_status status = open_parent(root, relative_path, &parent, &leaf);
    if (status != BM_WS_OK) return status;

    UniqueHandle file;
    if (!nt_open_relative(parent.get(), leaf,
            FILE_WRITE_DATA | FILE_READ_ATTRIBUTES, FILE_CREATE,
            FILE_NON_DIRECTORY_FILE, FILE_SHARE_READ, &file)) return BM_WS_IO_ERROR;
    if (is_reparse_or_wrong_type(file.get(), false, &status)) return status;

    size_t offset = 0;
    while (offset < content_bytes) {
        const DWORD chunk = static_cast<DWORD>(std::min<size_t>(content_bytes - offset, MAXDWORD));
        DWORD written = 0;
        if (!WriteFile(file.get(), content + offset, chunk, &written, nullptr) || written == 0) return BM_WS_IO_ERROR;
        offset += written;
    }
    if (!FlushFileBuffers(file.get())) return BM_WS_IO_ERROR;
    return BM_WS_OK;
}
