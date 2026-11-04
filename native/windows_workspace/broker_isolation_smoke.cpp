#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <userenv.h>

#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#pragma comment(lib, "userenv.lib")

namespace {
constexpr DWORD kExpectedExit = 50;
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
            value = other.value;
            other.value = nullptr;
        }
        return *this;
    }
    HANDLE get() const { return value; }
};

PSID get_or_create_profile() {
    PSID sid = nullptr;
    HRESULT hr = CreateAppContainerProfile(
        L"OpenAI.BabyMind.WorkspaceBroker",
        L"BabyMind Workspace Broker",
        L"Restricted identity for BabyMind's workspace broker",
        nullptr, 0, &sid);
    if (SUCCEEDED(hr)) return sid;
    if (hr == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS) &&
        SUCCEEDED(DeriveAppContainerSidFromAppContainerName(
            L"OpenAI.BabyMind.WorkspaceBroker", &sid))) return sid;
    return nullptr;
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

    SIZE_T attribute_bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attribute_bytes);
    std::vector<uint8_t> attribute_storage(attribute_bytes);
    auto* attributes = reinterpret_cast<PPROC_THREAD_ATTRIBUTE_LIST>(
        attribute_storage.data());
    if (!InitializeProcThreadAttributeList(attributes, 1, 0, &attribute_bytes)) {
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to initialize process attributes.\n";
        return 2;
    }

    SECURITY_CAPABILITIES security{};
    security.AppContainerSid = appcontainer_sid;
    const BOOL attributes_ok = UpdateProcThreadAttribute(
        attributes, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        &security, sizeof(security), nullptr, nullptr);
    if (!attributes_ok) {
        DeleteProcThreadAttributeList(attributes);
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to apply capability-free AppContainer token.\n";
        return 3;
    }

    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.lpAttributeList = attributes;
    const std::wstring broker_path = sibling_broker_path();
    std::wstring command = L"\"" + broker_path + L"\" --identity-probe";
    PROCESS_INFORMATION process{};
    const BOOL created = !broker_path.empty() && CreateProcessW(
        broker_path.c_str(), command.data(), nullptr, nullptr, FALSE,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW,
        nullptr, nullptr, &startup.StartupInfo, &process);

    DeleteProcThreadAttributeList(attributes);
    FreeSid(appcontainer_sid);
    if (!created) {
        std::cerr << "FAIL: AppContainer broker creation failed: "
                  << GetLastError() << "\n";
        return 4;
    }

    Handle process_handle(process.hProcess), thread_handle(process.hThread);
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
        TerminateProcess(process_handle.get(), 5);
        std::cerr << "FAIL: unable to apply process job limits.\n";
        return 5;
    }

    const DWORD wait = WaitForSingleObject(process_handle.get(), kTimeoutMs);
    if (wait != WAIT_OBJECT_0) {
        TerminateJobObject(job.get(), 6);
        std::cerr << "FAIL: AppContainer identity probe timed out or wait failed.\n";
        return 6;
    }

    DWORD exit_code = 0;
    if (!GetExitCodeProcess(process_handle.get(), &exit_code)) {
        std::cerr << "FAIL: unable to read broker exit status.\n";
        return 7;
    }
    if (exit_code != kExpectedExit) {
        std::cerr << "FAIL: broker rejected its AppContainer identity; code="
                  << exit_code << "\n";
        return 8;
    }
    std::cout << "PASS: capability-free AppContainer token verified; no inherited "
                 "handles or capabilities; process job limits applied.\n";
    return 0;
}
