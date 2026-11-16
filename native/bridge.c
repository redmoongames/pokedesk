/* Small ctypes ABI around mGBA's mCore API. No RetroArch process is used.
 * Compiled against the vendored mGBA revision and its libretro build flags.
 */
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/core/serialize.h>
#include <mgba-util/vfs.h>
#include <mgba-util/audio-buffer.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    struct mCore *core;
    mColor pixels[240 * 160];
    unsigned char rgb[240 * 160 * 3];
    struct mAudioBuffer pcm;
} Pokemon;

static void quiet_log(struct mLogger *logger, int category, enum mLogLevel level,
                      const char *format, va_list args) {
    (void)logger; (void)category;
    if (level & (mLOG_FATAL | mLOG_ERROR)) {
        vfprintf(stderr, format, args);
        fputc('\n', stderr);
    }
}
static struct mLogger logger = { .log = quiet_log, .filter = NULL };

Pokemon *pokemon_open(const char *rom) {
    mLogSetDefaultLogger(&logger);
    Pokemon *p = calloc(1, sizeof(*p));
    if (!p) return NULL;
    p->core = mCoreFind(rom);
    if (!p->core) { free(p); return NULL; }
    if (!p->core->init(p->core)) { free(p); return NULL; }
    mCoreInitConfig(p->core, NULL);
    mCoreConfigSetDefaultIntValue(&p->core->config, "useBios", 0);
    mCoreConfigSetDefaultIntValue(&p->core->config, "skipBios", 1);
    mCoreConfigSetDefaultIntValue(&p->core->config, "volume", 0x100);
    mCoreConfigSetDefaultIntValue(&p->core->config, "mute", 0);
    mCoreLoadConfig(p->core);
    p->core->setVideoBuffer(p->core, p->pixels, 240);
    if (!mCoreLoadFile(p->core, rom)) {
        p->core->deinit(p->core); free(p); return NULL;
    }
    p->core->reset(p->core);
    p->core->setAudioBufferSize(p->core, 4096);
    mAudioBufferInit(&p->pcm, 65536, 2);
    return p;
}

void pokemon_close(Pokemon *p) {
    if (!p) return;
    mAudioBufferDeinit(&p->pcm);
    mCoreConfigDeinit(&p->core->config);
    p->core->deinit(p->core);
    free(p);
}

void pokemon_step(Pokemon *p, unsigned keys, unsigned frames) {
    p->core->setKeys(p->core, keys);
    for (unsigned i = 0; i < frames; ++i) {
        p->core->runFrame(p->core);
        int16_t samples[4096 * 2];
        size_t count;
        while ((count = mAudioBufferRead(p->core->getAudioBuffer(p->core), samples, 4096))) {
            if (mAudioBufferAvailable(&p->pcm) + count > 65536) mAudioBufferClear(&p->pcm);
            mAudioBufferWrite(&p->pcm, samples, count);
        }
    }
}

unsigned pokemon_audio_rate(Pokemon *p) { return p->core->audioSampleRate(p->core); }
unsigned pokemon_audio_read(Pokemon *p, int16_t *out, unsigned frames) {
    return (unsigned)mAudioBufferRead(&p->pcm, out, frames);
}
void pokemon_audio_clear(Pokemon *p) {
    mAudioBufferClear(&p->pcm);
    mAudioBufferClear(p->core->getAudioBuffer(p->core));
}

unsigned pokemon_read8(Pokemon *p, unsigned addr) {
    return p->core->rawRead8(p->core, addr, -1);
}
unsigned pokemon_read16(Pokemon *p, unsigned addr) {
    return p->core->rawRead16(p->core, addr, -1);
}
unsigned pokemon_read32(Pokemon *p, unsigned addr) {
    return p->core->rawRead32(p->core, addr, -1);
}

int pokemon_read_block(Pokemon *p, unsigned addr, unsigned char *out, unsigned size) {
    if (!p || (!out && size) || size > 1048576 || (size && addr > UINT32_MAX - (size - 1))) return 0;
    /* Same logical GBA reads as read8; no pointer arithmetic into host RAM. */
    for (unsigned i = 0; i < size; ++i) out[i] = p->core->rawRead8(p->core, addr + i, -1);
    return 1;
}

