package com.wavedex.native

/**
 * JNI boundary for future rtl-sdr / libusb IQ streaming.
 *
 * IQ flow will likely claim a [android.hardware.usb.UsbDeviceConnection], obtain a bulk-IN
 * endpoint, then either read from Kotlin or pass a duplicated file descriptor into native code
 * via [nativeOpen].
 */
class NativeBridge private constructor() {
    companion object {
        init {
            System.loadLibrary("wavedex")
        }

        @JvmStatic
        external fun nativeInit(): Boolean

        @JvmStatic
        external fun nativeOpen(fd: Int): Boolean

        @JvmStatic
        external fun nativeClose()

        @JvmStatic
        external fun nativeGetStatus(): String
    }
}
