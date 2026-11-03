cmake_minimum_required(VERSION 3.20)
project(BabyMindWindowsWorkspace LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "BabyMind's native workspace broker is Windows-only.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(babymind_workspace STATIC workspace_broker.cpp)
target_include_directories(babymind_workspace PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(babymind_workspace PUBLIC ntdll)
target_compile_definitions(babymind_workspace PRIVATE BABYMIND_WORKSPACE_BUILD)
if(MSVC)
    target_compile_options(babymind_workspace PRIVATE /W4 /WX /permissive- /sdl)
endif()

add_executable(workspace_broker_tests tests.cpp)
target_link_libraries(workspace_broker_tests PRIVATE babymind_workspace)
if(MSVC)
    target_compile_options(workspace_broker_tests PRIVATE /W4 /WX /permissive- /sdl)
endif()

enable_testing()
add_test(NAME workspace_broker_tests COMMAND workspace_broker_tests)
