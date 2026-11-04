package es.sergio.opotest;

import android.content.Context;
import android.content.SharedPreferences;

final class Prefs {
    static final String DEFAULT_URL = "http://homelab2:8790";

    static SharedPreferences sp(Context c) {
        return c.getSharedPreferences("opotest", Context.MODE_PRIVATE);
    }
    static String url(Context c) {
        String u = sp(c).getString("url", "");
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }
    static boolean configured(Context c) { return !url(c).isEmpty(); }
    static String token(Context c) { return sp(c).getString("token", ""); }
    static long lastNotif(Context c) { return sp(c).getLong("last_notif", -1); }
    static void setLastNotif(Context c, long id) { sp(c).edit().putLong("last_notif", id).apply(); }
    static void save(Context c, String url, String token) {
        sp(c).edit().putString("url", url.trim()).putString("token", token.trim()).putLong("last_notif", -1).apply();
    }
}
