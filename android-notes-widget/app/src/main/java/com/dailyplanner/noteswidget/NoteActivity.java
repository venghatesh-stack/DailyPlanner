package com.dailyplanner.noteswidget;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Paint;
import android.net.Uri;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Edit a note right on the phone: title, text, checklist items (add, edit,
 * tick, delete), colour, voice. Saved on the phone when you leave, then
 * synced in the background, so the planner never has to open.
 */
public class NoteActivity extends Activity {
    private String noteId;
    private JSONObject original;
    private String color;
    private boolean isChecklist;
    private JSONArray items;
    private EditText title, body, newItem;
    private LinearLayout itemsBox, page;
    private ScrollView scroll;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        noteId = getIntent().getStringExtra(ActionActivity.EXTRA_NOTE);
        JSONObject n = Store.note(this, noteId);
        if (n == null) {
            finish();
            return;
        }
        try {
            original = new JSONObject(n.toString());
            items = new JSONArray(n.optJSONArray("items") == null ? "[]" : n.optJSONArray("items").toString());
        } catch (Exception e) {
            finish();
            return;
        }
        color = n.optString("color", "yellow");
        isChecklist = "checklist".equals(n.optString("kind"));

        scroll = new ScrollView(this);
        page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        int pad = Ui.dp(this, 18);
        page.setPadding(pad, pad, pad, pad);
        scroll.addView(page);

        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        title = new EditText(this);
        title.setHint("Title");
        title.setTextSize(22);
        title.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        title.setText(n.optString("title", ""));
        title.setBackground(null);
        top.addView(title, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        ImageButton mic = new ImageButton(this);
        mic.setImageResource(android.R.drawable.ic_btn_speak_now);
        mic.setContentDescription("Speak");
        mic.setOnClickListener(v -> Ui.listen(this));
        top.addView(mic);
        page.addView(top, Ui.matchWrap());

        LinearLayout colors = Ui.colorRow(this, color, name -> {
            color = name;
            paintPage();
        });
        colors.setPadding(0, 0, 0, Ui.dp(this, 10));
        page.addView(colors, Ui.matchWrap());

        if (isChecklist) {
            itemsBox = new LinearLayout(this);
            itemsBox.setOrientation(LinearLayout.VERTICAL);
            page.addView(itemsBox, Ui.matchWrap());
            newItem = new EditText(this);
            newItem.setHint("+ Add item");
            newItem.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            newItem.setImeOptions(EditorInfo.IME_ACTION_DONE);
            newItem.setOnEditorActionListener((v, actionId, ev) -> {
                addItems(newItem.getText().toString());
                newItem.setText("");
                return true;
            });
            page.addView(newItem, Ui.matchWrap());
            renderItems();
        } else {
            body = new EditText(this);
            body.setHint("Note");
            body.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            body.setGravity(Gravity.TOP);
            body.setMinLines(8);
            body.setBackground(null);
            body.setText(n.optString("body", ""));
            page.addView(body, Ui.matchWrap());
        }

        LinearLayout buttons = new LinearLayout(this);
        buttons.setGravity(Gravity.END);
        buttons.setPadding(0, Ui.dp(this, 12), 0, 0);
        Button web = new Button(this, null, android.R.attr.buttonBarButtonStyle);
        web.setText("Open in planner");
        web.setOnClickListener(v -> {
            save();
            if (!Store.isLocal(noteId)) {
                startActivity(new Intent(Intent.ACTION_VIEW,
                        Uri.parse(Prefs.server(this) + "/color-notes?open=" + Uri.encode(noteId))));
            }
            finish();
        });
        Button done = new Button(this, null, android.R.attr.buttonBarButtonStyle);
        done.setText("Done");
        done.setOnClickListener(v -> finish());
        buttons.addView(web);
        buttons.addView(done);
        page.addView(buttons, Ui.matchWrap());

        TextView hint = new TextView(this);
        hint.setTextSize(12);
        hint.setAlpha(0.6f);
        hint.setText("Saved on this phone and synced to DailyPlanner automatically. Reminders are set in the planner.");
        page.addView(hint, Ui.matchWrap());

        setContentView(scroll);
        paintPage();
    }

    private void paintPage() {
        int[] c = NoteColors.of(this, color);
        scroll.setBackgroundColor(c[0]);
        getWindow().setStatusBarColor(c[0]);
        title.setTextColor(c[1]);
        title.setHintTextColor(NoteColors.fade(c[1], 0x77));
        if (body != null) {
            body.setTextColor(c[1]);
            body.setHintTextColor(NoteColors.fade(c[1], 0x77));
        }
        if (newItem != null) {
            newItem.setTextColor(c[1]);
            newItem.setHintTextColor(NoteColors.fade(c[1], 0x99));
        }
        if (itemsBox != null) renderItems();
    }

