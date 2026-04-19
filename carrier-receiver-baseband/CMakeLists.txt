cmake_minimum_required(VERSION 3.12)

# Pull in SDK (must be before project)
include(pico_sdk_import.cmake)

project(pico_examples C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

if (PICO_SDK_VERSION_STRING VERSION_LESS "1.3.0")
    message(FATAL_ERROR "Raspberry Pi Pico SDK version 1.3.0 (or later) required. Your version is ${PICO_SDK_VERSION_STRING}")
endif()

set(PICO_EXAMPLES_PATH ${PROJECT_SOURCE_DIR})

# Initialize the SDK
pico_sdk_init()

# 1. Define the executable
add_executable(carrier_receiver_baseband)

# 2. Add include directories
include_directories(../project_pico_libs)

# 3. Add all source files
target_sources(carrier_receiver_baseband PRIVATE 
        main.c
        ../project_pico_libs/packet_generation.c
        ../project_pico_libs/receiver_CC2500.c
        ../project_pico_libs/carrier_CC2500.c
        ../project_pico_libs/backscatter.c
)

# 4. Link standard and hardware libraries
target_link_libraries(carrier_receiver_baseband PRIVATE 
        pico_stdlib 
        hardware_pio 
        hardware_spi
)

# 5. Enable USB serial output, disable UART output
pico_enable_stdio_usb(carrier_receiver_baseband 1)
pico_enable_stdio_uart(carrier_receiver_baseband 0)

# 6. Generate .uf2, .bin, .hex files
pico_add_extra_outputs(carrier_receiver_baseband)

# 7. Compiler options
add_compile_options(-Wall
        -Wno-format          # int != int32_t as far as the compiler is concerned because gcc has int32_t as long int
        -Wno-unused-function # we have some for the docs that aren't called
        -Wno-maybe-uninitialized
)