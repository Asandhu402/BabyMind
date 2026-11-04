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
constexpr DWORD kExpectedExit = 30; // valid frame parsed; operation deliberately denied
constexpr DWORD kExpectedTrailingDataExit = 20; // trailing request rejected
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
    HANDLE* address() { return &value; }
    void reset() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); value = nullptr; }
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

void put_u32(std::array<uint8_t, 36>& frame, size_t offset, uint32_t value) {
    frame[offset] = static_cast<uint8_t>(value);
    frame[offset + 1] = static_cast<uint8_t>(value >> 8);
    frame[offset + 2] = static_cast<uint8_t>(value >> 16);
    frame[offset + 3] = static_cast<uint8_t>(value >> 24);
}
}

int wmain(int argc, wchar_t** argv) {
    const bool inject_trailing_byte = argc == 2 && std::wstring(argv[1]) == L"--trailing-byte";
    if (argc > 2 || (argc == 2 && !inject_trailing_byte)) return 64;
    PSID appcontainer_sid = get_or_create_profile();
    if (!appcontainer_sid) {
        std::cerr << "FAIL: unable to create or derive dedicated AppContainer profile.\n";
        return 1;
    }

    SECURITY_ATTRIBUTES inheritable{sizeof(inheritable), nullptr, TRUE};
    Handle child_input, parent_output;
    if (!CreatePipe(child_input.address(), parent_output.address(), &inheritable, 0) ||
        !SetHandleInformation(parent_output.get(), HANDLE_FLAG_INHERIT, 0)) {
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to create private one-way IPC pipe.\n";
        return 2;
    }

    Handle child_stdout(CreateFileW(L"NUL", GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, &inheritable, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, nullptr));
    Handle child_stderr(CreateFileW(L"NUL", GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, &inheritable, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, nullptr));
    if (child_stdout.get() == INVALID_HANDLE_VALUE ||
        child_stderr.get() == INVALID_HANDLE_VALUE) {
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to create restricted output handles.\n";
        return 3;
    }

    SIZE_T attribute_bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 2, 0, &attribute_bytes);
    std::vector<uint8_t> attribute_storage(attribute_bytes);
    auto* attributes = reinterpret_cast<PPROC_THREAD_ATTRIBUTE_LIST>(
        attribute_storage.data());
    if (!InitializeProcThreadAttributeList(attributes, 2, 0, &attribute_bytes)) {
        FreeSid(appcontainer_sid);
        std::cerr << "FAIL: unable to initialize process attributes.\n";
        return 4;
    }

    SECURITY_CAPABILITIES security{};
    security.AppContainerSid = appcontainer_sid;
    const BOOL security_ok = UpdateProcThreadAttribute(
        attributes, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        &security, sizeof(security), nullptr, nullptr);

    std::array<HANDLE, 3> inherited_handles{
        child_input.get(), child_stdout.get(), child_stderr.get()};
    const BOOL handles_ok = security_ok && UpdateProcThreadAttribute(
        attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        inherited_handles.data(), sizeof(inherited_handles), nullptr, nullptr);

    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = child_input.get();
    startup.StartupInfo.hStdOutput = child_stdout.get();
    startup.StartupInfo.hStdError = child_stderr.get();
    startup.lpAttributeList = attributes;
    const std::wstring broker_path = sibling_broker_path();
    std::wstring command = L"\"" + broker_path + L"\"";
    PROCESS_INFORMATION process{};
    const BOOL created = handles_ok && !broker_path.empty() && CreateProcessW(
        broker_path.c_str(), command.data(), nullptr, nullptr, TRUE,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW,
        nullptr, nullptr, &startup.StartupInfo, &process);

    DeleteProcThreadAttributeList(attributes);
    FreeSid(appcontainer_sid);
    if (!created) {
        std::cerr << "FAIL: restricted AppContainer broker creation failed: "
                  << GetLastError() << "\n";
        return 5;
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
        TerminateProcess(process_handle.get(), 6);
        std::cerr << "FAIL: unable to apply process job limits.\n";
        return 6;
    }

    // A single empty-root LIST_DIRECTORY frame. The broker parses it and must
    // still deny the operation because native approval/ACL dispatch is absent.
    std::array<uint8_t, 36> frame{};
    put_u32(frame, 0, 1);   // protocol version
    put_u32(frame, 4, 1);   // LIST_DIRECTORY
    put_u32(frame, 8, static_cast<uint32_t>(frame.size()));
    put_u32(frame, 28, 0);  // empty relative path: workspace root
    put_u32(frame, 32, 0);  // no payload
    DWORD written = 0;
    const BOOL sent = WriteFile(parent_output.get(), frame.data(),
                                static_cast<DWORD>(frame.size()), &written, nullptr);
    DWORD trailing_written = 0;
    const uint8_t trailing_byte = 0xA5;
    const BOOL trailing_sent = !inject_trailing_byte || WriteFile(
        parent_output.get(), &trailing_byte, 1, &trailing_written, nullptr);
    parent_output.reset(); // EOF after the request (or deliberate trailing byte)
    child_input.reset();   // parent retains no child-side read handle

    if (!sent || written != frame.size() || !trailing_sent ||
        (inject_trailing_byte && trailing_written != 1)) {
        TerminateJobObject(job.get(), 7);
        std::cerr << "FAIL: unable to send bounded IPC request.\n";
        return 7;
    }

    const DWORD wait = WaitForSingleObject(process_handle.get(), kTimeoutMs);
    if (wait != WAIT_OBJECT_0) {
        TerminateJobObject(job.get(), 8);
        std::cerr << "FAIL: broker IPC request timed out or wait failed.\n";
        return 8;
    }

    DWORD exit_code = 0;
    if (!GetExitCodeProcess(process_handle.get(), &exit_code)) {
        std::cerr << "FAIL: unable to read broker exit status.\n";
        return 9;
    }
    const DWORD expected_exit = inject_trailing_byte ?
        kExpectedTrailingDataExit : kExpectedExit;
    if (exit_code != expected_exit) {
        std::cerr << "FAIL: broker did not validate-and-deny the IPC frame; code="
                  << exit_code << "\n";
        return 10;
    }
    if (inject_trailing_byte) {
        std::cout << "PASS: broker rejects trailing IPC data and chained requests.\n";
    } else {
        std::cout << "PASS: capability-free AppContainer; explicit three-handle "
                     "inheritance allowlist; bounded one-request IPC parsed; operation denied.\n";
    }
    return 0;
}
