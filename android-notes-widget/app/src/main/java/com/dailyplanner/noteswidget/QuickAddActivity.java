package com.dailyplanner.noteswidget;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The widget's quick-add box, floating over the home screen.
 *   * From "+": a new note (title, text or one item per line, colour).
 *   * From a card's "+ Add item": new items for that checklist; Enter adds
 *     one and keeps the box open for the next.
 * Saved on the phone at once; sent to the planner in the background.
 */
public class QuickAddActivity extends Activity {
    private String noteId;
    private EditText title, body, item;
    private CheckBox checklist;
    private TextView added;
    private String color = "yellow";
    private int addedCount = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        noteId = getIntent().getStringExtra(ActionActivity.EXTRA_NOTE);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = Ui.dp(this, 18);
        root.setPadding(pad, pad, pad, Ui.dp(this, 10));

        TextView heading = new TextView(this);
        heading.setTextSize(19);
        heading.setTypeface(heading.getTypeface(), android.graphics.Typeface.BOLD);
        root.addView(heading, Ui.matchWrap());

        JSONObject target = noteId == null ? null : Store.note(this, noteId);
        if (noteId != null && target == null) {
            finish();
            return;
        }

        LinearLayout inputRow = new LinearLayout(this);
        inputRow.setOrientation(LinearLayout.HORIZONTAL);
        inputRow.setGravity(Gravity.CENTER_VERTICAL);

        ImageButton mic = new ImageButton(this);
        mic.setImageResource(android.R.drawable.ic_btn_speak_now);
        mic.setContentDescription("Speak");
        mic.setOnClickListener(v -> Ui.listen(this));

        if (target != null) {
            String t = target.optString("title", "").trim();
            heading.setText("Add to " + (t.isEmpty() ? "checklist" : t));
            item = new EditText(this);
            item.setHint("New item");
            item.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            item.setImeOptions(EditorInfo.IME_ACTION_DONE);
            item.setOnEditorActionListener((v, actionId, ev) -> {
                boolean enter = actionId == EditorInfo.IME_ACTION_DONE
                        || (ev != null && ev.getKeyCode() == KeyEvent.KEYCODE_ENTER && ev.getAction() == KeyEvent.ACTION_DOWN);
                if (enter) {
                    addItems(item.getText().toString());
                    return true;
                }
                return false;
            });
            inputRow.addView(item, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            inputRow.addView(mic);
            root.addView(inputRow, Ui.matchWrap());
            added = new TextView(this);
            added.setTextSize(13);
            added.setAlpha(0.75f);
            root.addView(added, Ui.matchWrap());
            item.requestFocus();
        } else {
            heading.setText("New note");
            title = new EditText(this);
            title.setHint("Title");
            title.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            root.addView(title, Ui.matchWrap());
            body = new EditText(this);
            body.setHint("Note, or one item per line for a checklist");
            body.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            body.setMinLines(3);
            body.setGravity(Gravity.TOP);
            inputRow.addView(body, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            inputRow.addView(mic);
            root.addView(inputRow, Ui.matchWrap());
            checklist = new CheckBox(this);
            checklist.setText("Checklist (each line is an item)");
            root.addView(checklist, Ui.matchWrap());
            LinearLayout colors = Ui.colorRow(this, color, name -> color = name);
            colors.setPadding(0, Ui.dp(this, 8), 0, Ui.dp(this, 4));
            root.addView(colors, Ui.matchWrap());
            body.requestFocus();
        }

        LinearLayout buttons = new LinearLayout(this);
        buttons.setGravity(Gravity.END);
        Button cancel = new Button(this, null, android.R.attr.buttonBarButtonStyle);
        cancel.setText(target != null ? "Close" : "Cancel");
        cancel.setOnClickListener(v -> finish());
        Button save = new Button(this, null, android.R.attr.buttonBarButtonStyle);
        save.setText(target != null ? "Add" : "Save");
        save.setOnClickListener(v -> {
            if (target != null) {
                addItems(item.getText().toString());
                if (addedCount > 0 && item.getText().length() == 0) finish();
            } else if (saveNote()) {
                finish();
            }
        });
        buttons.addView(cancel);
        buttons.addView(save);
        root.addView(buttons, Ui.matchWrap());

        setContentView(root);
        getWindow().setLayout(Math.min(getResources().getDisplayMetrics().widthPixels - Ui.dp(this, 24), Ui.dp(this, 520)),
                WindowManager.LayoutParams.WRAP_CONTENT);
    }

    private void addItems(String text) {
        String[] parts = Ui.itemsFrom(text);
        if (parts.length == 0) return;
        JSONObject n = Store.note(this, noteId);
        if (n == null) return;
        try {
            JSONArray items = n.optJSONArray("items");
            JSONArray next = new JSONArray(items == null ? "[]" : items.toString());
            for (String p : parts) {
                JSONObject it = new JSONObject();
                it.put("id", Store.newItemId());
                it.put("text", p);
                it.put("done", false);
                next.put(it);
            }
            JSONObject fields = new JSONObject();
            fields.put("items", next);
            if (!"checklist".equals(n.optString("kind"))) fields.put("kind", "checklist");
            Store.patchNote(this, noteId, fields);
        } catch (Exception e) {
            return;
        }
        addedCount += parts.length;
        item.setText("");
        added.setText("Added: " + String.join(", ", parts) + "  ·  " + addedCount + " so far");
        changed();
    }

    private boolean saveNote() {
        String t = title.getText().toString().trim();
        String b = body.getText().toString();
        if (t.isEmpty() && b.trim().isEmpty()) {
            body.setError("Write something first");
            return false;
        }
        try {
            JSONObject fields = new JSONObject();
            fields.put("title", t);
            fields.put("color", color);
            if (checklist.isChecked()) {
                JSONArray items = new JSONArray();
                for (String p : Ui.itemsFrom(b)) {
                    JSONObject it = new JSONObject();
                    it.put("id", Store.newItemId());
                    it.put("text", p);
                    it.put("done", false);
                    items.put(it);
                }
                fields.put("kind", "checklist");
                fields.put("items", items);
                fields.put("body", "");
            } else {
                fields.put("kind", "text");
                fields.put("body", b.trim());
                fields.put("items", new JSONArray());
            }
            Store.createNote(this, fields);
        } catch (Exception e) {
            return false;
        }
        changed();
        return true;
    }

    private void changed() {
        NotesWidgetProvider.showLocal(getApplicationContext());
        SyncJobService.syncSoon(getApplicationContext());
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != Ui.REQ_SPEECH || resultCode != RESULT_OK) return;
        String said = Ui.heard(data);
        if (said.isEmpty()) return;
        if (item != null) {
            addItems(said);
        } else if (body != null) {
            String cur = body.getText().toString();
            String add = Ui.spoken(said);
            if (!add.isEmpty()) add = Character.toUpperCase(add.charAt(0)) + add.substring(1);
            body.setText(cur.isEmpty() ? add : cur + (cur.endsWith("\n") ? "" : (checklist.isChecked() ? "\n" : " ")) + add);
            body.setSelection(body.getText().length());
        }
    }
}
