package com.dailyplanner.noteswidget;

import android.content.Context;
import android.content.res.Configuration;

/** The same nine colours as the Color Notes page, light and dark. */
final class NoteColors {
    private NoteColors() {}

    static boolean dark(Context c) {
        int mode = c.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return mode == Configuration.UI_MODE_NIGHT_YES;
    }

    /** {background, text} for a colour name. */
    static int[] of(Context c, String name) {
        boolean d = dark(c);
        switch (name == null ? "" : name) {
            case "red":    return d ? pair(0xFF48201D, 0xFFFFE3DF) : pair(0xFFFFDCD8, 0xFF3A1310);
            case "orange": return d ? pair(0xFF48301A, 0xFFFFE8CF) : pair(0xFFFFE3C4, 0xFF3B230B);
            case "green":  return d ? pair(0xFF1D3A24, 0xFFDAF6DE) : pair(0xFFD5F3D8, 0xFF0F2E17);
            case "blue":   return d ? pair(0xFF1C3049, 0xFFDCE9FF) : pair(0xFFD6E8FF, 0xFF0E2442);
            case "purple": return d ? pair(0xFF31264A, 0xFFECE2FF) : pair(0xFFE8DCFF, 0xFF26124A);
            case "black":  return pair(0xFF26272C, 0xFFF3F3F0);
            case "gray":   return d ? pair(0xFF303137, 0xFFECECEA) : pair(0xFFE6E6E2, 0xFF1F2024);
            case "white":  return d ? pair(0xFF2A2B31, 0xFFF2F2EF) : pair(0xFFFFFFFF, 0xFF15161A);
            case "yellow":
            default:       return d ? pair(0xFF463D16, 0xFFFFF4C2) : pair(0xFFFFF2AD, 0xFF352B04);
        }
    }

    private static int[] pair(int bg, int ink) {
        return new int[] {bg, ink};
    }

    /** ink at a given alpha (0..255). */
    static int fade(int color, int alpha) {
        return (color & 0x00FFFFFF) | (alpha << 24);
    }
}
