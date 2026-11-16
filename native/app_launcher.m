/* Finder launcher for the self-contained application. No shell or system Python.
 * Python's libraries and the entry point are resolved inside this bundle, even
 * when Finder launches a quarantined/translocated copy or the path has spaces.
 */
#import <AppKit/AppKit.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

static BOOL hexIdentifier(id value, NSUInteger length) {
    if (![value isKindOfClass:[NSString class]] || [value length] != length) return NO;
    return [value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet]].location == NSNotFound;
}

static NSDictionary *jsonAt(NSString *path) {
    NSData *data = [NSData dataWithContentsOfFile:path];
    id value = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    return [value isKindOfClass:[NSDictionary class]] ? value : nil;
}

static void error(NSString *message) {
    [NSApplication sharedApplication];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"PokéDesk could not start";
    alert.informativeText = message;
    [alert addButtonWithTitle:@"Close"];
    [alert runModal];
}

int main(int argc, char **argv) {
    @autoreleasepool {
        // Finder and terminal launches use the same private runtime/scripts.
        // In particular, Tcl must not pick up another Python's library path.
        unsetenv("PYTHONHOME");
        unsetenv("PYTHONPATH");
        unsetenv("TCL_LIBRARY");
        unsetenv("TK_LIBRARY");
        unsetenv("__PYVENV_LAUNCHER__");
        NSString *resources = [[NSBundle mainBundle] resourcePath];
        NSString *installation = [resources stringByAppendingPathComponent:@"installation"];
        NSString *script = [installation stringByAppendingPathComponent:@"desktop_main.py"];
        NSString *profile = getenv("POKEDESK_LIBRARY") ? [NSString stringWithUTF8String:getenv("POKEDESK_LIBRARY")] :
            [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/PokeDesk"];
        NSDictionary *build = jsonAt([installation stringByAppendingPathComponent:@"desktop-build.json"]);
        NSDictionary *receipt = jsonAt([profile stringByAppendingPathComponent:@"desktop-installation.json"]);
        NSString *pinned = nil;
        if (!getenv("POKEDESK_REPAIR") && [receipt[@"build_id"] isEqual:build[@"build_id"]] &&
            hexIdentifier(receipt[@"release_id"], 64) && hexIdentifier(receipt[@"slot"], 32)) {
            NSString *relative = [NSString stringWithFormat:@"Sessions/installations/desktop-%@/%@", receipt[@"slot"], receipt[@"release_id"]];
            NSString *candidate = [profile stringByAppendingPathComponent:relative];
            NSFileManager *manager = [NSFileManager defaultManager];
            if ([manager fileExistsAtPath:[candidate stringByAppendingPathComponent:@"installation-version.json"]] &&
                [manager fileExistsAtPath:[candidate stringByAppendingPathComponent:@"runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3"]] &&
                [manager fileExistsAtPath:[candidate stringByAppendingPathComponent:@"runtime/python/cpython-3.12.16-macos-aarch64-none/lib/libpython3.12.dylib"]]) pinned = candidate;
        }
        NSString *runtime = [(pinned ?: installation) stringByAppendingPathComponent:@"runtime/python/cpython-3.12.16-macos-aarch64-none"];
        NSString *library = [runtime stringByAppendingPathComponent:@"lib/libpython3.12.dylib"];
        NSString *python = [runtime stringByAppendingPathComponent:@"bin/python3"];
        setenv("POKEDESK_LAUNCHER", [[[NSBundle mainBundle] executablePath] fileSystemRepresentation], 1);
        setenv("POKEDESK_LIBRARY", [profile fileSystemRepresentation], 1);
        setenv("POKEDESK_DESKTOP", "1", 1);
        if (pinned) {
            setenv("POKEDESK_PINNED_ROOT", [pinned fileSystemRepresentation], 1);
            setenv("POKEDESK_RELEASE_ID", [receipt[@"release_id"] UTF8String], 1);
            setenv("POKEDESK_INSTALLATION_ORIGIN", [pinned fileSystemRepresentation], 1);
        } else {
            unsetenv("POKEDESK_PINNED_ROOT");
            unsetenv("POKEDESK_RELEASE_ID");
            unsetenv("POKEDESK_INSTALLATION_ORIGIN");
        }
        NSString *logs = [profile stringByAppendingPathComponent:@"logs"];
        [[NSFileManager defaultManager] createDirectoryAtPath:logs withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *log = [logs stringByAppendingPathComponent:@"launch.log"];
        NSDictionary *attributes = [[NSFileManager defaultManager] attributesOfItemAtPath:log error:nil];
        if ([attributes fileSize] > 1024*1024) {
            NSString *previous = [log stringByAppendingString:@".previous"];
            [[NSFileManager defaultManager] removeItemAtPath:previous error:nil];
            [[NSFileManager defaultManager] moveItemAtPath:log toPath:previous error:nil];
        }
        int fd = open([log fileSystemRepresentation], O_WRONLY|O_APPEND|O_CREAT, 0600);
        if (fd >= 0) { dup2(fd, STDOUT_FILENO); dup2(fd, STDERR_FILENO); close(fd); }
        void *handle = dlopen([library fileSystemRepresentation], RTLD_NOW|RTLD_GLOBAL);
        if (!handle && pinned) {
            // A damaged cache must not prevent the bundled repair UI opening.
            unsetenv("POKEDESK_PINNED_ROOT");
            unsetenv("POKEDESK_RELEASE_ID");
            unsetenv("POKEDESK_INSTALLATION_ORIGIN");
            setenv("POKEDESK_REPAIR", "1", 1);
            runtime = [installation stringByAppendingPathComponent:@"runtime/python/cpython-3.12.16-macos-aarch64-none"];
            library = [runtime stringByAppendingPathComponent:@"lib/libpython3.12.dylib"];
            python = [runtime stringByAppendingPathComponent:@"bin/python3"];
            handle = dlopen([library fileSystemRepresentation], RTLD_NOW|RTLD_GLOBAL);
        }
        int (*python_main)(int, char **) = handle ? dlsym(handle, "Py_BytesMain") : NULL;
        if (!python_main) {
            error(@"The bundled Python runtime is missing or damaged. Download a fresh copy of PokéDesk.");
            return 1;
        }
        char **arguments = calloc((size_t)argc + 4, sizeof(char *));
        arguments[0] = (char *)[python fileSystemRepresentation];
        arguments[1] = "-I";
        arguments[2] = "-B";
        arguments[3] = (char *)[script fileSystemRepresentation];
        for (int i = 1; i < argc; ++i) arguments[i+3] = argv[i];
        int result = python_main(argc + 3, arguments);
        free(arguments);
        if (result) error([NSString stringWithFormat:@"See %@ for details. Your saved games have not been removed.", log]);
        return result;
    }
}
