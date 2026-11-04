#include "broker_protocol.h"
#include "workspace_broker.h"
#include <cstring>
namespace bm_ws_protocol {
namespace {
bool u32(const uint8_t* p,size_t n,size_t* o,uint32_t* v){if(*o>n||n-*o<4)return false;std::memcpy(v,p+*o,4);*o+=4;return true;}
bool utf16(const uint8_t* p,size_t n,std::wstring* out){out->clear();out->reserve(n);for(size_t i=0;i<n;++i){uint16_t x=0;std::memcpy(&x,p+i*2,2);if(!x)return false;if(x>=0xD800&&x<=0xDBFF){if(i+1>=n)return false;uint16_t y=0;std::memcpy(&y,p+(i+1)*2,2);if(y<0xDC00||y>0xDFFF)return false;out->push_back(static_cast<wchar_t>(x));out->push_back(static_cast<wchar_t>(y));++i;}else if(x>=0xDC00&&x<=0xDFFF)return false;else out->push_back(static_cast<wchar_t>(x));}return true;}
}
ParseStatus parse_request(const uint8_t* p,size_t n,Request* out){
 if(!p||!out)return ParseStatus::InvalidArgument;
 if(n<40)return ParseStatus::Truncated;if(n>kMaxFrameBytes)return ParseStatus::InvalidLength;
 size_t o=0;uint32_t v=0,op=0,total=0;
 if(!u32(p,n,&o,&v)||!u32(p,n,&o,&op)||!u32(p,n,&o,&total))return ParseStatus::Truncated;
 if(v!=kVersion)return ParseStatus::UnsupportedVersion;if(total!=n||total>kMaxFrameBytes)return ParseStatus::InvalidLength;
 if(op<1||op>3)return ParseStatus::UnsupportedOperation;
 Request r{};r.operation=static_cast<Operation>(op);std::memcpy(r.request_id.data(),p+o,16);o+=16;
 uint32_t chars=0;if(!u32(p,n,&o,&chars))return ParseStatus::Truncated;
 if(!chars||chars>kMaxPathChars)return ParseStatus::InvalidPath;
 size_t bytes=static_cast<size_t>(chars)*2;if(o>n||n-o<bytes)return ParseStatus::Truncated;
 if(!utf16(p+o,chars,&r.relative_path))return ParseStatus::InvalidPath;o+=bytes;
 if(bm_ws_validate_relative_path(r.relative_path.c_str(),r.relative_path.size(),r.operation==Operation::ListDirectory)!=BM_WS_OK)return ParseStatus::InvalidPath;
 uint32_t payload=0;if(!u32(p,n,&o,&payload))return ParseStatus::Truncated;
 if(payload>kMaxCreateBytes)return ParseStatus::InvalidPayload;
 if(o>n||n-o!=payload)return ParseStatus::InvalidLength;
 if(r.operation!=Operation::CreateNewText&&payload)return ParseStatus::InvalidPayload;
 if(r.operation==Operation::CreateNewText&&!payload)return ParseStatus::InvalidPayload;
 r.payload.assign(p+o,p+o+payload);*out=std::move(r);return ParseStatus::Ok;
}
}