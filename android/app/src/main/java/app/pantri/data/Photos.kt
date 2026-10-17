package app.pantri.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.util.Log
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayOutputStream
import java.io.IOException
import kotlin.math.max

/** A photo that couldn't be opened or read (no permission, not an image). */
class PhotoException(message: String) : Exception(message)

/** Photos of recipes, made small and upright before they're sent (the server shrinks to 1600px anyway). */
object Photos {
    private const val MAX_SIDE = 1600

    fun prepare(context: Context, uri: Uri): ByteArray = try {
        read(context, uri)
    } catch (e: SecurityException) {
        Log.w("Photos", "no access to $uri", e)
        throw PhotoException("This app wasn't allowed to open that photo. Try Choose photos instead.")
    } catch (e: IOException) {
        Log.w("Photos", "couldn't read $uri", e)
        throw PhotoException("Couldn't open that photo.")
    } catch (e: OutOfMemoryError) {
        throw PhotoException("That photo is too large.")
    }

    private fun read(context: Context, uri: Uri): ByteArray {
        val resolver = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        // (Measuring only: decodeStream returns null here by design, and fills in bounds.)
        val stream = resolver.openInputStream(uri) ?: throw PhotoException("Couldn't open that photo.")
        stream.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0) throw PhotoException("That file isn't a photo I can read. Use a JPEG or PNG.")
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2
        val bitmap = resolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: throw PhotoException("That file isn't a photo I can read. Use a JPEG or PNG.")
        val rotation = resolver.openInputStream(uri)?.use {
            when (ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        } ?: 0f
        val scale = MAX_SIDE.toFloat() / max(bitmap.width, bitmap.height)
        val matrix = Matrix().apply {
            if (scale < 1f) postScale(scale, scale)
            if (rotation != 0f) postRotate(rotation)
        }
        val upright = if (matrix.isIdentity) bitmap else Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        return ByteArrayOutputStream().use { out ->
            upright.compress(Bitmap.CompressFormat.JPEG, 85, out)
            out.toByteArray()
        }
    }
}
