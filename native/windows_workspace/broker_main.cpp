#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "broker_protocol.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cwchar>
#include <iostream>
#include <vector>

namespace {
constexpr DWORD kExitNotAppContainer = 10;
constexpr DWORD kExitBadInput = 20;
constexpr DWORD kExitDeniedNotImplemented = 30;
constexpr DWORD kExitIoFailure = 40;
constexpr ULONGLONG kReadDeadlineMs = 5000;

bool running_in_appcontainer_without_capabilities() {
    HANDLE token = GetCurrentProcessToken();
    BOOL is_appcontainer = FALSE;
    DWORD returned = 0;
    if (!GetTokenInformation(token, TokenIsAppContainer,
                             &is_appcontainer, sizeof(is_appcontainer), &returned) ||
        is_appcontainer != TRUE) {
        return false;
    }

    // This broker currently needs no capabilities at all. In particular it
    // receives no internetClient/internetClientServer capability.
    std::array<uint8_t, 4096> capability_buffer{};
    if (!GetTokenInformation(token, TokenCapabilities, capability_buffer.data(),
                             static_cast<DWORD>(capability_buffer.size()), &returned) ||
        returned < sizeof(DWORD)) {
        return false;
    }
    const auto* capabilities =
        reinterpret_cast<const TOKEN_GROUPS*>(capability_buffer.data());
    return capabilities->GroupCount == 0;
}

bool read_exact(HANDLE input, uint8_t* buffer, DWORD bytes, ULONGLONG deadline) {
    DWORD offset = 0;
    while (offset < bytes) {
        DWORD available = 0;
        if (!PeekNamedPipe(input, nullptr, 0, nullptr, &available, nullptr))
            return false;
        if (available == 0) {
            if (GetTickCount64() >= deadline) return false;
            Sleep(5);
            continue;
        }
        const DWORD requested = (std::min)(bytes - offset, available);
        DWORD read = 0;
        if (!ReadFile(input, buffer + offset, requested, &read, nullptr) || read == 0)
            return false;
        offset += read;
    }
    return true;
}

// The protocol is deliberately one request per process. Do not silently
// ignore a second frame or trailing bytes after a valid request.
bool require_eof(HANDLE input, ULONGLONG deadline) {
    for (;;) {
        DWORD available = 0;
        if (!PeekNamedPipe(input, nullptr, 0, nullptr, &available, nullptr))
            return GetLastError() == ERROR_BROKEN_PIPE;
        if (available != 0) return false;
        if (GetTickCount64() >= deadline) return false;
        Sleep(5);
    }
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc == 2 && std::wcscmp(argv[1], L"--identity-probe") == 0) {
        return running_in_appcontainer_without_capabilities() ? 50 :
            static_cast<int>(kExitNotAppContainer);
    }
    // Fail closed when launched outside the intended restricted identity.
    if (!running_in_appcontainer_without_capabilities()) {
        std::cerr << "DENIED: broker requires a capability-free Windows AppContainer token.\n";
        return static_cast<int>(kExitNotAppContainer);
    }

    HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    if (input == nullptr || input == INVALID_HANDLE_VALUE ||
        GetFileType(input) != FILE_TYPE_PIPE) {
        std::cerr << "DENIED: private request pipe is unavailable.\n";
        return static_cast<int>(kExitIoFailure);
    }

    const ULONGLONG deadline = GetTickCount64() + kReadDeadlineMs;
    std::array<uint8_t, 12> header{};
    if (!read_exact(input, header.data(), static_cast<DWORD>(header.size()), deadline)) {
        std::cerr << "DENIED: incomplete request header.\n";
        return static_cast<int>(kExitBadInput);
    }

    const uint32_t frame_bytes =
        static_cast<uint32_t>(header[8]) |
        (static_cast<uint32_t>(header[9]) << 8) |
        (static_cast<uint32_t>(header[10]) << 16) |
        (static_cast<uint32_t>(header[11]) << 24);
    if (frame_bytes < 36 || frame_bytes > bm_ws_protocol::kMaxFrameBytes) {
        std::cerr << "DENIED: invalid request frame length.\n";
        return static_cast<int>(kExitBadInput);
    }

    std::vector<uint8_t> frame(frame_bytes);
    std::copy(header.begin(), header.end(), frame.begin());
    if (!read_exact(input, frame.data() + header.size(),
                    frame_bytes - static_cast<DWORD>(header.size()), deadline)) {
        std::cerr << "DENIED: truncated request frame.\n";
        return static_cast<int>(kExitBadInput);
    }

    // Parent must close its writer after the one frame. Any additional byte
    // is a second request/trailing data and causes rejection.
    if (!require_eof(input, deadline)) {
        std::cerr << "DENIED: trailing bytes, chained request, or missing EOF.\n";
        return static_cast<int>(kExitBadInput);
    }

    bm_ws_protocol::Request request{};
    const auto parsed = bm_ws_protocol::parse_request(frame.data(), frame.size(), &request);
    if (parsed != bm_ws_protocol::ParseStatus::Ok) {
        std::cerr << "DENIED: malformed request frame.\n";
        return static_cast<int>(kExitBadInput);
    }

    // Deliberately no filesystem dispatch. Native approval, AppContainer ACL
    // provisioning, and independent security review are not implemented yet.
    std::cerr << "DENIED: valid request; workspace operations are not enabled.\n";
    return static_cast<int>(kExitDeniedNotImplemented);
}
