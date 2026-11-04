#include "workspace_broker.h"
#include "broker_protocol.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <barrier>
#include <cwchar>
#include <iostream>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#define CHECK(expression) do { if (!(expression)) { std::wcerr << L"CHECK failed at line " << __LINE__ << L"\n"; return __LINE__; } } while (false)

static bm_ws_status validate(const wchar_t* value, int allow_empty = 0) {
    return bm_ws_validate_relative_path(value, std::wcslen(value), allow_empty);
}

int main() {
    CHECK(bm_ws_abi_version() == 1);
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


    {
        auto put32=[](std::vector<uint8_t>& b,uint32_t v){auto p=reinterpret_cast<const uint8_t*>(&v);b.insert(b.end(),p,p+4);};
        auto frame=[&](uint32_t op,const std::wstring& path,const std::vector<uint8_t>& data){
            std::vector<uint8_t>b;put32(b,1);put32(b,op);put32(b,0);for(uint8_t i=1;i<=16;++i)b.push_back(i);
            put32(b,static_cast<uint32_t>(path.size()));for(wchar_t c:path){uint16_t x=static_cast<uint16_t>(c);b.push_back(x&255);b.push_back(x>>8);}
            put32(b,static_cast<uint32_t>(data.size()));b.insert(b.end(),data.begin(),data.end());uint32_t n=static_cast<uint32_t>(b.size());std::memcpy(b.data()+8,&n,4);return b;
        };
        bm_ws_protocol::Request req{};
        auto f=frame(1,L"src",{});
        CHECK(bm_ws_protocol::parse_request(f.data(),f.size(),&req)==bm_ws_protocol::ParseStatus::Ok);
        CHECK(req.relative_path==L"src"&&req.payload.empty());
        auto root_frame=frame(1,L"",{});
        CHECK(bm_ws_protocol::parse_request(root_frame.data(),root_frame.size(),&req)==bm_ws_protocol::ParseStatus::Ok);
        CHECK(req.relative_path.empty());
        auto c=frame(3,L"notes/new.txt",{'o','k'});
        CHECK(bm_ws_protocol::parse_request(c.data(),c.size(),&req)==bm_ws_protocol::ParseStatus::Ok);
        CHECK(req.payload.size()==2&&req.payload[0]=='o');
        CHECK(bm_ws_protocol::parse_request(f.data(),f.size()-1,&req)==bm_ws_protocol::ParseStatus::Truncated);
        auto bad=frame(2,L"../secret",{});
        CHECK(bm_ws_protocol::parse_request(bad.data(),bad.size(),&req)==bm_ws_protocol::ParseStatus::InvalidPath);
        auto op=frame(99,L"file.txt",{});
        CHECK(bm_ws_protocol::parse_request(op.data(),op.size(),&req)==bm_ws_protocol::ParseStatus::UnsupportedOperation);
        auto p=frame(2,L"file.txt",{'x'});
        CHECK(bm_ws_protocol::parse_request(p.data(),p.size(),&req)==bm_ws_protocol::ParseStatus::InvalidLength);
        auto empty=frame(3,L"file.txt",{});
        CHECK(bm_ws_protocol::parse_request(empty.data(),empty.size(),&req)==bm_ws_protocol::ParseStatus::InvalidPayload);
        auto version=f;uint32_t v=2;std::memcpy(version.data(),&v,4);
        CHECK(bm_ws_protocol::parse_request(version.data(),version.size(),&req)==bm_ws_protocol::ParseStatus::UnsupportedVersion);
        auto trailing=f;trailing.push_back(0);
        CHECK(bm_ws_protocol::parse_request(trailing.data(),trailing.size(),&req)==bm_ws_protocol::ParseStatus::InvalidLength);
    }

    wchar_t temp[MAX_PATH]{};
    CHECK(GetTempPathW(MAX_PATH, temp) != 0);
    wchar_t candidate[MAX_PATH]{};
    CHECK(GetTempFileNameW(temp, L"bmw", 0, candidate) != 0);
    CHECK(DeleteFileW(candidate) != 0);
    CHECK(CreateDirectoryW(candidate, nullptr) != 0);
    std::wstring root_path(candidate);
    const std::wstring nested = root_path + L"\\nested";
    CHECK(CreateDirectoryW(nested.c_str(), nullptr) != 0);
    const std::wstring outside = root_path + L"_outside";
    CHECK(CreateDirectoryW(outside.c_str(), nullptr) != 0);
    const std::wstring outside_file = outside + L"\\secret.txt";
    HANDLE outside_handle = CreateFileW(outside_file.c_str(), GENERIC_WRITE, 0, nullptr,
        CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    CHECK(outside_handle != INVALID_HANDLE_VALUE);
    const char secret[] = "outside";
    DWORD secret_written = 0;
    CHECK(WriteFile(outside_handle, secret, sizeof(secret) - 1, &secret_written, nullptr) != 0);
    CHECK(secret_written == sizeof(secret) - 1);
    CHECK(CloseHandle(outside_handle) != 0);
    const std::wstring junction = root_path + L"\\escape";
    CHECK(CreateSymbolicLinkW(junction.c_str(), outside.c_str(),
        SYMBOLIC_LINK_FLAG_DIRECTORY | SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE) != 0);
    const std::wstring file_link = root_path + L"\\file_escape";
    CHECK(CreateSymbolicLinkW(file_link.c_str(), outside_file.c_str(),
        SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE) != 0);

    void* root = nullptr;
    CHECK(bm_ws_open_workspace_root(root_path.c_str(), &root) == BM_WS_OK);
    CHECK(root != nullptr);

    const uint8_t payload[] = {'B','a','b','y','M','i','n','d'};
    CHECK(bm_ws_create_new_text(root, L"nested/hello.txt", payload, sizeof(payload), 1024) == BM_WS_OK);

    bm_ws_directory_entry listed[8]{};
    size_t listed_count = 0;
    int listing_truncated = 0;
    CHECK(bm_ws_list_directory(root, L"", listed, 8, &listed_count, &listing_truncated) == BM_WS_OK);
    CHECK(listing_truncated == 0);
    bool saw_nested = false;
    bool saw_escape_reparse = false;
    for (size_t i = 0; i < listed_count; ++i) {
        if (std::wstring(listed[i].name) == L"nested" && listed[i].type == 1) saw_nested = true;
        if (std::wstring(listed[i].name) == L"escape" && listed[i].type == 2) saw_escape_reparse = true;
    }
    CHECK(saw_nested && saw_escape_reparse);
    CHECK(bm_ws_list_directory(root, L"nested", listed, 8, &listed_count, &listing_truncated) == BM_WS_OK);
    CHECK(listed_count == 1 && std::wstring(listed[0].name) == L"hello.txt" && listed[0].type == 0);
    CHECK(bm_ws_list_directory(root, L"nested", listed, 0, &listed_count, &listing_truncated) == BM_WS_INVALID_ARGUMENT);
    CHECK(bm_ws_list_directory(root, L"escape", listed, 8, &listed_count, &listing_truncated) == BM_WS_REPARSE_POINT);

    uint8_t output[1025]{};
    size_t bytes_read = 0;
    CHECK(bm_ws_read_text(root, L"nested/hello.txt", 1024, output, sizeof(output), &bytes_read) == BM_WS_OK);
    CHECK(bytes_read == sizeof(payload));
    CHECK(std::string(reinterpret_cast<char*>(output), bytes_read) == "BabyMind");
    CHECK(bm_ws_read_text(root, L"nested/hello.txt", 3, output, 4, &bytes_read) == BM_WS_TOO_LARGE);
    CHECK(bytes_read == 0);

    CHECK(bm_ws_create_new_text(root, L"nested/hello.txt", payload, sizeof(payload), 1024) == BM_WS_IO_ERROR);

    std::barrier start_race(3);
    bm_ws_status race_results[2] = {BM_WS_NOT_IMPLEMENTED, BM_WS_NOT_IMPLEMENTED};
    std::thread creator_one([&] {
        start_race.arrive_and_wait();
        race_results[0] = bm_ws_create_new_text(root, L"nested/race.txt", payload, sizeof(payload), 1024);
    });
    std::thread creator_two([&] {
        start_race.arrive_and_wait();
        race_results[1] = bm_ws_create_new_text(root, L"nested/race.txt", payload, sizeof(payload), 1024);
    });
    start_race.arrive_and_wait();
    creator_one.join();
    creator_two.join();
    const bool first_won = race_results[0] == BM_WS_OK && race_results[1] == BM_WS_IO_ERROR;
    const bool second_won = race_results[1] == BM_WS_OK && race_results[0] == BM_WS_IO_ERROR;
    CHECK(first_won || second_won);
    CHECK(bm_ws_read_text(root, L"../outside.txt", 1024, output, sizeof(output), &bytes_read) == BM_WS_INVALID_RELATIVE_PATH);
    CHECK(bm_ws_read_text(root, L"nested/absent.txt", 1024, output, sizeof(output), &bytes_read) == BM_WS_IO_ERROR);
    CHECK(bm_ws_read_text(root, L"nested/hello.txt", 1024, output, 4, &bytes_read) == BM_WS_BUFFER_TOO_SMALL);
    CHECK(bm_ws_read_text(root, L"escape/secret.txt", 1024, output, sizeof(output), &bytes_read) != BM_WS_OK);
    CHECK(bm_ws_create_new_text(root, L"escape/created.txt", payload, sizeof(payload), 1024) != BM_WS_OK);
    CHECK(bm_ws_read_text(root, L"file_escape", 1024, output, sizeof(output), &bytes_read) != BM_WS_OK);

    void* escaped_root = nullptr;
    CHECK(bm_ws_open_workspace_root(junction.c_str(), &escaped_root) != BM_WS_OK);
    CHECK(escaped_root == nullptr);

    bm_ws_close_workspace_root(root);
    CHECK(DeleteFileW((nested + L"\\hello.txt").c_str()) != 0);
    CHECK(DeleteFileW((nested + L"\\race.txt").c_str()) != 0);
    CHECK(RemoveDirectoryW(nested.c_str()) != 0);
    CHECK(DeleteFileW(outside_file.c_str()) != 0);
    CHECK(RemoveDirectoryW(outside.c_str()) != 0);
    CHECK(DeleteFileW(file_link.c_str()) != 0);
    CHECK(RemoveDirectoryW(junction.c_str()) != 0);
    CHECK(RemoveDirectoryW(root_path.c_str()) != 0);

    std::wcout << L"Handle-relative workspace tests passed. Python integration remains disabled.\n";
    return 0;
}
