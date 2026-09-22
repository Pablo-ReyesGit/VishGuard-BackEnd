<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:id="@+id/overlayContainer"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:layout_margin="12dp"
    android:background="@drawable/bg_overlay_card"
    android:elevation="10dp"
    android:orientation="vertical"
    android:padding="16dp">

    <!-- Encabezado: Estado e Indicador de Score -->
    <LinearLayout
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:gravity="center_vertical"
        android:orientation="horizontal">

        <TextView
            android:id="@+id/tvShieldStatus"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1"
            android:text="🛡️ Protección Activa"
            android:textColor="#FFFFFF"
            android:textSize="16sp"
            android:textStyle="bold" />

        <TextView
            android:id="@+id/tvScore"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:background="@drawable/bg_score_badge"
            android:paddingHorizontal="10dp"
            android:paddingVertical="4dp"
            android:text="0%"
            android:textColor="#FFFFFF"
            android:textSize="14sp"
            android:textStyle="bold" />
    </LinearLayout>

    <View
        android:layout_width="match_parent"
        android:layout_height="1dp"
        android:layout_marginVertical="10dp"
        android:background="#33FFFFFF" />

    <!-- Recomendación / Alerta -->
    <TextView
        android:id="@+id/tvRecommendation"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="Escaneando conversación en tiempo real..."
        android:textColor="#E0E0E0"
        android:textSize="13sp"
        android:lineSpacingExtra="2dp" />


</LinearLayout>