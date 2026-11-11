package br.ps2ponte

import android.app.Activity
import android.os.Bundle
import android.graphics.Typeface
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.text.format.Formatter
import java.util.Locale
import java.util.concurrent.Executors

/** Inventário somente leitura; nenhuma cópia dos jogos é criada. */
class BibliotecaActivity : Activity() {
    private data class Item(val nome: String, val pasta: String, val bytes: Long)
    private val executor = Executors.newSingleThreadExecutor()
    private var itens = emptyList<Item>()
    private lateinit var lista: LinearLayout
    private lateinit var resumo: TextView
    private lateinit var busca: EditText
    private var geracao = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        Aparencia.aplicar(this)
        super.onCreate(savedInstanceState)
        val raiz = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(20), dp(16), dp(20), dp(20)) }
        raiz.addView(Button(this).apply { text = getString(R.string.maizo_voltar); setOnClickListener { finish() } })
        raiz.addView(TextView(this).apply { text = getString(R.string.maizo_biblioteca); textSize = 26f; setTypeface(typeface, Typeface.BOLD) })
        busca = EditText(this).apply { hint = getString(R.string.maizo_buscar); setSingleLine() }
        raiz.addView(busca)
        resumo = TextView(this).also { raiz.addView(it) }
        raiz.addView(Button(this).apply { text = getString(R.string.maizo_atualizar); setOnClickListener { carregar() } })
        lista = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        raiz.addView(ScrollView(this).apply { addView(lista) }, LinearLayout.LayoutParams(-1, 0, 1f))
        busca.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { mostrar() }
            override fun afterTextChanged(s: Editable?) {}
        })
        setContentView(raiz)
        carregar()
    }
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
    private fun carregar() {
        val id = ++geracao
        resumo.text = getString(R.string.maizo_carregando)
        val pasta = getSharedPreferences("ps2ponte", MODE_PRIVATE).getString("pasta", null)
        if (pasta == null) { resumo.text = getString(R.string.av_escolha_pasta); return }
        executor.execute {
            try {
                val raiz = Fonte.raiz(this, pasta)
                val encontrados = mutableListOf<Item>()
                for (dir in raiz.listFiles().orEmpty().filter { it.isDirectory && it.name.uppercase(Locale.ROOT) in setOf("DVD", "CD", "POPS", "APPS") }) {
                    for (file in dir.listFiles().orEmpty()) {
                        if (file.isFile && file.name.substringAfterLast('.', "").lowercase(Locale.ROOT) in setOf("iso", "zso", "vcd", "elf", "chd"))
                            encontrados += Item(file.name, dir.name, file.length())
                    }
                }
                val ordenados = encontrados.sortedBy { it.nome.lowercase(Locale.ROOT) }
                runOnUiThread { if (!isFinishing && id == geracao) { itens = ordenados; mostrar() } }
            } catch (e: Exception) {
                runOnUiThread { if (!isFinishing && id == geracao) resumo.text = getString(R.string.pasta_erro, e.message ?: "") }
            }
        }
    }
    private fun mostrar() {
        val filtrados = itens.filter { it.nome.contains(busca.text, ignoreCase = true) }
        resumo.text = getString(R.string.maizo_contagem, filtrados.size, Formatter.formatFileSize(this, filtrados.sumOf { it.bytes }))
        lista.removeAllViews()
        for (item in filtrados) lista.addView(TextView(this).apply {
            text = "${item.pasta}  ·  ${item.nome}\n${Formatter.formatFileSize(this@BibliotecaActivity, item.bytes)}"
            textSize = 14f; setPadding(0, dp(12), 0, dp(12)); setTextIsSelectable(true)
        })
    }
    override fun onDestroy() { geracao++; executor.shutdownNow(); super.onDestroy() }
}
