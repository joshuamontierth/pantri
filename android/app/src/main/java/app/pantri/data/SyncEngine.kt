package app.pantri.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.pantri.PantriApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerializationException
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import java.io.IOException
import java.util.concurrent.TimeUnit

enum class Connection { Connecting, Live, Online, Offline }

data class SyncStatus(
    val connection: Connection = Connection.Connecting,
    val pending: Int = 0,
    val syncing: Boolean = false,
    val lastSynced: Long? = null,
)

sealed interface EngineEvent {
    data class Message(val text: String) : EngineEvent
    data object LoggedOut : EngineEvent
    data object HouseholdGone : EngineEvent
}

/**
 * Keeps the phone's copy of a household in step with the server.
 *
 * The list on screen is always [LocalApply.view] of the last server snapshot plus the queued
 * ops, so it works the same offline and online. Ops are sent whenever the server is reachable;
 * the server applies each one at most once and answers with a fresh snapshot. While the app is
 * open, a live event stream tells us when someone else changed something.
 */
class SyncEngine(
    private val context: Context,
    private val settings: Settings,
    private val api: Api,
    private val store: LocalStore,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val syncMutex = Mutex()
    private val lock = Any()

    // Guarded by lock.
    private var householdId = -1L
    private var snapshot: HouseholdState? = null
    private var etag: String? = null
    private val ops = mutableListOf<Op>()
    private val refs = LinkedHashMap<String, Long>()
    private val inFlight = mutableSetOf<String>()

    private val _view = MutableStateFlow<LocalView?>(null)
    val view = _view.asStateFlow()
    private val _status = MutableStateFlow(SyncStatus())
    val status = _status.asStateFlow()
    private val _events = MutableSharedFlow<EngineEvent>(extraBufferCapacity = 16)
    val events = _events.asSharedFlow()

    private val wake = Channel<Unit>(Channel.CONFLATED)
    @Volatile private var foreground = false
    @Volatile private var stream: EventSource? = null
    @Volatile private var streamOpen = false
    private var streamGen = 0
    private var retryMs = RETRY_MIN
    private var streamRetryMs = RETRY_MIN
    private var retryJob: Job? = null
    private var reconnectJob: Job? = null

    init {
        scope.launch {
            for (signal in wake) {
                delay(120) // let a burst of taps go out as one batch
                runCatching { syncOnce() } // never let one bad round stop syncing for good
            }
        }
        context.getSystemService(ConnectivityManager::class.java)?.registerDefaultNetworkCallback(
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    retryMs = RETRY_MIN
                    streamRetryMs = RETRY_MIN
                    requestSync()
                    if (foreground) scope.launch { restartStream() }
                }
            },
        )
    }

    val openHouseholdId: Long get() = synchronized(lock) { householdId }

    /** Load a household's saved copy (instantly, even offline), then catch up with the server. */
    fun open(id: Long) {
        synchronized(lock) {
            householdId = id
            snapshot = store.loadState(id)
            etag = null
            val outbox = store.loadOutbox(id)
            ops.clear()
            ops.addAll(outbox.ops)
            refs.clear()
            refs.putAll(outbox.refs)
            inFlight.clear()
            publishLocked()
        }
        _status.update { it.copy(connection = Connection.Connecting, lastSynced = null) }
        restartStream()
        requestSync()
    }

    fun close() {
        stopStream()
        synchronized(lock) {
            householdId = -1
            snapshot = null
            ops.clear()
            refs.clear()
            _view.value = null
        }
        _status.value = SyncStatus()
    }

    fun pendingCount() = synchronized(lock) { ops.size }

    /** The server sent a fresh household after a change made online (store, catalog, recipe). */
    fun acceptState(id: Long, state: HouseholdState) {
        synchronized(lock) {
            if (householdId != id) return
            snapshot = state
            etag = null
            store.saveState(id, state)
            publishLocked()
        }
    }

    fun enqueue(vararg newOps: Op) {
        synchronized(lock) {
            if (householdId < 0) return
            ops.addAll(newOps)
            persistOutboxLocked()
            publishLocked()
        }
        requestSync()
    }

    /** Take back queued changes that haven't been sent yet (for Undo). False if any already went. */
    fun cancel(opIds: Collection<String>): Boolean = synchronized(lock) {
        if (opIds.any { it in inFlight } || opIds.any { id -> ops.none { it.opId == id } }) return false
        ops.removeAll { it.opId in opIds }
        persistOutboxLocked()
        publishLocked()
        true
    }

    fun requestSync() {
        wake.trySend(Unit)
    }

    fun setForeground(value: Boolean) {
        foreground = value
        if (value) {
            restartStream()
            requestSync()
        } else {
            stopStream()
            scheduleBackgroundSync()
        }
    }

    /** One round trip. Returns true when everything queued has reached the server. */
    suspend fun syncOnce(): Boolean = syncMutex.withLock {
        val hid: Long
        val batch: List<Op>
        val tag: String?
        synchronized(lock) {
            if (householdId < 0 || settings.token == null) return false
            hid = householdId
            batch = ops.take(MAX_BATCH)
            tag = etag
            inFlight.addAll(batch.map { it.opId })
        }
        _status.update { it.copy(syncing = true) }
        try {
            if (batch.isNotEmpty()) {
                val resp = api.ops(hid, batch)
                val problems = mutableListOf<String>()
                synchronized(lock) {
                    if (householdId != hid) return false
                    val byId = resp.results.associateBy { it.opId }
                    for (op in batch) {
                        val r = byId[op.opId] ?: continue
                        if (op is AddOp && r.itemId != null) refs[op.ref] = r.itemId
                        if (r.status == "error") r.message?.let { problems += it }
                    }
                    val sent = batch.map { it.opId }.toSet()
                    ops.removeAll { it.opId in sent }
                    while (refs.size > MAX_REFS) refs.remove(refs.keys.first())
                    snapshot = resp.state
                    etag = null
                    store.saveState(hid, resp.state)
                    persistOutboxLocked()
                    publishLocked()
                }
                problems.distinct().forEach { _events.tryEmit(EngineEvent.Message(it)) }
            } else {
                val (state, newTag) = api.state(hid, tag)
                synchronized(lock) {
                    if (householdId != hid) return false
                    if (state != null) {
                        snapshot = state
                        store.saveState(hid, state)
                        publishLocked()
                    }
                    etag = newTag
                }
            }
            retryMs = RETRY_MIN
            _status.update {
                it.copy(connection = if (streamOpen) Connection.Live else Connection.Online, lastSynced = System.currentTimeMillis())
            }
            val more = synchronized(lock) { ops.isNotEmpty() }
            if (more) requestSync()
            !more
        } catch (e: ApiException) {
            when (e.code) {
                401 -> _events.tryEmit(EngineEvent.LoggedOut)
                403 -> {
                    _events.tryEmit(EngineEvent.Message(e.message ?: "Log in again."))
                    _events.tryEmit(EngineEvent.LoggedOut)
                }
                404 -> _events.tryEmit(EngineEvent.HouseholdGone)
                else -> {
                    _events.tryEmit(EngineEvent.Message(e.message ?: "Sync failed."))
                    scheduleRetry()
                }
            }
            false
        } catch (e: IOException) {
            _status.update { it.copy(connection = Connection.Offline) }
            scheduleRetry()
            false
        } catch (e: SerializationException) {
            _events.tryEmit(EngineEvent.Message("The server sent something this app doesn't understand. Is it up to date?"))
            scheduleRetry()
            false
        } catch (e: RuntimeException) {
            _events.tryEmit(EngineEvent.Message("Sync failed: ${e.message ?: e.javaClass.simpleName}"))
            scheduleRetry()
            false
        } finally {
            synchronized(lock) { inFlight.removeAll(batch.map { it.opId }.toSet()) }
            _status.update { it.copy(syncing = false, pending = pendingCount()) }
        }
    }

    /** For WorkManager: the app may have been closed, so load the saved household first. */
    suspend fun syncFromBackground(): Boolean {
        if (openHouseholdId < 0 && settings.token != null && settings.householdId >= 0) open(settings.householdId)
        return syncOnce()
    }

    private fun publishLocked() {
        _view.value = snapshot?.let { LocalApply.view(it, ops, refs) }
        _status.update { it.copy(pending = ops.size) }
    }

    private fun persistOutboxLocked() {
        if (householdId >= 0) store.saveOutbox(householdId, Outbox(ops.toList(), LinkedHashMap(refs)))
    }

    private fun scheduleRetry() {
        if (!foreground && pendingCount() == 0) return
        retryJob?.cancel()
        val wait = retryMs
        retryMs = (retryMs * 2).coerceAtMost(RETRY_MAX)
        retryJob = scope.launch {
            delay(wait)
            requestSync()
        }
        if (!foreground) scheduleBackgroundSync()
    }

    private fun scheduleBackgroundSync() {
        if (pendingCount() == 0) return
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork("sync", ExistingWorkPolicy.KEEP, request)
    }

    // ---------- live updates ----------

    @Synchronized
    private fun restartStream() {
        stopStream()
        if (!foreground) return
        val hid = openHouseholdId
        if (hid < 0 || settings.token == null) return
        val gen = streamGen
        stream = api.events(hid, object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                if (gen != streamGen) return
                streamOpen = true
                streamRetryMs = RETRY_MIN
                _status.update { it.copy(connection = Connection.Live) }
                requestSync() // catch up on anything missed while disconnected
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                if (gen != streamGen) return
                val event = runCatching { AppJson.decodeFromString(ServerEvent.serializer(), data) }.getOrNull() ?: return
                if (event.origin != null && event.origin == settings.clientId) return // our own change
                if (event.kind == "deleted") _events.tryEmit(EngineEvent.HouseholdGone) else requestSync()
            }

            override fun onClosed(eventSource: EventSource) {
                if (gen == streamGen) streamLost()
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                if (gen != streamGen) return
                when (response?.code) {
                    401 -> _events.tryEmit(EngineEvent.LoggedOut)
                    404 -> _events.tryEmit(EngineEvent.HouseholdGone)
                    else -> streamLost()
                }
            }
        })
    }

    private fun streamLost() {
        streamOpen = false
        stream = null
        _status.update { if (it.connection == Connection.Live) it.copy(connection = Connection.Connecting) else it }
        requestSync() // works out whether we're offline or just lost the stream
        if (!foreground) return
        reconnectJob?.cancel()
        val wait = streamRetryMs
        streamRetryMs = (streamRetryMs * 2).coerceAtMost(RETRY_MAX)
        reconnectJob = scope.launch {
            delay(wait)
            if (foreground && stream == null) restartStream()
        }
    }

    @Synchronized
    private fun stopStream() {
        streamGen++
        reconnectJob?.cancel()
        stream?.cancel()
        stream = null
        streamOpen = false
    }

    companion object {
        private const val RETRY_MIN = 2_000L
        private const val RETRY_MAX = 15_000L
        private const val MAX_BATCH = 400
        private const val MAX_REFS = 300
    }
}

/** Sends queued changes after the app is closed, once there's a network. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val engine = (applicationContext as PantriApp).engine
        return if (engine.syncFromBackground()) Result.success() else Result.retry()
    }
}
