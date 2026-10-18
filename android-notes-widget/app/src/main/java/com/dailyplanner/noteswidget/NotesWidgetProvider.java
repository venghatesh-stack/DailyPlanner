package com.dailyplanner.noteswidget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.text.format.DateUtils;
import android.widget.RemoteViews;

/** The home-screen widget: a header (title, refresh, +) over a list of note cards. */
public class NotesWidgetProvider extends AppWidgetProvider {
    static final String ACTION_REFRESH = "com.dailyplanner.noteswidget.REFRESH";

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) {
            manager.updateAppWidget(id, build(context, id));
        }
        manager.notifyAppWidgetViewDataChanged(ids, R.id.list);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        if (ACTION_REFRESH.equals(intent.getAction())) {
            refreshAll(context);
        }
    }

    /** Rebuild the header and reload every widget's notes from the server. */
    static void refreshAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, NotesWidgetProvider.class));
        if (ids == null || ids.length == 0) return;
        for (int id : ids) {
            manager.updateAppWidget(id, build(context, id));
        }
        manager.notifyAppWidgetViewDataChanged(ids, R.id.list);
    }

    /** Update only the header line (after a fetch finished). */
    static void updateHeaders(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, NotesWidgetProvider.class));
        if (ids == null) return;
        for (int id : ids) {
            RemoteViews rv = new RemoteViews(context.getPackageName(), R.layout.widget_notes);
            rv.setTextViewText(R.id.sub, subtitle(context));
            rv.setTextViewText(R.id.empty, emptyText(context));
            manager.partiallyUpdateAppWidget(id, rv);
        }
    }

    static String subtitle(Context c) {
        if (!Prefs.connected(c)) return "Not connected";
        String err = Prefs.error(c);
        long last = Prefs.lastSync(c);
        String when = last == 0 ? "" : "Updated " + DateUtils.getRelativeTimeSpanString(
                last, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS);
        if (!err.isEmpty()) return err.length() > 60 ? err.substring(0, 60) : err;
        return when;
    }

    static String emptyText(Context c) {
        if (!Prefs.connected(c)) return c.getString(R.string.not_connected);
        if (!Prefs.error(c).isEmpty() && Prefs.cache(c).isEmpty()) return Prefs.error(c) + "\nTap ⟳ to try again.";
        return Prefs.lastSync(c) == 0 ? c.getString(R.string.loading) : c.getString(R.string.no_notes);
    }

    static RemoteViews build(Context context, int widgetId) {
        RemoteViews rv = new RemoteViews(context.getPackageName(), R.layout.widget_notes);

        Intent svc = new Intent(context, NotesWidgetService.class);
        svc.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId);
        svc.setData(Uri.parse(svc.toUri(Intent.URI_INTENT_SCHEME)));
        rv.setRemoteAdapter(R.id.list, svc);
        rv.setEmptyView(R.id.list, R.id.empty);

        // One template for every tap inside the list; each card/item fills in what to do.
        Intent tap = new Intent(context, ActionActivity.class);
        rv.setPendingIntentTemplate(R.id.list, PendingIntent.getActivity(context, 10, tap,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE));

        Intent refresh = new Intent(context, NotesWidgetProvider.class).setAction(ACTION_REFRESH);
        rv.setOnClickPendingIntent(R.id.refresh, PendingIntent.getBroadcast(context, 11, refresh,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));

        rv.setOnClickPendingIntent(R.id.add, ActionActivity.pending(context, 12, ActionActivity.NEW));
        rv.setOnClickPendingIntent(R.id.header_text, ActionActivity.pending(context, 13, ActionActivity.LIST));

        Intent settings = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        rv.setOnClickPendingIntent(R.id.empty, PendingIntent.getActivity(context, 14, settings,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));

        rv.setTextViewText(R.id.sub, subtitle(context));
        rv.setTextViewText(R.id.empty, emptyText(context));
        return rv;
    }
}
