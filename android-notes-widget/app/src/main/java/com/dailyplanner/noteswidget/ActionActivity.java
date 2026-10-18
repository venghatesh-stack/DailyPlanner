package com.dailyplanner.noteswidget;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;

/**
 * Invisible activity behind every widget tap. Opening a page must come from
 * an activity (Android blocks activity starts from background broadcasts), so
 * taps land here, do their job and close at once.
 */
public class ActionActivity extends Activity {
    static final String EXTRA_ACTION = "action";
    static final String EXTRA_NOTE = "note_id";
    static final String EXTRA_ITEM = "item_id";
    static final String OPEN = "open";
    static final String TOGGLE = "toggle";
    static final String NEW = "new";
    static final String LIST = "list";

    static PendingIntent pending(Context c, int requestCode, String action) {
        Intent i = new Intent(c, ActionActivity.class).putExtra(EXTRA_ACTION, action);
        return PendingIntent.getActivity(c, requestCode, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent in = getIntent();
        String action = in.getStringExtra(EXTRA_ACTION);
        String noteId = in.getStringExtra(EXTRA_NOTE);
        final Context app = getApplicationContext();

        if (!Prefs.connected(this)) {
            startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            finish();
            return;
        }
        if (TOGGLE.equals(action) && noteId != null) {
            final String itemId = in.getStringExtra(EXTRA_ITEM);
            new Thread(() -> {
                try {
                    Api.toggle(app, noteId, itemId);
                } catch (Exception e) {
                    Prefs.saveError(app, "Could not tick that item: " + e.getMessage());
                }
                NotesWidgetProvider.refreshAll(app);
            }).start();
            finish();
            return;
        }
        String path = "/color-notes";
        if (OPEN.equals(action) && noteId != null) path = "/color-notes?open=" + Uri.encode(noteId);
        else if (NEW.equals(action)) path = "/color-notes?new=text";
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(Prefs.server(this) + path))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception e) {
            Toast.makeText(this, "No browser found to open DailyPlanner", Toast.LENGTH_LONG).show();
        }
        finish();
    }
}
