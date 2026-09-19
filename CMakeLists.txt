cmake_minimum_required(VERSION 3.21)
project(CM14ResourceIsolation LANGUAGES CXX)

if(NOT WIN32 OR NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "This add-on requires Windows, MSVC and the x64 target.")
endif()

set(RESHADE_SDK_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/reshade-v6.5.1/include"
    CACHE PATH "Directory containing the compatible ReShade SDK headers")
if(NOT EXISTS "${RESHADE_SDK_INCLUDE_DIR}/reshade.hpp")
    message(FATAL_ERROR "Set RESHADE_SDK_INCLUDE_DIR to the compatible ReShade SDK include directory.")
endif()

option(BUILD_GENERIC_ISOLATION "Build an isolated generated package instead of fixed experiments" OFF)
option(BUILD_UNIVERSAL_ISOLATION "Build the fixed add-on that loads package JSON configuration" OFF)
if(BUILD_UNIVERSAL_ISOLATION AND BUILD_GENERIC_ISOLATION)
    message(FATAL_ERROR "Universal and generated-package build modes are mutually exclusive.")
endif()
if(BUILD_UNIVERSAL_ISOLATION)
    set(ISOLATION_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/dist/armor-isolation-runtime"
        CACHE PATH "Directory for the universal runtime")
    set(NLOHMANN_JSON_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/nlohmann-json-3.12.0/include"
        CACHE PATH "Directory containing nlohmann/json.hpp")
    if(NOT EXISTS "${NLOHMANN_JSON_INCLUDE_DIR}/nlohmann/json.hpp" OR
       NOT IS_ABSOLUTE "${ISOLATION_OUTPUT_DIRECTORY}")
        message(FATAL_ERROR "The JSON parser header and an absolute runtime output directory are required.")
    endif()
    enable_testing()
    add_library(UniversalResourceIsolation SHARED src/cm14_isolation_addon.cpp)
    add_executable(validate_runtime_profile tools/validate_runtime_profile.cpp)
    add_executable(test_universal_addon tests/test_universal_addon.cpp)
    add_executable(test_runtime_profile tests/test_runtime_profile.cpp)
    foreach(task_target UniversalResourceIsolation validate_runtime_profile test_universal_addon test_runtime_profile)
        target_compile_features(${task_target} PRIVATE cxx_std_17)
        target_compile_definitions(${task_target} PRIVATE UNIVERSAL_ISOLATION)
        target_include_directories(${task_target} PRIVATE include "${RESHADE_SDK_INCLUDE_DIR}" "${NLOHMANN_JSON_INCLUDE_DIR}")
        target_compile_options(${task_target} PRIVATE /W4 /permissive- /utf-8 /EHsc)
        set_target_properties(${task_target} PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    endforeach()
    set_target_properties(UniversalResourceIsolation PROPERTIES
        PREFIX "" OUTPUT_NAME "ArmorIsolation" SUFFIX ".addon64")
    foreach(task_target UniversalResourceIsolation validate_runtime_profile)
        set_target_properties(${task_target} PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY "${ISOLATION_OUTPUT_DIRECTORY}"
            RUNTIME_OUTPUT_DIRECTORY_RELEASE "${ISOLATION_OUTPUT_DIRECTORY}"
            RUNTIME_OUTPUT_DIRECTORY_DEBUG "${ISOLATION_OUTPUT_DIRECTORY}")
    endforeach()
    add_test(NAME universal_addon_transaction COMMAND test_universal_addon)
    add_test(NAME runtime_profile_validation COMMAND test_runtime_profile)
    return()
endif()
if(NOT BUILD_GENERIC_ISOLATION)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/include/cm14_resource_map.hpp")
        message(FATAL_ERROR "Build the CM14 isolated patch and generated resource map first.")
    endif()
endif()

if(BUILD_GENERIC_ISOLATION)
    set(ISOLATION_HEADER_DIRECTORY "" CACHE PATH "Directory containing generic_resource_map.hpp")
    set(ISOLATION_OUTPUT_DIRECTORY "" CACHE PATH "Directory for this package add-on")
    set(ISOLATION_PACKAGE_ID "" CACHE STRING "Unique lowercase package identifier")
    if(NOT ISOLATION_PACKAGE_ID MATCHES "^[a-z0-9][a-z0-9_-]*$")
        message(FATAL_ERROR "ISOLATION_PACKAGE_ID must contain lowercase ASCII letters, digits, underscores or hyphens.")
    endif()
    if(NOT IS_ABSOLUTE "${ISOLATION_HEADER_DIRECTORY}" OR
       NOT EXISTS "${ISOLATION_HEADER_DIRECTORY}/generic_resource_map.hpp" OR
       NOT IS_ABSOLUTE "${ISOLATION_OUTPUT_DIRECTORY}")
        message(FATAL_ERROR "Set absolute ISOLATION_HEADER_DIRECTORY and ISOLATION_OUTPUT_DIRECTORY package paths.")
    endif()
    enable_testing()
    add_library(GenericResourceIsolation SHARED src/cm14_isolation_addon.cpp)
    add_executable(probe_generic_resources tools/probe_cm14_resources.cpp)
    add_executable(test_generic_addon tests/test_generic_addon.cpp)
    foreach(task_target GenericResourceIsolation probe_generic_resources test_generic_addon)
        target_compile_features(${task_target} PRIVATE cxx_std_17)
        target_compile_definitions(${task_target} PRIVATE GENERIC_ISOLATION ISOLATION_PACKAGE_ID="${ISOLATION_PACKAGE_ID}")
        target_include_directories(${task_target} PRIVATE "${ISOLATION_HEADER_DIRECTORY}" include "${RESHADE_SDK_INCLUDE_DIR}")
        target_compile_options(${task_target} PRIVATE /W4 /permissive- /utf-8 /EHsc)
        set_target_properties(${task_target} PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    endforeach()
    set_target_properties(GenericResourceIsolation PROPERTIES
        PREFIX "" OUTPUT_NAME "ArmorIsolation_${ISOLATION_PACKAGE_ID}" SUFFIX ".addon64"
        RUNTIME_OUTPUT_DIRECTORY "${ISOLATION_OUTPUT_DIRECTORY}"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${ISOLATION_OUTPUT_DIRECTORY}"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${ISOLATION_OUTPUT_DIRECTORY}"
    )
    target_link_libraries(probe_generic_resources PRIVATE psapi)
    add_test(NAME generic_addon_transaction COMMAND test_generic_addon)
    return()
endif()

add_library(CM14ResourceIsolation SHARED src/cm14_isolation_addon.cpp)
target_compile_features(CM14ResourceIsolation PRIVATE cxx_std_17)
target_include_directories(CM14ResourceIsolation PRIVATE include "${RESHADE_SDK_INCLUDE_DIR}")
target_compile_options(CM14ResourceIsolation PRIVATE /W4 /permissive- /utf-8 /EHsc)
set_target_properties(CM14ResourceIsolation PROPERTIES
    PREFIX ""
    OUTPUT_NAME "CM14Isolation"
    SUFFIX ".addon64"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/dist/cm14-isolated/addon"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/dist/cm14-isolated/addon"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/dist/cm14-isolated/addon"
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
)

add_executable(probe_cm14_resources tools/probe_cm14_resources.cpp)
target_compile_features(probe_cm14_resources PRIVATE cxx_std_17)
target_include_directories(probe_cm14_resources PRIVATE include)
target_compile_options(probe_cm14_resources PRIVATE /W4 /permissive- /utf-8 /EHsc)
target_link_libraries(probe_cm14_resources PRIVATE psapi)
set_target_properties(probe_cm14_resources PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

enable_testing()
add_executable(test_cm14_addon tests/test_cm14_addon.cpp)
target_compile_features(test_cm14_addon PRIVATE cxx_std_17)
target_include_directories(test_cm14_addon PRIVATE include "${RESHADE_SDK_INCLUDE_DIR}")
target_compile_options(test_cm14_addon PRIVATE /W4 /permissive- /utf-8 /EHsc)
set_target_properties(test_cm14_addon PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
add_test(NAME cm14_addon_transaction COMMAND test_cm14_addon)

option(BUILD_B01_ISOLATION "Build the fixed B01 experiment alongside CM14" OFF)
if(BUILD_B01_ISOLATION)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/include/b01_resource_map.hpp")
        message(FATAL_ERROR "Build the B01 isolated patch and generated resource map first.")
    endif()
    add_library(B01ResourceIsolation SHARED src/cm14_isolation_addon.cpp)
    target_compile_features(B01ResourceIsolation PRIVATE cxx_std_17)
    target_compile_definitions(B01ResourceIsolation PRIVATE B01_ISOLATION)
    target_include_directories(B01ResourceIsolation PRIVATE include "${RESHADE_SDK_INCLUDE_DIR}")
    target_compile_options(B01ResourceIsolation PRIVATE /W4 /permissive- /utf-8 /EHsc)
    set_target_properties(B01ResourceIsolation PROPERTIES
        PREFIX ""
        OUTPUT_NAME "B01Isolation"
        SUFFIX ".addon64"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/dist/b01-isolated/addon"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/dist/b01-isolated/addon"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/dist/b01-isolated/addon"
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
    )
    add_executable(probe_b01_resources tools/probe_cm14_resources.cpp)
    target_compile_features(probe_b01_resources PRIVATE cxx_std_17)
    target_compile_definitions(probe_b01_resources PRIVATE B01_ISOLATION)
    target_include_directories(probe_b01_resources PRIVATE include)
    target_compile_options(probe_b01_resources PRIVATE /W4 /permissive- /utf-8 /EHsc)
    target_link_libraries(probe_b01_resources PRIVATE psapi)
    set_target_properties(probe_b01_resources PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

    add_executable(test_b01_addon tests/test_b01_addon.cpp)
    target_compile_features(test_b01_addon PRIVATE cxx_std_17)
    target_include_directories(test_b01_addon PRIVATE include "${RESHADE_SDK_INCLUDE_DIR}")
    target_compile_options(test_b01_addon PRIVATE /W4 /permissive- /utf-8 /EHsc)
    set_target_properties(test_b01_addon PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    add_test(NAME b01_addon_transaction COMMAND test_b01_addon)
endif()
