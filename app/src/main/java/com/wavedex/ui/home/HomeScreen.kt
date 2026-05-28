package com.wavedex.ui.home

import android.hardware.usb.UsbManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.wavedex.ConnectionPhase
import com.wavedex.UsbConnectionViewModel
import com.wavedex.usb.RtlSdrUsb

@Composable
fun HomeScreen(
    viewModel: UsbConnectionViewModel,
    usbManager: UsbManager,
    modifier: Modifier = Modifier,
) {
    val state = viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current

    LaunchedEffect(state.value.phase) {
        if (state.value.phase == ConnectionPhase.PermissionDenied) {
            snackbarHostState.showSnackbar("USB permission denied")
        }
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        snackbarHost = { SnackbarHost(snackbarHostState) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .padding(innerPadding)
                .padding(horizontal = 24.dp, vertical = 20.dp)
                .fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = "WaveDex",
                style = MaterialTheme.typography.headlineLarge,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Text(
                text = "Radio birdwatching for quiet nights",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.secondary,
                textAlign = TextAlign.Center,
            )
            Text(
                text = "Tonight’s band: discoveries over frequencies.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )

            Spacer(modifier = Modifier.height(8.dp))

            when (state.value.phase) {
                ConnectionPhase.Searching -> CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
                else -> Spacer(modifier = Modifier.height(4.dp))
            }

            Text(
                text = state.value.statusDetail,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
                textAlign = TextAlign.Center,
            )

            if (state.value.nativeStatus.isNotBlank()) {
                Text(
                    text = state.value.nativeStatus,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.tertiary,
                    textAlign = TextAlign.Center,
                )
            }

            Spacer(modifier = Modifier.weight(1f, fill = true))

            val primaryEnabled = when (state.value.phase) {
                ConnectionPhase.Searching,
                ConnectionPhase.Ready,
                -> false

                ConnectionPhase.Idle,
                ConnectionPhase.Found,
                ConnectionPhase.PermissionDenied,
                -> true
            }

            val primaryLabel = when (state.value.phase) {
                ConnectionPhase.Idle -> "Look for dongle"
                ConnectionPhase.Found,
                ConnectionPhase.PermissionDenied,
                -> "Connect dongle"

                ConnectionPhase.Searching -> "Scanning…"
                ConnectionPhase.Ready -> "Connected"
            }

            Button(
                onClick = {
                    when (state.value.phase) {
                        ConnectionPhase.Idle -> viewModel.scan(usbManager)
                        ConnectionPhase.Found,
                        ConnectionPhase.PermissionDenied,
                        -> viewModel.requestPermission(usbManager, context)

                        else -> Unit
                    }
                },
                enabled = primaryEnabled,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                    disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                ),
            ) {
                Text(primaryLabel)
            }

            OutlinedButton(
                onClick = { viewModel.scan(usbManager) },
                enabled = state.value.phase != ConnectionPhase.Searching,
            ) {
                Text("Scan USB again")
            }

            Text(
                text = "Watching for VID 0x${RtlSdrUsb.REALTEK_VENDOR_ID.toString(16)} RTL2832U family",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
    }
}