size_t pokemon_capture_state(Pokemon *p, void **out) {
    *out = NULL;
    struct VFile *vf = VFileMemChunk(NULL, 0);
    if (!vf) return 0;
    size_t size = 0;
    if (mCoreSaveStateNamed(p->core, vf, SAVESTATE_SAVEDATA | SAVESTATE_RTC | SAVESTATE_METADATA)) {
        ssize_t length = vf->size(vf);
        if (length > 0 && length <= 16 * 1024 * 1024) {
            void *buffer = malloc((size_t)length);
            if (buffer && vf->seek(vf, 0, SEEK_SET) == 0 && vf->read(vf, buffer, length) == length) {
                *out = buffer;
                size = (size_t)length;
            } else free(buffer);
        }
    }
    vf->close(vf);
    return size;
}

size_t pokemon_capture_save(Pokemon *p, void **out) {
    *out = NULL;
    size_t size = p->core->savedataClone(p->core, out);
    if (!*out || size != 131072) {
        free(*out);
        *out = NULL;
        return 0;
    }
    return size;
}

void pokemon_free_buffer(void *buffer) { free(buffer); }

int pokemon_load_state(Pokemon *p, const char *path) {
    struct VFile *vf = VFileOpen(path, O_RDONLY);
    if (!vf) return 0;
    int ok = mCoreLoadStateNamed(p->core, vf, SAVESTATE_SAVEDATA | SAVESTATE_RTC);
    vf->close(vf);
    mAudioBufferClear(&p->pcm);
    return ok;
}

/* Restore an emulator checkpoint, including its savedata, without disk I/O.
 * This follows the same mGBA restore path as pokemon_load_state. */
int pokemon_restore_state(Pokemon *p, const void *data, size_t size) {
    if (!p || !data || !size || size > 16 * 1024 * 1024) return 0;
    struct VFile *vf = VFileFromConstMemory(data, size);
    if (!vf) return 0;
    int ok = mCoreLoadStateNamed(p->core, vf, SAVESTATE_SAVEDATA | SAVESTATE_RTC);
    vf->close(vf);
    mAudioBufferClear(&p->pcm);
    return ok;
}

int pokemon_save_state(Pokemon *p, const char *path) {
    struct VFile *vf = VFileOpen(path, O_CREAT | O_TRUNC | O_RDWR);
    if (!vf) return 0;
    int ok = mCoreSaveStateNamed(p->core, vf, SAVESTATE_SAVEDATA | SAVESTATE_RTC | SAVESTATE_METADATA);
    vf->close(vf);
    return ok;
}

int pokemon_load_save(Pokemon *p, const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) return 0;
    if (fseek(fp, 0, SEEK_END)) { fclose(fp); return 0; }
    long size = ftell(fp);
    rewind(fp);
    if (size != 131072) { fclose(fp); return 0; }
    void *data = malloc((size_t) size);
    if (!data) { fclose(fp); return 0; }
    int ok = fread(data, 1, (size_t) size, fp) == (size_t) size;
    fclose(fp);
    if (ok) ok = p->core->savedataRestore(p->core, data, size, false);
    free(data);
    return ok;
}

int pokemon_save_save(Pokemon *p, const char *path) {
    void *data = NULL;
    size_t size = p->core->savedataClone(p->core, &data);
    if (!data || size != 131072) { free(data); return 0; }
    FILE *fp = fopen(path, "wb");
    if (!fp) { free(data); return 0; }
    int ok = fwrite(data, 1, size, fp) == size;
    if (fclose(fp)) ok = 0;
    free(data);
    return ok;
}

const unsigned char *pokemon_rgb(Pokemon *p) {
    for (unsigned i = 0; i < 240 * 160; ++i) {
        unsigned c = p->pixels[i];
        p->rgb[i * 3] = ((c >> 11) & 31) * 255 / 31;
        p->rgb[i * 3 + 1] = ((c >> 5) & 63) * 255 / 63;
        p->rgb[i * 3 + 2] = (c & 31) * 255 / 31;
    }
    return p->rgb;
}

unsigned pokemon_frame(Pokemon *p) { return p->core->frameCounter(p->core); }

#include "link.c"
