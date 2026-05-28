package com.wavedex.usb

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import androidx.core.content.ContextCompat

/**
 * RTL2832U-class dongle discovery and USB permission helpers.
 *
 * Does not open [android.hardware.usb.UsbDeviceConnection]; that belongs with native bring-up.
 */
object RtlSdrUsb {

    const val REALTEK_VENDOR_ID = 0x0bda
    private val KNOWN_PRODUCT_IDS = intArrayOf(0x2832, 0x2838)

    fun usbPermissionAction(context: Context): String =
        "${context.packageName}.action.USB_PERMISSION"

    fun findRtlDevices(usbManager: UsbManager): List<UsbDevice> =
        usbManager.deviceList.values.filter(::isRtlSdrFamily)

    fun findRtlDevice(usbManager: UsbManager): UsbDevice? = findRtlDevices(usbManager).firstOrNull()

    fun isRtlSdrFamily(device: UsbDevice): Boolean =
        device.vendorId == REALTEK_VENDOR_ID && device.productId in KNOWN_PRODUCT_IDS

    fun hasPermission(usbManager: UsbManager, device: UsbDevice): Boolean =
        usbManager.hasPermission(device)

    fun requestPermission(usbManager: UsbManager, device: UsbDevice, pendingIntent: PendingIntent) {
        usbManager.requestPermission(device, pendingIntent)
    }

    fun createUsbPermissionPendingIntent(context: Context, requestCode: Int): PendingIntent {
        val intent = Intent(usbPermissionAction(context)).setPackage(context.packageName)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                PendingIntent.FLAG_IMMUTABLE
            } else {
                0
            }
        return PendingIntent.getBroadcast(context, requestCode, intent, flags)
    }

    fun registerUsbPermissionReceiver(
        context: Context,
        onResult: (device: UsbDevice?, granted: Boolean) -> Unit,
    ): BroadcastReceiver {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                if (intent?.action != usbPermissionAction(context)) return
                val device = intent.deviceExtra()
                val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                onResult(device, granted)
            }
        }
        ContextCompat.registerReceiver(
            context,
            receiver,
            IntentFilter(usbPermissionAction(context)),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        return receiver
    }

    fun registerDetachReceiver(
        context: Context,
        onDetached: (device: UsbDevice?) -> Unit,
    ): BroadcastReceiver {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context?, intent: Intent?) {
                if (intent?.action != UsbManager.ACTION_USB_DEVICE_DETACHED) return
                onDetached(intent.deviceExtra())
            }
        }
        ContextCompat.registerReceiver(
            context,
            receiver,
            IntentFilter(UsbManager.ACTION_USB_DEVICE_DETACHED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        return receiver
    }

    fun unregisterReceiver(context: Context, receiver: BroadcastReceiver) {
        runCatching { context.unregisterReceiver(receiver) }
    }

    private fun Intent.deviceExtra(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        } else {
            @Suppress("DEPRECATION")
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
        }
}
