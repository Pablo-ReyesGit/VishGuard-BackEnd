package com.vishguard.ai.services

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.NotificationCompat
import com.google.gson.Gson
import com.vishguard.ai.R
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

// Data class ajustada para mapear la respuesta de Groq / Heurística local
data class VishingResponse(
    val nivel_riesgo: String? = null,
    val color: String? = null,
    val mensaje_alerta: String? = null,
    val recomendacion: String? = null,
    val patron_detectado: String? = null,
    val score: Int? = 0
)

class OverlayService : Service() {

    private lateinit var windowManager: WindowManager
    private var overlayView: View? = null
    private lateinit var container: LinearLayout
    private lateinit var tvShieldStatus: TextView
    private lateinit var tvScore: TextView
    private lateinit var tvRecommendation: TextView

    // ⏱️ Cliente HTTP configurado con Timeouts extendidos para la fase de pruebas
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS) // Conexión a la red local
        .readTimeout(15, TimeUnit.SECONDS)    // Tiempo de espera para la inferencia de la IA
        .writeTimeout(15, TimeUnit.SECONDS)   // Envío de la petición
        .build()

    private val gson = Gson()
    private val TAG = "VishGuardHTTP"

    companion object {
        const val EXTRA_TEXTO = "extra_texto_llamada"
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "🚀 [ANDROID LOG]: Servicio OverlayService creado correctamente.")
        startForegroundServiceNotification()
        setupOverlayWindow()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val textoRecibido = intent?.getStringExtra(EXTRA_TEXTO)

        if (!textoRecibido.isNullOrBlank()) {
            Log.d(TAG, "📞 [ANDROID LOG]: Frase enviada para análisis: \"$textoRecibido\"")
            enviarTextoParaAnalizar(textoRecibido)
        } else {
            // 👈 Cambiamos el texto por defecto al iniciar la protección
            Log.d(TAG, "🛡️ [ANDROID LOG]: Protección activa. Esperando audio/texto...")
            updateOverlayUI(
                VishingResponse(
                    nivel_riesgo = "INICIAL",
                    score = 0,
                    recomendacion = "Escaneando llamada en tiempo real..."
                )
            )
        }
        return START_STICKY
    }

    private fun startForegroundServiceNotification() {
        val channelId = "vishguard_channel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "VishGuard Protection Service",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("VishGuard AI Activo")
            .setContentText("Escaneando llamada en tiempo real...")
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notification)
        }
    }

    private fun setupOverlayWindow() {
        if (overlayView != null) return

        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val inflater = LayoutInflater.from(this)
        overlayView = inflater.inflate(R.layout.overlay_layout, null)

        container = overlayView!!.findViewById(R.id.overlayContainer)
        tvShieldStatus = overlayView!!.findViewById(R.id.tvShieldStatus)
        tvScore = overlayView!!.findViewById(R.id.tvScore)
        tvRecommendation = overlayView!!.findViewById(R.id.tvRecommendation)

        val layoutParamsType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutParamsType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )

        params.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        params.y = 90

        windowManager.addView(overlayView, params)
        Log.d(TAG, "🎨 [ANDROID LOG]: Tarjeta Flotante (Overlay) inflada y colocada en pantalla.")
    }

    // 🚀 Petición HTTP POST con Logs hacia FastAPI
    fun enviarTextoParaAnalizar(textoLlamada: String) {
        val urlServer = "http://10.170.195.216:8000/analizar-llamada"
        Log.i(TAG, "🌐 [ANDROID LOG]: Conectando a $urlServer...")
        Log.i(TAG, "📤 [ENVIANDO TEXTO]: \"$textoLlamada\"")

        // Feedback inmediato en pantalla mientras responde la IA
        Handler(Looper.getMainLooper()).post {
            tvShieldStatus.text = "🔍 Analizando intención..."
            tvRecommendation.text = "Procesando mensaje con el cerebro de IA..."
        }

        val jsonBody = mapOf("texto" to textoLlamada)
        val bodyString = gson.toJson(jsonBody)
        val body = bodyString.toRequestBody("application/json; charset=utf-8".toMediaType())

        val request = Request.Builder()
            .url(urlServer)
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                Log.e(TAG, "❌ [ANDROID LOG ERROR]: Falló la conexión con el servidor: ${e.message}")
            }

            override fun onResponse(call: Call, response: Response) {
                val responseData = response.body?.string()
                if (response.isSuccessful && responseData != null) {
                    Log.d(TAG, "✅ [ANDROID LOG]: ¡Conexión Exitosa con la PC! Respuesta recibida:")
                    Log.d(TAG, "📩 [JSON RECIBIDO]: $responseData")

                    try {
                        val resultado = gson.fromJson(responseData, VishingResponse::class.java)
                        if (resultado != null) {
                            updateOverlayUI(resultado)
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "❌ [ANDROID LOG ERROR]: Error al mapear el JSON: ${e.message}")
                    }
                } else {
                    Log.e(TAG, "⚠️ [ANDROID LOG ERROR]: Servidor respondió con código de error: ${response.code}")
                }
            }
        })
    }

    private fun updateOverlayUI(data: VishingResponse) {
        Handler(Looper.getMainLooper()).post {
            val score = data.score ?: 0
            val nivelRecibido = data.nivel_riesgo?.uppercase() ?: "INICIAL"

            Log.i(TAG, "🎨 [ANDROID LOG]: Actualizando Interfaz Móvil -> Riesgo: $nivelRecibido | Score: $score%")

            tvScore.text = "$score%"

            // 1. Asignamos la forma redondeada del drawable
            container.setBackgroundResource(R.drawable.bg_overlay_card)

            // 2. Evaluamos el color, título y mensaje descriptivo basándonos en el Score
            val (colorHex, tituloEstado, recomendacionTexto) = when {
                nivelRecibido == "INICIAL" && score == 0 -> Triple(
                    "#1B5E20",
                    "🛡️ VishGuard Activo",
                    "Escaneando llamada en tiempo real..."
                )
                score <= 25 -> Triple(
                    "#1B5E20",
                    "🛡️ Llamada Segura",
                    data.recomendacion ?: "Conversación cotidiana sin indicadores de riesgo."
                )
                score in 26..60 -> Triple(
                    "#E65100",
                    "⚠️ Sospecha Detectada",
                    if (data.recomendacion?.contains("segura", ignoreCase = true) == true)
                        "Precaución: La conversación contiene patrones inusuales o solicitud de datos."
                    else
                        (data.recomendacion ?: "Precaución: Valide la identidad del interlocutor.")
                )
                score > 60 -> Triple(
                    "#B71C1C",
                    "🛑 ALERTA DE FRAUDE",
                    data.recomendacion ?: "¡Peligro! No proporcione claves, códigos SMS ni datos bancarios."
                )
                else -> Triple(
                    "#1B5E20",
                    "🛡️ VishGuard Activo",
                    "Escaneando llamada..."
                )
            }

            tvShieldStatus.text = tituloEstado
            tvRecommendation.text = recomendacionTexto

            // 3. Aplicamos la tinta respetando los bordes redondeados
            container.background?.let { backgroundDrawable ->
                val wrappedDrawable = androidx.core.graphics.drawable.DrawableCompat.wrap(backgroundDrawable).mutate()
                androidx.core.graphics.drawable.DrawableCompat.setTint(wrappedDrawable, Color.parseColor(colorHex))
                container.background = wrappedDrawable
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        overlayView?.let {
            windowManager.removeView(it)
            overlayView = null
        }
    }
}