package com.dailyplanner.noteswidget;

import android.content.Context;
import android.net.Uri;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** The two calls the widget makes. Blocking: call from a background thread. */
final class Api {
    static final class ApiException extends IOException {
        final int code;
        ApiException(int code, String message) {
            super(message);
            this.code = code;
        }
    }

    private Api() {}

    /** GET /api/widget/notes. Returns the response body (JSON text). */
    static String fetchNotes(Context c) throws IOException {
        String url = Prefs.server(c) + "/api/widget/notes?scope=" + Uri.encode(Prefs.scope(c));
        return request(c, "GET", url, null);
    }

    /** POST /api/widget/notes/{id}/toggle with {"item_id": ...}. */
    static void toggle(Context c, String noteId, String itemId) throws IOException {
        try {
            JSONObject body = new JSONObject();
            body.put("item_id", itemId);
            request(c, "POST", Prefs.server(c) + "/api/widget/notes/" + Uri.encode(noteId) + "/toggle",
                    body.toString());
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        }
    }

    /** POST /api/widget/notes. Returns the created note. */
    static JSONObject createNote(Context c, JSONObject fields) throws IOException {
        String text = request(c, "POST", Prefs.server(c) + "/api/widget/notes", fields.toString());
        try {
            return new JSONObject(text).getJSONObject("note");
        } catch (org.json.JSONException e) {
            throw new IOException("Unexpected reply from the server");
        }
    }

    /** POST /api/widget/notes/{id} with the changed fields. */
    static void updateNote(Context c, String id, JSONObject fields) throws IOException {
        request(c, "POST", Prefs.server(c) + "/api/widget/notes/" + Uri.encode(id), fields.toString());
    }

    private static String request(Context c, String method, String url, String body) throws IOException {
        if (!Prefs.connected(c)) throw new ApiException(401, "Not connected");
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        try {
            conn.setRequestMethod(method);
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);   // a sleeping free-tier server can take a while to wake
            conn.setRequestProperty("Authorization", "Bearer " + Prefs.token(c));
            conn.setRequestProperty("Accept", "application/json");
            if (body != null) {
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json");
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(bytes);
                }
            }
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String text = in == null ? "" : read(in);
            if (code == 401) throw new ApiException(code, "Disconnected. Connect again from Color Notes.");
            if (code >= 400) {
                String msg = "Server error " + code;
                try {
                    msg = new JSONObject(text).optString("error", msg);
                } catch (Exception ignored) {
                    // not JSON
                }
                throw new ApiException(code, msg);
            }
            return text;
        } finally {
            conn.disconnect();
        }
    }

    private static String read(InputStream in) throws IOException {
        try (InputStream is = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) != -1) out.write(buf, 0, n);
            return out.toString("UTF-8");
        }
    }
}
