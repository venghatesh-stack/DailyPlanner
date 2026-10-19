package com.dailyplanner.noteswidget;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.RadioGroup;
import android.widget.TextView;

import org.json.JSONObject;

/** Connection settings. Also receives dpnotes://connect links from the Color Notes page. */
public class MainActivity extends Activity {
    private EditText server, token;
    private RadioGroup scope;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        server = findViewById(R.id.server);
        token = findViewById(R.id.token);
        scope = findViewById(R.id.scope);
        status = findViewById(R.id.status);
        Button save = findViewById(R.id.save);
        Button pin = findViewById(R.id.pin);
        Button open = findViewById(R.id.open);

        server.setText(Prefs.server(this));
        token.setText(Prefs.token(this));
        scope.check("all".equals(Prefs.scope(this)) ? R.id.scope_all : R.id.scope_pinned);
        showStatus(Prefs.connected(this) ? "Connected. Tap Save and test to check." : "Not connected yet.", false);

        save.setOnClickListener(v -> saveAndTest());
        pin.setOnClickListener(v -> requestPin());
        open.setOnClickListener(v -> {
            String s = Prefs.server(this);
            if (s.isEmpty()) {
                showStatus("Enter the server first.", true);
                return;
            }
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(s + "/color-notes")));
        });
        handleLink(getIntent());
        TextView version = new TextView(this);
        try {
            version.setText("Widget app version " + getPackageManager().getPackageInfo(getPackageName(), 0).versionName
                    + " · " + Store.pending(this) + " change(s) waiting to sync");
        } catch (Exception e) {
            version.setText("Widget app");
        }
        version.setAlpha(0.6f);
        version.setPadding(0, 24, 0, 0);
        ((android.widget.LinearLayout) status.getParent()).addView(version);
        // Rebuild the widget so its taps always run this version's code.
        NotesWidgetProvider.refreshAll(getApplicationContext());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleLink(intent);
    }

    private void handleLink(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null || !"dpnotes".equals(data.getScheme())) return;
        String s = data.getQueryParameter("server");
        String t = data.getQueryParameter("token");
        if (s == null || t == null) return;
        server.setText(s);
        token.setText(t);
        saveAndTest();
    }

    private void saveAndTest() {
        String sc = scope.getCheckedRadioButtonId() == R.id.scope_all ? "all" : "pinned";
        Prefs.saveConnection(this, server.getText().toString(), token.getText().toString(), sc);
        if (!Prefs.connected(this)) {
            showStatus("Enter both the server and the access code.", true);
            return;
        }
        showStatus("Checking… (the server may take up to a minute to wake up)", false);
        new Thread(() -> {
            String msg;
            boolean bad;
            android.content.Context app = getApplicationContext();
            boolean ok = Store.flush(app);
            int count = Store.notes(app).length();
            if (ok) {
                msg = "Connected. " + count + " note" + (count == 1 ? "" : "s") + " on the widget. "
                        + "Changes sync automatically.";
                bad = false;
            } else {
                msg = "Could not connect: " + Prefs.error(app);
                bad = true;
            }
            SyncJobService.schedulePeriodic(app);
            NotesWidgetProvider.refreshAll(app);
            final String m = msg;
            final boolean b = bad;
            runOnUiThread(() -> showStatus(m, b));
        }).start();
    }

    private void requestPin() {
        AppWidgetManager mgr = getSystemService(AppWidgetManager.class);
        if (mgr != null && mgr.isRequestPinAppWidgetSupported()) {
            mgr.requestPinAppWidget(new ComponentName(this, NotesWidgetProvider.class), null, null);
        } else {
            showStatus("Your launcher can't add widgets from an app. Long-press the home screen, "
                    + "tap Widgets and drag DailyPlanner Notes onto it.", true);
        }
    }

    private void showStatus(String text, boolean bad) {
        status.setText(text);
        status.setBackgroundColor(bad ? 0x33C2362F : 0x332F7D4F);
    }
}
