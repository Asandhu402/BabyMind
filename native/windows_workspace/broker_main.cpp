#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "broker_protocol.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <vector>

namespace {
constexpr DWORD kExitNotAppContainer = 10;
constexpr DWORD kExitBadInput = 20;
constexpr DWORD kExitDeniedNotImplemented = 30;
constexpr DWORD kExitIoFailure = 40;

bool running_in_appcontainer() {
    BOOL is_appcontainer = FALSE;
    DWORD returned = 0;
    if (!GetTokenInformation(GetCurrentProcessToken(), TokenIsAppContainer,
                             &is_appcontainer, sizeof(is_appcontainer), &returned)) {
        return false;
    }
    return is_appcontainer == TRUE;
}

bool read_exact(HANDLE input, uint8_t* buffer, DWORD bytes) {
    DWORD offset = 0;
    while (offset < bytes) {
        DWORD read = 0;
        if (!ReadFile(input, buffer + offset, bytes - offset, &read, nullptr) || read == 0)
            return false;
        offset += read;
    }
    return true;
}
}

int wmain() {
    // Fail closed when launched outside the intended restricted identity.
    if (!running_in_appcontainer()) {
        std::cerr << "DENIED: broker requires a Windows AppContainer token.\n";
        return static_cast<int>(kExitNotAppContainer);
    }

    HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    if (input == nullptr || input == INVALID_HANDLE_VALUE) {
        std::cerr << "DENIED: private request pipe is unavailable.\n";
        return static_cast<int>(kExitIoFailure);
    }

    std::array<uint8_t, 12> header{};
    if (!read_exact(input, header.data(), static_cast<DWORD>(header.size()))) {
        std::cerr << "DENIED: incomplete request header.\n";
        return static_cast<int>(kExitBadInput);
    }

    uint32_t frame_bytes = 0;
    frame_bytes = static_cast<uint32_t>(header[8]) |
                  (static_cast<uint32_t>(header[9]) << 8) |
                  (static_cast<uint32_t>(header[10]) << 16) |
                  (static_cast<uint32_t>(header[11]) << 24);
    if (frame_bytes < header.size() || frame_bytes > bm_ws_protocol::kMaxFrameBytes) {
        std::cerr << "DENIED: invalid request frame length.\n";
        return static_cast<int>(kExitBadInput);
    }

    std::vector<uint8_t> frame(frame_bytes);
    std::copy(header.begin(), header.end(), frame.begin());
    if (!read_exact(input, frame.data() + header.size(),
                    frame_bytes - static_cast<DWORD>(header.size()))) {
        std::cerr << "DENIED: truncated request frame.\n";
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
