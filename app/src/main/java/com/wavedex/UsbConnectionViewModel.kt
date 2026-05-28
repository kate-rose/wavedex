package com.wavedex

import android.content.Context
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wavedex.native.NativeBridge
import com.wavedex.usb.RtlSdrUsb
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class ConnectionPhase {
    Idle,
    Searching,
    Found,
    PermissionDenied,
    Ready,
}

data class UsbUiState(
    val phase: ConnectionPhase = ConnectionPhase.Idle,
    val device: UsbDevice? = null,
    val statusDetail: String = "",
    val nativeStatus: String = "",
)

class UsbConnectionViewModel : ViewModel() {

    private val _state = MutableStateFlow(UsbUiState())
    val state: StateFlow<UsbUiState> = _state.asStateFlow()

    fun scan(usbManager: UsbManager) {
        viewModelScope.launch {
            _state.update { it.copy(phase = ConnectionPhase.Searching, statusDetail = "Scanning USB…") }
            delay(60)
            val device = RtlSdrUsb.findRtlDevice(usbManager)
            when {
                device == null -> {
                    NativeBridge.nativeClose()
                    _state.update {
                        UsbUiState(
                            phase = ConnectionPhase.Idle,
                            device = null,
                            statusDetail = "No RTL-SDR dongle detected. Plug one in via USB-OTG.",
                            nativeStatus = "",
                        )
                    }
                }

                RtlSdrUsb.hasPermission(usbManager, device) -> applyReady(device)

                else -> _state.update {
                    UsbUiState(
                        phase = ConnectionPhase.Found,
                        device = device,
                        statusDetail = "Found ${device.readableName()}. Tap Connect to grant USB access.",
                        nativeStatus = "",
                    )
                }
            }
        }
    }

    fun requestPermission(usbManager: UsbManager, context: Context) {
        val device = _state.value.device ?: RtlSdrUsb.findRtlDevice(usbManager) ?: return
        val pendingIntent = RtlSdrUsb.createUsbPermissionPendingIntent(context, requestCode = 0)
        RtlSdrUsb.requestPermission(usbManager, device, pendingIntent)
    }

    fun onPermissionResult(usbManager: UsbManager, device: UsbDevice?, granted: Boolean) {
        if (device == null || !RtlSdrUsb.isRtlSdrFamily(device)) return
        if (granted) {
            applyReady(device)
        } else {
            _state.update {
                UsbUiState(
                    phase = ConnectionPhase.PermissionDenied,
                    device = device,
                    statusDetail = "USB permission denied. Tap Connect to try again.",
                    nativeStatus = NativeBridge.nativeGetStatus(),
                )
            }
        }
    }

    fun onDeviceDetached(device: UsbDevice?) {
        if (device == null) return
        val current = _state.value.device ?: return
        if (device.deviceName != current.deviceName) return
        NativeBridge.nativeClose()
        _state.update {
            UsbUiState(
                phase = ConnectionPhase.Idle,
                device = null,
                statusDetail = "Dongle unplugged.",
                nativeStatus = "",
            )
        }
    }

    fun onUsbDeviceAttached(usbManager: UsbManager, device: UsbDevice?) {
        if (device != null && RtlSdrUsb.isRtlSdrFamily(device)) {
            scan(usbManager)
        }
    }

    private fun applyReady(device: UsbDevice) {
        NativeBridge.nativeInit()
        _state.update {
            UsbUiState(
                phase = ConnectionPhase.Ready,
                device = device,
                statusDetail = "USB access granted. IQ streaming hooks go next.",
                nativeStatus = NativeBridge.nativeGetStatus(),
            )
        }
    }

    private fun UsbDevice.readableName(): String =
        listOfNotNull(productName, deviceName, "RTL-SDR dongle").first()
}
