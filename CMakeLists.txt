cmake_minimum_required(VERSION 3.13)

project(dyno_sv_test LANGUAGES CXX)

set(DYNO_SV_TEST_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

function(dyno_sv_test target)
    if(NOT EXISTS "${DYNO_SV_TEST_DIR}/designs/${target}/run.py")
        return()
    endif()
    foreach(repo ${ARGN})
        if(NOT EXISTS "${DYNO_SV_TEST_DIR}/designs/${target}/${repo}/.git")
            message(FATAL_ERROR "missing ${target}/${repo} checkout")
        endif()
    endforeach()
    add_test(
        NAME dyno_sv_test_${target}
        COMMAND python3 "${DYNO_SV_TEST_DIR}/driver.py" --targets ${target} --out "${CMAKE_BINARY_DIR}/bench_${target}.json"
    )
    set_tests_properties(dyno_sv_test_${target} PROPERTIES
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        TIMEOUT 3600
        RUN_SERIAL TRUE
    )
endfunction()

dyno_sv_test(picorv32 picorv32)
dyno_sv_test(cv32e40p cv32e40p)
dyno_sv_test(serv serv)
dyno_sv_test(soomrv SoomRV SoomRV/riscv-isa-sim)
set_tests_properties(dyno_sv_test_soomrv PROPERTIES TIMEOUT 7200)
