package br.ps2ponte.core.block

import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ReadOnlyBlockDeviceTest {
    @Test fun protectsWritesAndOwnsResource() {
        var writes = 0
        var closed = false
        val source = object : BlockDevice {
            override val sectorSize = 512
            override val sectorCount = 8L
            override val readOnly = false
            override fun read(lba: Long, count: Int, buf: ByteArray, off: Int) { buf[off] = 42 }
            override fun write(lba: Long, count: Int, buf: ByteArray, off: Int) { writes++ }
            override fun close() { closed = true }
        }
        val disk = ReadOnlyBlockDevice(source)
        val data = ByteArray(512)
        assertTrue(disk.readOnly)
        assertEquals(512, disk.sectorSize)
        assertEquals(8L, disk.sectorCount)
        disk.read(0, 1, data, 0)
        assertEquals(42.toByte(), data[0])
        assertFailsWith<IOException> { disk.write(0, 1, data, 0) }
        assertEquals(0, writes)
        disk.close()
        assertTrue(closed)
    }
}
