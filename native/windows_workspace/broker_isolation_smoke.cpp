#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <userenv.h>

#include <array>
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#pragma comment(lib, "userenv.lib")

namespace {
constexpr DWORD kExpectedBrokerExit = 30;
constexpr DWORD kTimeoutMs = 10000;

struct Handle {
    HANDLE value = nullptr;
    Handle() = default;
    explicit Handle(HANDLE h) : value(h) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value(other.value) { other.value = nullptr; }
    Handle& operator=(Handle&& other) noexcept {
        if (this != &other) {
            if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value);
            value = other.value; other.value = nullptr;
        }
        return *this;
    }
    HANDLE get() const { return value; }
    HANDLE* put() { return &value; }
    HANDLE release() { HANDLE h = value; value = nullptr; return h; }
};

PSID get_or_create_profile() {
    PSID sid = nullptr;
    HRESULT hr = CreateAppContainerProfile(
        L"OpenAI.BabyMind.WorkspaceBroker",
        L"BabyMind Workspace Broker",
        L"Restricted identity for BabyMind's fail-closed workspace broker",
        nullptr, 0, &sid);
    if (SUCCEEDED(hr)) return sid;
    if (hr == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)) {
        if (SUCCEEDED(DeriveAppContainerSidFromAppContainerName(
                L"OpenAI.BabyMind.WorkspaceBroker", &sid))) return sid;
    }
    return nullptr;
}

bool make_request(std::array<uint8_t, 36>* frame) {
    // Version 1, LIST_DIRECTORY, 36-byte frame, 16-byte correlation ID,
    // empty relative path (workspace root), empty payload.
    const uint32_t words[] = {1, 1, 36, 0, 0, 0, 0, 0, 0};
    size_t offset = 0;
    for (uint32_t word : words) {
        (*frame)[offset++] = static_cast<uint8_t>(word & 0xff);
        (*frame)[offset++] = static_cast<uint8_t>((word >> 8) & 0xff);
        (*frame)[offset++] = static_cast<uint8_t>((word >> 16) & 0xff);
        (*frame)[offset++] = static_cast<uint8_t>((word >> 24) & 0xff);
    }
    return offset == frame->size();
}

std::wstring sibling_broker_path() {
    std::wstring path(32768, L'\0');
    DWORD length = GetModuleFileNameW(nullptr, path.data(),
                                      static_cast<DWORD>(path.size()));
    if (length == 0 || length >= path.size()) return {};
    path.resize(length);
    const size_t slash = path.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return {};
    path.resize(slash + 1);
    path += L"babymind_workspace_broker.exe";
    return path;
}
}

