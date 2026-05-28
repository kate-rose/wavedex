cmake_minimum_required(VERSION 3.22.1)

project("wavedex")

add_library(wavedex SHARED native_bridge.cpp)

find_library(log-lib log)

target_link_libraries(wavedex ${log-lib})
