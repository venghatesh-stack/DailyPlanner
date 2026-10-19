package com.dailyplanner.noteswidget;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.Iterator;
import java.util.UUID;

/**
 * Notes as this phone knows them, plus an outbox of changes not yet on the
 * server. Every edit is applied here first, so the widget and editor update
 * at once, even offline. {@link #flush} sends the outbox in order whenever
 * the server can be reached. Notes made here get a "local-" id until the
 * server gives them a real one.
 */
final class Store {
    private static final String FILE = "notes_widget";
    private static final Object LOCK = new Object();

    private Store() {}

    private static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    // ── reading ──────────────────────────────────────────────────────────
    static JSONArray notes(Context c) {
        synchronized (LOCK) {
            try {
                String raw = Prefs.cache(c);
                if (raw.isEmpty()) return new JSONArray();
                JSONArray a = new JSONObject(raw).optJSONArray("notes");
                return a == null ? new JSONArray() : a;
            } catch (JSONException e) {
                return new JSONArray();
            }
        }
    }

    static JSONObject note(Context c, String id) {
        return find(notes(c), id);
    }

    static int pending(Context c) {
        return outbox(c).length();
    }

    private static JSONObject find(JSONArray arr, String id) {
        if (id == null) return null;
        for (int i = 0; i < arr.length(); i++) {
            JSONObject n = arr.optJSONObject(i);
            if (n != null && id.equals(n.optString("id"))) return n;
        }
        return null;
    }

