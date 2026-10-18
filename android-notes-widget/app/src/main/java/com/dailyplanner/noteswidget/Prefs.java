package com.dailyplanner.noteswidget;

import android.content.Context;
import android.content.SharedPreferences;

/** Connection settings and the last notes we fetched (shown when offline). */
final class Prefs {
    private static final String FILE = "notes_widget";

    private Prefs() {}

    private static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static String server(Context c) { return sp(c).getString("server", ""); }
    static String token(Context c) { return sp(c).getString("token", ""); }
    static String scope(Context c) { return sp(c).getString("scope", "pinned"); }
    static String cache(Context c) { return sp(c).getString("cache", ""); }
    static String error(Context c) { return sp(c).getString("error", ""); }
    static long lastSync(Context c) { return sp(c).getLong("last_sync", 0L); }

    static boolean connected(Context c) {
        return !server(c).isEmpty() && !token(c).isEmpty();
    }

    static void saveConnection(Context c, String server, String token, String scope) {
        String s = server.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (!s.isEmpty() && !s.startsWith("http://") && !s.startsWith("https://")) s = "https://" + s;
        sp(c).edit()
                .putString("server", s)
                .putString("token", token.trim())
                .putString("scope", scope)
                .remove("cache")
                .remove("error")
                .apply();
    }

    static void saveResult(Context c, String json) {
        sp(c).edit().putString("cache", json).putString("error", "")
                .putLong("last_sync", System.currentTimeMillis()).apply();
    }

    static void saveError(Context c, String message) {
        sp(c).edit().putString("error", message == null ? "" : message).apply();
    }
}
