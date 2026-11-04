#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
namespace bm_ws_protocol {
constexpr uint32_t kVersion=1;
constexpr size_t kMaxFrameBytes=1024*1024, kMaxPathChars=500, kMaxCreateBytes=32*1024;
enum class Operation:uint32_t { ListDirectory=1, ReadText=2, CreateNewText=3 };
enum class ParseStatus { Ok, InvalidArgument, Truncated, InvalidLength, UnsupportedVersion, UnsupportedOperation, InvalidPath, InvalidPayload };
struct Request { Operation operation{}; std::array<uint8_t,16> request_id{}; std::wstring relative_path; std::vector<uint8_t> payload; };
ParseStatus parse_request(const uint8_t* frame,size_t frame_bytes,Request* output);
}