    private static JSONArray outbox(Context c) {
        try {
            return new JSONArray(sp(c).getString("outbox", "[]"));
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    private static void save(Context c, JSONArray notes, JSONArray outbox) {
        JSONObject wrap = new JSONObject();
        try {
            wrap.put("notes", notes);
        } catch (JSONException ignored) {
            // cannot happen with a JSONArray
        }
        sp(c).edit().putString("cache", wrap.toString()).putString("outbox", outbox.toString()).commit();
    }

    static String newItemId() {
        return "w" + UUID.randomUUID().toString().replace("-", "").substring(0, 11);
    }

    static boolean isLocal(String id) {
        return id != null && id.startsWith("local-");
    }

    // ── changing (always local first) ────────────────────────────────────
    /** Adds a note on this phone and queues it for the server. Returns its (local) id. */
    static String createNote(Context c, JSONObject fields) {
        synchronized (LOCK) {
            String id = "local-" + UUID.randomUUID().toString().substring(0, 8);
            JSONArray notes = notes(c), out = outbox(c);
            try {
                JSONObject n = new JSONObject(fields.toString());
                n.put("id", id);
                n.put("updated_at", nowIso());
                JSONArray next = new JSONArray();
                next.put(n);
                for (int i = 0; i < notes.length(); i++) next.put(notes.get(i));
                JSONObject op = new JSONObject();
                op.put("type", "create");
                op.put("id", id);
                op.put("fields", new JSONObject(fields.toString()));
                out.put(op);
                save(c, next, out);
            } catch (JSONException ignored) {
                // fields came from our own code
            }
            return id;
        }
    }

    /** Applies changed fields to a note here and queues them for the server. */
    static void patchNote(Context c, String id, JSONObject fields) {
        synchronized (LOCK) {
            JSONArray notes = notes(c), out = outbox(c);
            JSONObject n = find(notes, id);
            try {
                if (n != null) {
                    merge(n, fields);
                    n.put("updated_at", nowIso());
                }
                JSONObject target = null;
                for (int i = 0; i < out.length(); i++) {
                    JSONObject op = out.getJSONObject(i);
                    if (id.equals(op.optString("id")) && "create".equals(op.optString("type"))
                            && !(i == 0 && (id + "|create").equals(inFlight))) target = op;
                }
                if (target == null && out.length() > 0) {
                    JSONObject last = out.getJSONObject(out.length() - 1);
                    boolean sending = out.length() == 1 && (id + "|patch").equals(inFlight);
                    if (!sending && id.equals(last.optString("id")) && "patch".equals(last.optString("type"))) target = last;
                }
                if (target != null) {
                    merge(target.getJSONObject("fields"), fields);
                } else {
                    JSONObject op = new JSONObject();
                    op.put("type", "patch");
                    op.put("id", id);
                    op.put("fields", new JSONObject(fields.toString()));
                    out.put(op);
                }
                save(c, notes, out);
            } catch (JSONException ignored) {
                // our own data
            }
        }
    }

    /** Ticks or unticks one checklist item (the server flips just that item). */
    static void toggleItem(Context c, String noteId, String itemId) {
        synchronized (LOCK) {
            JSONArray notes = notes(c), out = outbox(c);
            JSONObject n = find(notes, noteId);
            if (n == null) return;
            JSONArray items = n.optJSONArray("items");
            if (items == null) return;
            try {
                for (int i = 0; i < items.length(); i++) {
                    JSONObject it = items.getJSONObject(i);
                    if (itemId.equals(it.optString("id"))) it.put("done", !it.optBoolean("done"));
                }
                if (isLocal(noteId)) {
                    boolean merged = false;
                    for (int i = 0; i < out.length(); i++) {
                        JSONObject op = out.getJSONObject(i);
                        if (noteId.equals(op.optString("id")) && "create".equals(op.optString("type"))
                                && !(i == 0 && (noteId + "|create").equals(inFlight))) {
                            op.getJSONObject("fields").put("items", new JSONArray(items.toString()));
                            merged = true;
                        }
                    }
                    if (!merged) {
                        JSONObject op = new JSONObject();
                        op.put("type", "patch");
                        op.put("id", noteId);
                        JSONObject f = new JSONObject();
                        f.put("items", new JSONArray(items.toString()));
                        op.put("fields", f);
                        out.put(op);
                    }
                } else {
                    JSONObject op = new JSONObject();
                    op.put("type", "toggle");
                    op.put("id", noteId);
                    op.put("item_id", itemId);
                    out.put(op);
                }
                save(c, notes, out);
            } catch (JSONException ignored) {
                // our own data
            }
        }
    }

    private static void merge(JSONObject into, JSONObject from) throws JSONException {
        Iterator<String> keys = from.keys();
        while (keys.hasNext()) {
            String k = keys.next();
            into.put(k, from.get(k));
        }
    }

    private static String nowIso() {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", java.util.Locale.US);
        f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
        return f.format(new java.util.Date());
    }

    // ── syncing ──────────────────────────────────────────────────────────
    /**
     * Sends queued changes in order, then (if nothing is left) fetches the
     * server's notes, which also brings in edits made in the planner.
     * Returns true when everything is in sync. Blocking.
     */
    private static final Object SYNC = new Object();   // one sync at a time; edits never wait on it
    /** The queued change being sent right now: new edits must not merge into it. */
    private static volatile String inFlight = null;

    static boolean flush(Context c) {
        synchronized (SYNC) {
            if (!Prefs.connected(c)) return false;
            while (true) {
                JSONObject op;
                synchronized (LOCK) {
                    JSONArray out = outbox(c);
                    if (out.length() == 0) break;
                    op = out.optJSONObject(0);
                    inFlight = op.optString("id") + "|" + op.optString("type");
                }
                try {
                    send(c, op);
                    drop(c, 0);
                    inFlight = null;
                } catch (Api.ApiException e) {
                    inFlight = null;
                    if (e.code == 401) { Prefs.saveError(c, e.getMessage()); return false; }
                    if (e.code >= 500 || e.code == 408 || e.code == 429) { Prefs.saveError(c, "Will sync when the server is back"); return false; }
                    drop(c, 0);           // the server refused this change (note deleted elsewhere): move on
                } catch (IOException e) {
                    inFlight = null;
                    Prefs.saveError(c, "Offline. Changes are saved on this phone and will sync.");
                    return false;
                } catch (JSONException e) {
                    inFlight = null;
                    drop(c, 0);
                }
            }
            try {
                String json = Api.fetchNotes(c);
                synchronized (LOCK) {
                    // Keep anything edited on the phone while we were fetching.
                    if (outbox(c).length() > 0) return false;
                    Prefs.saveResult(c, json);
                }
                return true;
            } catch (Api.ApiException e) {
                Prefs.saveError(c, e.getMessage());
            } catch (IOException e) {
                Prefs.saveError(c, "Offline. Showing notes saved on this phone.");
            }
            return false;
        }
    }

    private static void send(Context c, JSONObject op) throws IOException, JSONException {
        String type = op.optString("type");
        String id = op.optString("id");
        if ("create".equals(type)) {
            JSONObject created = Api.createNote(c, op.getJSONObject("fields"));
            remap(c, id, created);
        } else if ("patch".equals(type)) {
            if (!isLocal(id)) Api.updateNote(c, id, op.getJSONObject("fields"));
        } else if ("toggle".equals(type)) {
            if (!isLocal(id)) Api.toggle(c, id, op.optString("item_id"));
        }
    }

    private static void drop(Context c, int index) {
        synchronized (LOCK) {
        JSONArray out = outbox(c), next = new JSONArray();
        for (int i = 0; i < out.length(); i++) if (i != index) next.put(out.opt(i));
        sp(c).edit().putString("outbox", next.toString()).commit();
        }
    }

    /** A local note got its server id: update the notes and any queued changes. */
    private static void remap(Context c, String localId, JSONObject server) throws JSONException {
        synchronized (LOCK) {
        String realId = server.getString("id");
        JSONArray notes = notes(c), out = outbox(c);
        JSONObject n = find(notes, localId);
        if (n != null) {
            n.put("id", realId);
            if (server.has("created_at")) n.put("created_at", server.get("created_at"));
        }
        for (int i = 0; i < out.length(); i++) {
            JSONObject op = out.getJSONObject(i);
            if (localId.equals(op.optString("id"))) op.put("id", realId);
        }
        save(c, notes, out);
        }
    }
}
