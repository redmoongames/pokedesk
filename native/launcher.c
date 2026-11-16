/* Portable macOS application entry point, using the bundled Python. */
#include <Python.h>
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, resolved)) return 1;
    /* executable -> MacOS -> Contents -> Pokemon.app -> project */
    for (int i = 0; i < 4; ++i) {
        char *slash = strrchr(resolved, '/');
        if (!slash) return 1;
        *slash = 0;
    }
    snprintf(python, sizeof(python), "%s/runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3", resolved);
    snprintf(script, sizeof(script), "%s/main.py", resolved);
    char **arguments = calloc((size_t)argc + 4, sizeof(char *));
    if (!arguments) return 1;
    arguments[0] = python;
    arguments[1] = "-I";
    arguments[2] = "-B";
    arguments[3] = script;
    for (int i = 1; i < argc; ++i) arguments[i + 3] = argv[i];
    int result = Py_BytesMain(argc + 3, arguments);
    free(arguments);
    return result;
}
