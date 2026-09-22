package com.vishguard.ai

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.vishguard.ai.services.OverlayService

class MainActivity : AppCompatActivity() {

    private var isServiceRunning = false
    private lateinit var btnToggleService: Button
    private lateinit var tvStatusInfo: TextView
    private lateinit var etFraseSimulada: EditText
    private lateinit var btnEnviarFrase: Button

    companion object {
        private const val OVERLAY_PERMISSION_REQ_CODE = 1234
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnToggleService = findViewById(R.id.btnToggleService)
        tvStatusInfo = findViewById(R.id.tvStatusInfo)
        etFraseSimulada = findViewById(R.id.etFraseSimulada)
        btnEnviarFrase = findViewById(R.id.btnEnviarFrase)

        btnToggleService.setOnClickListener {
            if (checkOverlayPermission()) {
                toggleOverlayService()
            } else {
                requestOverlayPermission()
            }
        }

        // 🚀 Evento para enviar la frase que escribas hacia el OverlayService
        btnEnviarFrase.setOnClickListener {
            val frase = etFraseSimulada.text.toString().trim()

            if (!isServiceRunning) {
                Toast.makeText(this, "Primero presiona 'ACTIVAR PROTECCIÓN'", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            if (frase.isNotEmpty()) {
                enviarTextoAlServicio(frase)
                etFraseSimulada.text.clear()
            } else {
                Toast.makeText(this, "Escribe una frase antes de analizar", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun enviarTextoAlServicio(texto: String) {
        val intent = Intent(this, OverlayService::class.java).apply {
            putExtra(OverlayService.EXTRA_TEXTO, texto)
        }
        startService(intent)
    }

    private fun checkOverlayPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(this)
        } else {
            true
        }
    }

    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Toast.makeText(
                this,
                "Por favor, concede el permiso para mostrar la alerta sobre otras aplicaciones.",
                Toast.LENGTH_LONG
            ).show()

            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            startActivityForResult(intent, OVERLAY_PERMISSION_REQ_CODE)
        }
    }

    private fun toggleOverlayService() {
        val intent = Intent(this, OverlayService::class.java)

        if (!isServiceRunning) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            isServiceRunning = true
            btnToggleService.text = "DESACTIVAR PROTECCIÓN"
            btnToggleService.setBackgroundColor(android.graphics.Color.parseColor("#C62828"))
            tvStatusInfo.text = "Estado: Monitoreando llamadas..."
            tvStatusInfo.setTextColor(android.graphics.Color.parseColor("#4CAF50"))
        } else {
            stopService(intent)
            isServiceRunning = false
            btnToggleService.text = "ACTIVAR PROTECCIÓN"
            btnToggleService.setBackgroundColor(android.graphics.Color.parseColor("#2E7D32"))
            tvStatusInfo.text = "Estado: Desconectado"
            tvStatusInfo.setTextColor(android.graphics.Color.parseColor("#757575"))
        }
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == OVERLAY_PERMISSION_REQ_CODE) {
            if (checkOverlayPermission()) {
                toggleOverlayService()
            } else {
                Toast.makeText(this, "Permiso denegado. No se podrá mostrar la alerta.", Toast.LENGTH_SHORT).show()
            }
        }
    }
}