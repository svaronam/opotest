package es.sergio.opotest;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.view.View;
import android.widget.RemoteViews;

import org.json.JSONObject;

/** Widget de la pantalla de inicio: progreso del día y acceso directo al modo 5 minutos. */
public class OpoWidget extends AppWidgetProvider {

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        final PendingResult pr = goAsync();
        final Context app = c.getApplicationContext();
        draw(app, null);                    // pinta enseguida con lo último guardado
        new Thread(() -> {
            try { refresh(app); } finally { pr.finish(); }
        }).start();
    }

    @Override
    public void onEnabled(Context c) { Poller.schedule(c); }

    /** Pide los datos a la Raspberry y repinta. Se llama también desde el aviso periódico y al salir de la app. */
    static void refresh(Context c) {
        if (!Prefs.configured(c) || ids(c).length == 0) return;
        try {
            String json = Poller.get(c, "/api/widget");
            Prefs.sp(c).edit().putString("widget_json", json).putLong("widget_at", System.currentTimeMillis()).apply();
            draw(c, new JSONObject(json));
        } catch (Exception e) {
            draw(c, null);
        }
    }

    static void refreshAsync(Context c) {
        final Context app = c.getApplicationContext();
        new Thread(() -> refresh(app)).start();
    }

    private static int[] ids(Context c) {
        return AppWidgetManager.getInstance(c).getAppWidgetIds(new ComponentName(c, OpoWidget.class));
    }

    private static PendingIntent open(Context c, String link, int req) {
        Intent i = new Intent(c, MainActivity.class)
                .putExtra("link", link)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(c, 9000 + req, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static void draw(Context c, JSONObject d) {
        if (d == null) {
            try {
                String s = Prefs.sp(c).getString("widget_json", null);
                if (s != null) d = new JSONObject(s);
            } catch (Exception ignored) { }
        }
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_opotest);
        if (d != null) {
            int done = d.optInt("answered"), goal = Math.max(1, d.optInt("goal", 50));
            int rev = d.optInt("review_due"), fichas = d.optInt("fichas_due"), streak = d.optInt("streak");
            v.setTextViewText(R.id.w_count, done + " / " + goal);
            v.setTextViewText(R.id.w_sub, done >= goal ? "Mínimo cumplido" + (streak > 0 ? " · racha " + streak : "")
                    : "Faltan " + (goal - done) + (streak > 0 ? " · racha " + streak : ""));
            v.setProgressBar(R.id.w_bar, goal, Math.min(done, goal), false);
            String pend = rev + (rev == 1 ? " fallada" : " falladas") + " · " + fichas + (fichas == 1 ? " ficha" : " fichas");
            v.setTextViewText(R.id.w_pend, pend);
            boolean open = d.optBoolean("open_test");
            v.setTextViewText(R.id.w_rep, open ? "Seguir test" : "Repaso");
            v.setOnClickPendingIntent(R.id.w_rep, open(c, open ? "#/" : (rev > 0 ? "#/test/repaso" : "#/fichas"), 2));
        } else {
            v.setTextViewText(R.id.w_count, "OpoTest");
            v.setTextViewText(R.id.w_sub, "Sin conexión con la Raspberry");
            v.setTextViewText(R.id.w_pend, "");
            v.setViewVisibility(R.id.w_bar, View.INVISIBLE);
            v.setOnClickPendingIntent(R.id.w_rep, open(c, "#/test/repaso", 2));
        }
        v.setOnClickPendingIntent(R.id.w_five, open(c, "#/test/5min", 1));
        v.setOnClickPendingIntent(R.id.w_root, open(c, "#/", 0));
        AppWidgetManager.getInstance(c).updateAppWidget(ids(c), v);
    }
}
