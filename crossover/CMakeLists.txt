# Standalone build of the crossover asset builder (no game dependencies):
#   cmake -S crossover -B build-crossover && cmake --build build-crossover
cmake_minimum_required(VERSION 3.16)
project(shre_convert CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(shre_convert cli/shre_convert.cpp lib/disc.cpp lib/harry.cpp lib/build.cpp)
if(WIN32)
  # The launcher is normally built from Game.sln; this lets CMake users build it too.
  add_executable(CrossoverLauncher WIN32 launcher/launcher.cpp lib/disc.cpp lib/harry.cpp lib/build.cpp)
  target_compile_definitions(CrossoverLauncher PRIVATE UNICODE _UNICODE NOMINMAX)
  target_link_libraries(CrossoverLauncher PRIVATE comctl32 comdlg32 shell32 ole32)
endif()
