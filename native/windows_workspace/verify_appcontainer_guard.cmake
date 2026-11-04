execute_process(
    COMMAND "${BROKER_EXE}"
    RESULT_VARIABLE broker_result
    OUTPUT_VARIABLE broker_stdout
    ERROR_VARIABLE broker_stderr
)
if(NOT "${broker_result}" STREQUAL "10")
    message(FATAL_ERROR
        "Broker must exit 10 outside AppContainer; got '${broker_result}'. stderr='${broker_stderr}'")
endif()
