/* macOS output only: callbacks consume PCM, never call the emulator or Python. */
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#include <AudioToolbox/AudioToolbox.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    AudioQueueRef queue;
    AudioQueueBufferRef buffers[3];
    pthread_mutex_t mutex;
    int16_t *samples;
    size_t capacity, read, count, block;
    uint64_t played;
} Playback;

static void fill_buffer(void *context, AudioQueueRef queue, AudioQueueBufferRef buffer) {
    Playback *p = context;
    int16_t *out = buffer->mAudioData;
    pthread_mutex_lock(&p->mutex);
    size_t count = p->count < p->block ? p->count : p->block;
    for (size_t i = 0; i < count; ++i) {
        size_t index = (p->read + i) % p->capacity;
        out[i * 2] = p->samples[index * 2];
        out[i * 2 + 1] = p->samples[index * 2 + 1];
    }
    p->read = (p->read + count) % p->capacity;
    p->count -= count;
    p->played += count;
    pthread_mutex_unlock(&p->mutex);
    memset(out + count * 2, 0, (p->block - count) * 4);
    buffer->mAudioDataByteSize = (UInt32)(p->block * 4);
    AudioQueueEnqueueBuffer(queue, buffer, 0, NULL);
}

void pokemon_output_close(Playback *p) {
    if (!p) return;
    if (p->queue) {
        AudioQueueStop(p->queue, true);
        AudioQueueDispose(p->queue, true);
    }
    pthread_mutex_destroy(&p->mutex);
    free(p->samples);
    free(p);
}

Playback *pokemon_output_open(unsigned rate) {
    if (rate < 8000 || rate > 384000) return NULL;
    Playback *p = calloc(1, sizeof(*p));
    if (!p) return NULL;
    pthread_mutex_init(&p->mutex, NULL);
    p->capacity = rate / 5;  /* Bounded backlog; never accumulate seconds of sound. */
    p->block = rate / 50;   /* 20 ms per output buffer. */
    p->samples = calloc(p->capacity * 2, sizeof(int16_t));
    if (!p->samples) { pokemon_output_close(p); return NULL; }
    AudioStreamBasicDescription format = {0};
    format.mSampleRate = rate;
    format.mFormatID = kAudioFormatLinearPCM;
    format.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked;
    format.mChannelsPerFrame = 2;
    format.mFramesPerPacket = 1;
    format.mBitsPerChannel = 16;
    format.mBytesPerFrame = format.mBytesPerPacket = 4;
    if (AudioQueueNewOutput(&format, fill_buffer, p, NULL, NULL, 0, &p->queue)) {
        pokemon_output_close(p); return NULL;
    }
    for (int i = 0; i < 3; ++i) {
        if (AudioQueueAllocateBuffer(p->queue, (UInt32)(p->block * 4), &p->buffers[i])) {
            pokemon_output_close(p); return NULL;
        }
        fill_buffer(p, p->queue, p->buffers[i]);
    }
    if (AudioQueueStart(p->queue, NULL)) { pokemon_output_close(p); return NULL; }
    return p;
}

void pokemon_output_push(Playback *p, const int16_t *samples, unsigned count) {
    if (!p || !count) return;
    pthread_mutex_lock(&p->mutex);
    if (count > p->capacity) {
        samples += (count - p->capacity) * 2;
        count = (unsigned)p->capacity;
    }
    if (p->count + count > p->capacity) {
        size_t drop = p->count + count - p->capacity;
        p->read = (p->read + drop) % p->capacity;
        p->count -= drop;
    }
    size_t end = (p->read + p->count) % p->capacity;
    for (unsigned i = 0; i < count; ++i) {
        size_t index = (end + i) % p->capacity;
        p->samples[index * 2] = samples[i * 2];
        p->samples[index * 2 + 1] = samples[i * 2 + 1];
    }
    p->count += count;
    pthread_mutex_unlock(&p->mutex);
}

void pokemon_output_volume(Playback *p, float volume) {
    if (p) AudioQueueSetParameter(p->queue, kAudioQueueParam_Volume, volume);
}

uint64_t pokemon_output_played(Playback *p) {
    pthread_mutex_lock(&p->mutex);
    uint64_t count = p->played;
    pthread_mutex_unlock(&p->mutex);
    return count;
}

void *pokemon_activity_begin(void) {
    id token = [NSProcessInfo.processInfo beginActivityWithOptions:NSActivityUserInitiatedAllowingIdleSystemSleep
                                                        reason:@"Running the Pokémon game session"];
    return (__bridge_retained void *)token;
}

void pokemon_activity_end(void *pointer) {
    if (!pointer) return;
    id token = (__bridge_transfer id)pointer;
    [NSProcessInfo.processInfo endActivity:token];
}

/* Tk may mark an IME/deferred event as lacking a physical byte. In an actual
 * keyboard callback the app's current NSEvent still carries the hardware code.
 * Never monitor other apps, install a hook or reuse an old currentEvent. */
int pokemon_current_keycode(int pressed) {
    if (![NSThread isMainThread] || !NSApp) return -1;
    NSEvent *event = NSApp.currentEvent;
    if (!event) return -1;
    NSTimeInterval age = NSProcessInfo.processInfo.systemUptime - event.timestamp;
    if (age < 0 || age > 0.25) return -1;
    NSEventType expected = pressed ? NSEventTypeKeyDown : NSEventTypeKeyUp;
    if (event.type != expected) return -1;
    return event.keyCode;
}

/* Preserve fractional trackpad points and macOS momentum. Read only the current
 * app event during a Tk wheel callback; no event tap or global monitoring. */
int pokemon_current_scroll(double *x, double *y, int *precise) {
    if (![NSThread isMainThread] || !NSApp) return 0;
    NSEvent *event = NSApp.currentEvent;
    if (!event || event.type != NSEventTypeScrollWheel) return 0;
    NSTimeInterval age = NSProcessInfo.processInfo.systemUptime - event.timestamp;
    if (age < 0 || age > 0.25) return 0;
    if (x) *x = event.scrollingDeltaX;
    if (y) *y = event.scrollingDeltaY;
    if (precise) *precise = event.hasPreciseScrollingDeltas;
    return 1;
}