int wmain() {
    PSID appcontainer_sid = get_or_create_profile();
    if (!appcontainer_sid) {
        std::cerr << "FAIL: unable to create or derive dedicated AppContainer profile.\n";
        return 1;
    }

    SECURITY_ATTRIBUTES inheritable{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    Handle child_stdin_read, parent_stdin_write, parent_stdout_read, child_stdout_write;
    if (!CreatePipe(child_stdin_read.put(), parent_stdin_write.put(), &inheritable, 0) ||
        !CreatePipe(parent_stdout_read.put(), child_stdout_write.put(), &inheritable, 0) ||
        !SetHandleInformation(parent_stdin_write.get(), HANDLE_FLAG_INHERIT, 0) ||
        !SetHandleInformation(parent_stdout_read.get(), HANDLE_FLAG_INHERIT, 0)) {
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to create private one-launch pipes.\n";
        return 2;
    }

    SIZE_T attribute_bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 2, 0, &attribute_bytes);
    std::vector<uint8_t> attribute_storage(attribute_bytes);
    auto* attributes = reinterpret_cast<PPROC_THREAD_ATTRIBUTE_LIST>(
        attribute_storage.data());
    if (!InitializeProcThreadAttributeList(attributes, 2, 0, &attribute_bytes)) {
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to initialize process attributes.\n";
        return 3;
    }

    SECURITY_CAPABILITIES security{};
    security.AppContainerSid = appcontainer_sid;
    HANDLE inherited_handles[] = {child_stdin_read.get(), child_stdout_write.get()};
    const bool attributes_ok =
        UpdateProcThreadAttribute(attributes, 0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            &security, sizeof(security), nullptr, nullptr) &&
        UpdateProcThreadAttribute(attributes, 0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            inherited_handles, sizeof(inherited_handles), nullptr, nullptr);

    if (!attributes_ok) {
        DeleteProcThreadAttributeList(attributes);
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to apply AppContainer/handle restrictions.\n";
        return 4;
    }

    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = child_stdin_read.get();
    startup.StartupInfo.hStdOutput = child_stdout_write.get();
    startup.StartupInfo.hStdError = child_stdout_write.get();
    startup.lpAttributeList = attributes;

    const std::wstring broker_path = sibling_broker_path();
    std::vector<wchar_t> command(broker_path.begin(), broker_path.end());
    command.push_back(L'\0');
    PROCESS_INFORMATION process{};
    const BOOL created = !broker_path.empty() && CreateProcessW(
        broker_path.c_str(), command.data(), nullptr, nullptr, TRUE,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW,
        nullptr, nullptr, &startup.StartupInfo, &process);

    DeleteProcThreadAttributeList(attributes);
    FreeSid(appcontainer_sid);
    if (!created) {
        std::cerr << "FAIL: AppContainer broker process creation failed: "
                  << GetLastError() << "\n";
        return 5;
    }

    Handle process_handle(process.hProcess), thread_handle(process.hThread);
    child_stdin_read = Handle{};
    child_stdout_write = Handle{};

    Handle job(CreateJobObjectW(nullptr, nullptr));
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags =
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
        JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    limits.BasicLimitInformation.ActiveProcessLimit = 1;
    limits.ProcessMemoryLimit = 256ull * 1024ull * 1024ull;
    if (!job.get() ||
        !SetInformationJobObject(job.get(), JobObjectExtendedLimitInformation,
                                 &limits, sizeof(limits)) ||
        !AssignProcessToJobObject(job.get(), process_handle.get()) ||
        ResumeThread(thread_handle.get()) == static_cast<DWORD>(-1)) {
        TerminateProcess(process_handle.get(), 6);
        std::cerr << "FAIL: unable to apply process job limits.\n";
        return 6;
    }

    std::array<uint8_t, 36> request{};
    make_request(&request);
    DWORD written = 0;
    if (!WriteFile(parent_stdin_write.get(), request.data(),
                   static_cast<DWORD>(request.size()), &written, nullptr) ||
        written != request.size()) {
        TerminateJobObject(job.get(), 7);
        std::cerr << "FAIL: unable to send one bounded request.\n";
        return 7;
    }
    parent_stdin_write = Handle{};

    const DWORD wait = WaitForSingleObject(process_handle.get(), kTimeoutMs);
    if (wait != WAIT_OBJECT_0) {
        TerminateJobObject(job.get(), 8);
        std::cerr << "FAIL: broker timed out or wait failed.\n";
        return 8;
    }
    DWORD exit_code = 0;
    if (!GetExitCodeProcess(process_handle.get(), &exit_code)) {
        std::cerr << "FAIL: unable to read broker exit status.\n";
        return 9;
    }

    char output[1024]{};
    DWORD received = 0;
    while (ReadFile(parent_stdout_read.get(), output, sizeof(output), &received, nullptr)
           && received > 0) {
        std::cerr.write(output, received);
    }

    if (exit_code != kExpectedBrokerExit) {
        std::cerr << "FAIL: broker did not return the expected fail-closed status; code="
                  << exit_code << "\n";
        return 10;
    }
    std::cout << "PASS: launched in AppContainer; inherited only private IPC handles; "
                 "job limits applied; valid request denied without filesystem access.\n";
    return 0;
}
