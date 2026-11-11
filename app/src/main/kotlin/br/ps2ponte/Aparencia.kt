package br.ps2ponte

import android.app.Activity
import android.content.Context
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.os.Build

/** Preferências exclusivas da interface; não alteram a sessão de transferência. */
object Aparencia {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("maizonas_visual", Context.MODE_PRIVATE)
    fun nome(ctx: Context) = prefs(ctx).getString("nome", "MaizonNAS Android") ?: "MaizonNAS Android"
    fun compacto(ctx: Context) = prefs(ctx).getBoolean("compacto", false)
    fun cor(ctx: Context) = prefs(ctx).getInt("cor", Color.rgb(83, 224, 189))
    fun tema(ctx: Context) = prefs(ctx).getInt("tema", 0)
    fun aplicar(a: Activity) {
        val claro = when (tema(a)) {
            1 -> false
            2 -> true
            else -> a.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK != Configuration.UI_MODE_NIGHT_YES
        }
        a.setTheme(if (claro) R.style.MaizoClaro else R.style.MaizoEscuro)
    }
    fun salvar(ctx: Context, nome: String, tema: Int, cor: Int, compacto: Boolean) {
        prefs(ctx).edit().putString("nome", nome.trim().take(48).ifEmpty { "MaizonNAS Android" })
            .putInt("tema", tema.coerceIn(0, 2)).putInt("cor", cor).putBoolean("compacto", compacto).apply()
    }
}
