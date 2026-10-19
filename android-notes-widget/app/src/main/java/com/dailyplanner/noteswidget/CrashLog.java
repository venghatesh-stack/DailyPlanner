package com.dailyplanner.noteswidget;

import android.app.Application;
import android.content.Context;
import android.os.Build;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * Keeps the last error so it can be seen and shared from the app's main
 * screen, instead of vanishing into a "keeps stopping" dialog.
 */
public class CrashLog extends Application {
    private static final String FILE = "notes_widget_crash";

    @Override
    public void onCreate() {
        super.onCreate();
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        final Context app = getApplicationContext();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            record(app, error, "Crash on " + thread.getName());
            if (previous != null) previous.uncaughtException(thread, error);
        });
    }

    static void record(Context c, Throwable t, String where) {
        try {
            StringWriter sw = new StringWriter();
            t.printStackTrace(new PrintWriter(sw));
            String version = "";
            try {
                version = c.getPackageManager().getPackageInfo(c.getPackageName(), 0).versionName;
            } catch (Exception ignored) {
                // unknown version
            }
            String text = where + "\n"
                    + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date())
                    + " · app " + version + " · Android " + Build.VERSION.RELEASE + " · " + Build.MANUFACTURER + " " + Build.MODEL
                    + "\n\n" + sw;
            if (text.length() > 6000) text = text.substring(0, 6000);
            c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE)
                    .edit().putString("last", text).commit();
        } catch (Throwable ignored) {
            // never crash while recording a crash
        }
    }

    static String last(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE).getString("last", "");
    }

    static void clear(Context c) {
        c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().remove("last").commit();
    }
}
