package com.dailyplanner.noteswidget;

import android.content.Context;
import android.content.Intent;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.StrikethroughSpan;
import android.view.View;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

/** Supplies one card per note to the widget's list. */
public class NotesWidgetService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Factory(getApplicationContext());
    }

    static final class Factory implements RemoteViewsFactory {
        private static final int MAX_ITEMS = 8;
        private final Context context;
        private final List<JSONObject> notes = new ArrayList<>();

        Factory(Context context) {
            this.context = context;
        }

        @Override public void onCreate() { load(Prefs.cache(context)); }

        /**
         * Draws from the copy saved on the phone, so it is instant and works
         * offline. The network is SyncJobService's job; it redraws when done.
         */
        @Override
        public void onDataSetChanged() {
            if (!Prefs.connected(context)) {
                notes.clear();
                return;
            }
            load(Prefs.cache(context));
        }

        private void load(String json) {
            notes.clear();
            if (json == null || json.isEmpty()) return;
            try {
                JSONArray arr = new JSONObject(json).optJSONArray("notes");
                if (arr == null) return;
                for (int i = 0; i < arr.length(); i++) notes.add(arr.getJSONObject(i));
            } catch (Exception ignored) {
                // a bad cache just means an empty list until the next fetch
            }
        }

        @Override public void onDestroy() { notes.clear(); }
        @Override public int getCount() { return notes.size(); }
        @Override public RemoteViews getLoadingView() { return null; }
        @Override public int getViewTypeCount() { return 1; }
        @Override public long getItemId(int position) { return position; }
        @Override public boolean hasStableIds() { return false; }

        @Override
        public RemoteViews getViewAt(int position) {
            RemoteViews card = new RemoteViews(context.getPackageName(), R.layout.widget_note);
            if (position < 0 || position >= notes.size()) return card;
            JSONObject n = notes.get(position);
            String id = n.optString("id");
            int[] c = NoteColors.of(context, n.optString("color"));
            int bg = c[0], ink = c[1];

            card.setInt(R.id.card_bg, "setColorFilter", bg);

            String title = n.optString("title", "").trim();
            if (n.optBoolean("is_pinned")) title = title.isEmpty() ? "📌" : "📌 " + title;
            card.setTextViewText(R.id.note_title, title);
            card.setTextColor(R.id.note_title, ink);
            card.setViewVisibility(R.id.note_title, title.isEmpty() ? View.GONE : View.VISIBLE);

            card.removeAllViews(R.id.items);
            boolean checklist = "checklist".equals(n.optString("kind"));
            String meta = reminderText(n);
            if (checklist) {
                card.setViewVisibility(R.id.note_body, View.GONE);
                JSONArray items = n.optJSONArray("items");
                List<JSONObject> open = new ArrayList<>(), done = new ArrayList<>();
                if (items != null) {
                    for (int i = 0; i < items.length(); i++) {
                        JSONObject it = items.optJSONObject(i);
                        if (it == null || it.optString("text", "").trim().isEmpty()) continue;
                        (it.optBoolean("done") ? done : open).add(it);
                    }
                }
                List<JSONObject> shown = new ArrayList<>(open);
                shown.addAll(done);
                int count = 0;
                for (JSONObject it : shown) {
                    if (count++ >= MAX_ITEMS) break;
                    card.addView(R.id.items, itemRow(id, it, ink));
                }
                RemoteViews add = new RemoteViews(context.getPackageName(), R.layout.widget_add_row);
                add.setTextColor(R.id.add_row, NoteColors.fade(ink, 0xB0));
                Intent addIntent = new Intent();
                addIntent.putExtra(ActionActivity.EXTRA_ACTION, ActionActivity.ADD_ITEM);
                addIntent.putExtra(ActionActivity.EXTRA_NOTE, id);
                add.setOnClickFillInIntent(R.id.add_row, addIntent);
                card.addView(R.id.items, add);
                int total = open.size() + done.size();
                String progress = total == 0 ? "Empty checklist" : done.size() + "/" + total + " done";
                if (total > MAX_ITEMS) progress += " · +" + (total - MAX_ITEMS) + " more";
                meta = meta.isEmpty() ? progress : progress + " · " + meta;
            } else {
                String body = n.optString("body", "").trim();
                card.setTextViewText(R.id.note_body, body);
                card.setTextColor(R.id.note_body, ink);
                card.setViewVisibility(R.id.note_body, body.isEmpty() ? View.GONE : View.VISIBLE);
            }
            card.setTextViewText(R.id.note_meta, meta);
            card.setTextColor(R.id.note_meta, NoteColors.fade(ink, 0xB0));
            card.setViewVisibility(R.id.note_meta, meta.isEmpty() ? View.GONE : View.VISIBLE);

            Intent open = new Intent();
            open.putExtra(ActionActivity.EXTRA_ACTION, ActionActivity.OPEN);
            open.putExtra(ActionActivity.EXTRA_NOTE, id);
            card.setOnClickFillInIntent(R.id.card, open);
            return card;
        }

        private RemoteViews itemRow(String noteId, JSONObject it, int ink) {
            RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.widget_item);
            boolean isDone = it.optBoolean("done");
            String text = it.optString("text", "");
            if (isDone) {
                SpannableString s = new SpannableString(text);
                s.setSpan(new StrikethroughSpan(), 0, text.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                row.setTextViewText(R.id.item_text, s);
                row.setTextColor(R.id.item_text, NoteColors.fade(ink, 0x99));
            } else {
                row.setTextViewText(R.id.item_text, text);
                row.setTextColor(R.id.item_text, ink);
            }
            row.setImageViewResource(R.id.box, isDone ? R.drawable.ic_box_checked : R.drawable.ic_box);
            row.setInt(R.id.box, "setColorFilter", NoteColors.fade(ink, isDone ? 0x99 : 0xDD));
            row.setContentDescription(R.id.item_row, (isDone ? "Checked: " : "Not checked: ") + text);

            Intent toggle = new Intent();
            toggle.putExtra(ActionActivity.EXTRA_ACTION, ActionActivity.TOGGLE);
            toggle.putExtra(ActionActivity.EXTRA_NOTE, noteId);
            toggle.putExtra(ActionActivity.EXTRA_ITEM, it.optString("id"));
            row.setOnClickFillInIntent(R.id.item_row, toggle);
            return row;
        }

        private static String reminderText(JSONObject n) {
            String at = n.optString("remind_at", "");
            if (at.isEmpty() || "null".equals(at)) return "";
            try {
                String s = at.length() >= 19 ? at.substring(0, 19) : at;
                SimpleDateFormat in = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US);
                in.setTimeZone(TimeZone.getTimeZone("UTC"));
                Date d = in.parse(s);
                if (d == null) return "";
                SimpleDateFormat out = new SimpleDateFormat("EEE d MMM, h:mm a", Locale.getDefault());
                String rep = n.optString("remind_repeat", "none");
                return "⏰ " + out.format(d) + ("none".equals(rep) || rep.isEmpty() ? "" : " · " + rep);
            } catch (Exception e) {
                return "";
            }
        }
    }
}
