package app.shoppinglist

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import app.shoppinglist.data.Api
import app.shoppinglist.data.LocalStore
import app.shoppinglist.data.Settings
import app.shoppinglist.data.SyncEngine

class ShoppingApp : Application() {
    lateinit var settings: Settings
    lateinit var api: Api
    lateinit var store: LocalStore
    lateinit var engine: SyncEngine

    override fun onCreate() {
        super.onCreate()
        settings = Settings(this)
        api = Api(settings)
        store = LocalStore(filesDir)
        engine = SyncEngine(this, settings, api, store)
        if (settings.token != null && settings.householdId >= 0) engine.open(settings.householdId)
        // Live updates only while the app is on screen; queued changes still go out in the background.
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) = engine.setForeground(true)
            override fun onStop(owner: LifecycleOwner) = engine.setForeground(false)
        })
    }
}
