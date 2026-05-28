package com.wavedex

import android.content.Context
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext
import com.wavedex.ui.home.HomeScreen
import com.wavedex.ui.theme.WaveDexTheme
import com.wavedex.usb.RtlSdrUsb

class MainActivity : ComponentActivity() {

    private val usbViewModel: UsbConnectionViewModel by viewModels()

    private val usbManager: UsbManager by lazy(LazyThreadSafetyMode.NONE) {
        getSystemService(Context.USB_SERVICE) as UsbManager
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        usbViewModel.scan(usbManager)
        handleUsbLaunchIntent(intent, usbViewModel)

        setContent {
            val context = LocalContext.current

            DisposableEffect(usbViewModel, usbManager) {
                val permissionReceiver = RtlSdrUsb.registerUsbPermissionReceiver(context) { device, granted ->
                    usbViewModel.onPermissionResult(usbManager, device, granted)
                }
                val detachReceiver = RtlSdrUsb.registerDetachReceiver(context) { device ->
                    usbViewModel.onDeviceDetached(device)
                }
                onDispose {
                    RtlSdrUsb.unregisterReceiver(context, permissionReceiver)
                    RtlSdrUsb.unregisterReceiver(context, detachReceiver)
                }
            }

            WaveDexTheme {
                HomeScreen(viewModel = usbViewModel, usbManager = usbManager)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleUsbLaunchIntent(intent, usbViewModel)
    }

    private fun handleUsbLaunchIntent(intent: Intent?, viewModel: UsbConnectionViewModel) {
        if (intent?.action != UsbManager.ACTION_USB_DEVICE_ATTACHED) return
        val device = intent.usbDeviceExtra()
        viewModel.onUsbDeviceAttached(usbManager, device)
    }

    private fun Intent.usbDeviceExtra(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        } else {
            @Suppress("DEPRECATION")
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
        }
}
