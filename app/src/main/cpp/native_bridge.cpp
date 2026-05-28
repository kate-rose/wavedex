#include <jni.h>
#include <android/log.h>

#define LOG_TAG "WaveDexNative"

namespace {

bool gInited = false;
bool gOpen = false;
int gLastFd = -1;

} // namespace

extern "C" JNIEXPORT jboolean JNICALL
Java_com_wavedex_native_NativeBridge_nativeInit(JNIEnv * /*env*/, jclass /*clazz*/) {
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "nativeInit");
    gInited = true;
    gOpen = false;
    gLastFd = -1;
    return JNI_TRUE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_wavedex_native_NativeBridge_nativeOpen(JNIEnv *env, jclass /*clazz*/, jint fd) {
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "nativeOpen fd=%d", fd);
    if (fd < 0) {
        return JNI_FALSE;
    }
    gOpen = true;
    gLastFd = fd;
    (void)env;
    return JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_wavedex_native_NativeBridge_nativeClose(JNIEnv * /*env*/, jclass /*clazz*/) {
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "nativeClose");
    gOpen = false;
    gLastFd = -1;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_wavedex_native_NativeBridge_nativeGetStatus(JNIEnv *env, jclass /*clazz*/) {
    const char *msg;
    if (!gInited) {
        msg = "native: idle";
    } else if (gOpen) {
        msg = "native: open (stub)";
    } else {
        msg = "native: initialized (stub)";
    }
    return env->NewStringUTF(msg);
}
