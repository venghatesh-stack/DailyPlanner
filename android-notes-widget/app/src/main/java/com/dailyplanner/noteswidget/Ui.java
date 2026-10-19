package com.dailyplanner.noteswidget;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.graphics.drawable.GradientDrawable;
import android.speech.RecognizerIntent;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.Toast;

import java.util.ArrayList;

/** Small shared pieces for the note editor and the quick-add box. */
final class Ui {
    static final String[] COLORS = {"red", "orange", "yellow", "green", "blue", "purple", "black", "gray", "white"};
    static final int REQ_SPEECH = 77;

    private Ui() {}

    static int dp(Context c, float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, c.getResources().getDisplayMetrics()));
    }

    interface ColorPicked { void picked(String name); }

    /** A row of nine colour dots; the chosen one gets a ring. */
    static LinearLayout colorRow(Context c, String selected, ColorPicked cb) {
        LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.HORIZONTAL);
        int size = dp(c, 30), gap = dp(c, 6);
        View[] dots = new View[COLORS.length];
        for (int i = 0; i < COLORS.length; i++) {
            final String name = COLORS[i];
            View dot = new View(c);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(size, size);
            lp.setMarginEnd(gap);
            dot.setLayoutParams(lp);
            dot.setContentDescription(name + " colour");
            dots[i] = dot;
            dot.setOnClickListener(v -> {
                for (int j = 0; j < dots.length; j++) paintDot(c, dots[j], COLORS[j], COLORS[j].equals(name));
                cb.picked(name);
            });
            row.addView(dot);
        }
        for (int j = 0; j < dots.length; j++) paintDot(c, dots[j], COLORS[j], COLORS[j].equals(selected));
        return row;
    }

    private static void paintDot(Context c, View dot, String name, boolean on) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        int[] pair = NoteColors.of(c, name);
        g.setColor(swatch(name, pair[0]));
        g.setStroke(dp(c, on ? 3 : 1), on ? 0xFF3A3DD0 : 0x55000000);
        dot.setBackground(g);
    }

    private static int swatch(String name, int bg) {
        switch (name) {
            case "red": return 0xFFE5534B;
            case "orange": return 0xFFEE8A2B;
            case "yellow": return 0xFFE2BD1F;
            case "green": return 0xFF3A9F57;
            case "blue": return 0xFF3A7FE0;
            case "purple": return 0xFF8656EF;
            case "black": return 0xFF26272C;
            case "gray": return 0xFF8B8D94;
            default: return 0xFFFFFFFF;
        }
    }

    /** Opens the phone's speech recogniser; the result arrives in onActivityResult. */
    static void listen(Activity a) {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak your note")
                .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        try {
            a.startActivityForResult(i, REQ_SPEECH);
        } catch (ActivityNotFoundException e) {
            Toast.makeText(a, "Voice typing isn't available. Use the mic on your keyboard.", Toast.LENGTH_LONG).show();
        }
    }

    static String heard(Intent data) {
        if (data == null) return "";
        ArrayList<String> r = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
        return r == null || r.isEmpty() ? "" : r.get(0);
    }

    /** "comma", "full stop", "new line"... spoken -> written. */
    static String spoken(String t) {
        return t.replaceAll("(?i)\\s*\\bnew paragraph\\b\\s*", "\n\n")
                .replaceAll("(?i)\\s*\\b(new line|next line)\\b\\s*", "\n")
                .replaceAll("(?i)\\s*\\b(full stop|period)\\b", ".")
                .replaceAll("(?i)\\s*\\bcomma\\b", ",")
                .replaceAll("(?i)\\s*\\bquestion mark\\b", "?")
                .trim();
    }

    /** Spoken or typed lines -> separate checklist items ("next item" also splits). */
    static String[] itemsFrom(String t) {
        String[] parts = spoken(t).split("\\n+|(?i)\\s*\\bnext item\\b\\s*");
        ArrayList<String> out = new ArrayList<>();
        for (String p : parts) {
            String s = p.replaceAll("^[\\s,.]+|[\\s,.]+$", "");
            if (!s.isEmpty()) out.add(Character.toUpperCase(s.charAt(0)) + s.substring(1));
        }
        return out.toArray(new String[0]);
    }

    static ViewGroup.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }
}
