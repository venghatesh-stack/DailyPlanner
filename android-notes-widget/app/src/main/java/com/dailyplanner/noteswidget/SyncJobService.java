package com.dailyplanner.noteswidget;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/**
 * All network work for the widget happens here, never while the widget is
 * drawing. Android runs this job as soon as there is a connection:
 *   * right after any change made on the widget (sync now),
 *   * every 15 minutes, to bring in changes made in the planner.
 */
public class SyncJobService extends JobService {
    private static final int NOW_ID = 4101;
    private static final int PERIODIC_ID = 4102;

    @Override
    public boolean onStartJob(JobParameters params) {
        final Context app = getApplicationContext();
        new Thread(() -> {
            boolean done = false;
            try {
                done = Store.flush(app);
            } catch (Throwable e) {
                CrashLog.record(app, e, "Background sync");
                Prefs.saveError(app, "Sync failed: " + e.getMessage());
            }
            NotesWidgetProvider.showLocal(app);
            // Retry later (with backoff) only if changes are still waiting.
            jobFinished(params, !done && Store.pending(app) > 0 && params.getJobId() == NOW_ID);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;   // interrupted: run again later
    }

    /** Sync as soon as there is a network connection. */
    static void syncSoon(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (js == null) return;
        js.schedule(new JobInfo.Builder(NOW_ID, new ComponentName(c, SyncJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setBackoffCriteria(30_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .build());
    }

    /** Keep the widget fresh every 15 minutes (Android's shortest interval). */
    static void schedulePeriodic(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (js == null) return;
        if (js.getPendingJob(PERIODIC_ID) != null) return;
        js.schedule(new JobInfo.Builder(PERIODIC_ID, new ComponentName(c, SyncJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true)
                .build());
    }

    static void cancelPeriodic(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (js != null) js.cancel(PERIODIC_ID);
    }
}