    private void renderItems() {
        int ink = NoteColors.of(this, color)[1];
        itemsBox.removeAllViews();
        // Open items first, then checked ones (as in the planner).
        for (int pass = 0; pass < 2; pass++) {
            for (int i = 0; i < items.length(); i++) {
                final JSONObject it = items.optJSONObject(i);
                if (it == null || it.optBoolean("done") != (pass == 1)) continue;
                LinearLayout row = new LinearLayout(this);
                row.setGravity(Gravity.CENTER_VERTICAL);
                CheckBox box = new CheckBox(this);
                box.setChecked(it.optBoolean("done"));
                box.setOnCheckedChangeListener((b, on) -> {
                    try { it.put("done", on); } catch (Exception ignored) { /* our data */ }
                    renderItems();
                });
                EditText text = new EditText(this);
                text.setText(it.optString("text", ""));
                text.setTextColor(on(it) ? NoteColors.fade(ink, 0x88) : ink);
                text.setBackground(null);
                text.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
                if (on(it)) text.setPaintFlags(text.getPaintFlags() | Paint.STRIKE_THRU_TEXT_FLAG);
                text.addTextChangedListener(new TextWatcher() {
                    @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) {}
                    @Override public void onTextChanged(CharSequence s, int a, int b, int c) {}
                    @Override public void afterTextChanged(Editable s) {
                        try { it.put("text", s.toString()); } catch (Exception ignored) { /* our data */ }
                    }
                });
                ImageButton del = new ImageButton(this);
                del.setImageResource(android.R.drawable.ic_menu_close_clear_cancel);
                del.setBackground(null);
                del.setContentDescription("Remove item");
                del.setOnClickListener(v -> {
                    JSONArray next = new JSONArray();
                    for (int k = 0; k < items.length(); k++) if (items.opt(k) != it) next.put(items.opt(k));
                    items = next;
                    renderItems();
                });
                row.addView(box);
                row.addView(text, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
                row.addView(del);
                itemsBox.addView(row, Ui.matchWrap());
            }
            if (pass == 0) {
                View spacer = new View(this);
                itemsBox.addView(spacer, new LinearLayout.LayoutParams(1, Ui.dp(this, 6)));
            }
        }
    }

    private static boolean on(JSONObject it) {
        return it.optBoolean("done");
    }

    private void addItems(String text) {
        for (String p : Ui.itemsFrom(text)) {
            try {
                JSONObject it = new JSONObject();
                it.put("id", Store.newItemId());
                it.put("text", p);
                it.put("done", false);
                items.put(it);
            } catch (Exception ignored) {
                // our data
            }
        }
        renderItems();
    }

    /** Sends only what changed, so edits made elsewhere to other fields survive. */
    private void save() {
        if (original == null) return;
        try {
            JSONObject fields = new JSONObject();
            String t = title.getText().toString().trim();
            if (!t.equals(original.optString("title", ""))) fields.put("title", t);
            if (!color.equals(original.optString("color", "yellow"))) fields.put("color", color);
            if (isChecklist) {
                JSONArray before = original.optJSONArray("items");
                if (!items.toString().equals(before == null ? "[]" : before.toString())) fields.put("items", items);
            } else {
                String b = body.getText().toString();
                if (!b.equals(original.optString("body", ""))) fields.put("body", b);
            }
            if (fields.length() == 0) return;
            Store.patchNote(this, noteId, fields);
            original = Store.note(this, noteId);
            if (original != null) original = new JSONObject(original.toString());
            NotesWidgetProvider.showLocal(getApplicationContext());
            SyncJobService.syncSoon(getApplicationContext());
        } catch (Exception ignored) {
            // nothing to save
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        save();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != Ui.REQ_SPEECH || resultCode != RESULT_OK) return;
        String said = Ui.heard(data);
        if (said.isEmpty()) return;
        if (isChecklist) {
            addItems(said);
        } else {
            String cur = body.getText().toString();
            String add = Ui.spoken(said);
            if (!add.isEmpty()) add = Character.toUpperCase(add.charAt(0)) + add.substring(1);
            body.setText(cur.isEmpty() ? add : cur + (cur.endsWith("\n") || cur.endsWith(" ") ? "" : " ") + add);
            body.setSelection(body.getText().length());
        }
    }
}
