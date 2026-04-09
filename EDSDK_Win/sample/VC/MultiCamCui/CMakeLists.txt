# CMakeList.txt : MultiCamCui
cmake_minimum_required (VERSION 3.10.2)
# for Mac(apple silicon) 3.19.2 is needed

project(MultiCamCui CXX)
# cmake_policy(SET CMP0076 NEW)
set(SRC_DIR ${PROJECT_SOURCE_DIR}/src)
set(INC_DIR ${PROJECT_SOURCE_DIR}/include)

if(MSVC)
    string(REPLACE "/W3" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /W4 /EHsc")
    set(CMAKE_CXX_FLAGS_DEBUG   "${CMAKE_CXX_FLAGS_DEBUG}   /DBUILD_TYPE=\\\"Debug\\\"")
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} /DBUILD_TYPE=\\\"Release\\\"")
elseif(APPLE)
    add_compile_options(-D __MACOS__)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -std=c++11 -fpermissive -pthread")
    set(CMAKE_CXX_FLAGS_DEBUG   "${CMAKE_CXX_FLAGS_DEBUG}   -DBUILD_TYPE=\\\"Debug\\\"")
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -DBUILD_TYPE=\\\"Release\\\"")
else()
    add_compile_options(-D TARGET_OS_LINUX)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -std=c++17 -fpermissive -pthread")
endif()

add_executable (MultiCamCui
    ${SRC_DIR}/CameraEvent.cpp
    ${SRC_DIR}/FileControl.cpp
    ${SRC_DIR}/MultiCamCui.cpp
    ${SRC_DIR}/PreSetting.cpp
    ${SRC_DIR}/CameraModel.cpp
    ${SRC_DIR}/utility.cpp
)

set_target_properties(MultiCamCui PROPERTIES
	CXX_STANDARD 17
    CXX_STANDARD_REQUIRED YES
    CXX_EXTENSIONS NO
    BUILD_RPATH "$ORIGIN"
    INSTALL_RPATH "$ORIGIN"
)

target_include_directories(MultiCamCui
  PUBLIC ${SRC_DIR}
  PUBLIC ${INC_DIR}
  PUBLIC ${INC_DIR}/Camera
  PUBLIC ${INC_DIR}/Class
  PUBLIC ${INC_DIR}/Command
  PUBLIC ${PROJECT_SOURCE_DIR}/../../../EDSDK/Header
  )

if(MSVC)
    set(EDSDK_LDIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../EDSDK_64)
    target_link_libraries(MultiCamCui
        PRIVATE
            ${EDSDK_LDIR}/Library/EDSDK.lib
    )
elseif(UNIX AND NOT APPLE)
    set(EDSDK_LDIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../EDSDK/Library/ARM64)
    target_link_libraries(MultiCamCui
        PRIVATE
            ${EDSDK_LDIR}/libEDSDK.so
    )
elseif(APPLE)
    set(EDSDK_LDIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../EDSDK)
    target_link_libraries(MultiCamCui
        PRIVATE
            ${EDSDK_LDIR}/Library/Mac/EDSDK.framework/EDSDK
    )
endif()

if(MSVC)
    add_custom_command(TARGET MultiCamCui PRE_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${EDSDK_LDIR}/Dll $<TARGET_FILE_DIR:MultiCamCui>
        COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:MultiCamCui>/resources
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${PROJECT_SOURCE_DIR}/resources $<TARGET_FILE_DIR:MultiCamCui>/resources
    )
elseif(UNIX AND NOT APPLE)
    add_custom_command(TARGET MultiCamCui PRE_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${EDSDK_LDIR} $<TARGET_FILE_DIR:MultiCamCui>
        COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:MultiCamCui>/resources
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${PROJECT_SOURCE_DIR}/resources $<TARGET_FILE_DIR:MultiCamCui>/resources
    )
elseif(APPLE)
    execute_process(
        COMMAND ${CMAKE_COMMAND} -E tar xzf ${EDSDK_LDIR}/Library/Mac/EDSDK.Framework.zip WORKING_DIRECTORY ${EDSDK_LDIR}/Library/Mac
    )
    add_custom_command(TARGET MultiCamCui PRE_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:MultiCamCui>/../Frameworks
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${EDSDK_LDIR}/Library/Mac $<TARGET_FILE_DIR:MultiCamCui>/../Frameworks
        COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:MultiCamCui>/resources
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${PROJECT_SOURCE_DIR}/resources $<TARGET_FILE_DIR:MultiCamCui>/resources
    )
endif()
