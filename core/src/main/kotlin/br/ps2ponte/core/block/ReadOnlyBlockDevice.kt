package br.ps2ponte.core.block

import java.io.IOException

/** Protege a origem contra escritas de clientes de rede. O wrapper é dono do dispositivo. */
class ReadOnlyBlockDevice(private val inner: BlockDevice) : BlockDevice {
    override val sectorSize get() = inner.sectorSize
    override val sectorCount get() = inner.sectorCount
    override val readOnly = true
    override fun read(lba: Long, count: Int, buf: ByteArray, off: Int) = inner.read(lba, count, buf, off)
    override fun write(lba: Long, count: Int, buf: ByteArray, off: Int): Unit =
        throw IOException("MaizonNAS: dispositivo compartilhado somente para leitura")
    override fun close() = inner.close()
}
