package es.sergio.opotest;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Pregunta a la Raspberry si hay avisos nuevos y los muestra como notificaciones. */
final class Poller {
    static final String CHANNEL = "avisos";
    static final int JOB_ID = 4711;

    static void ensureChannel(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Avisos de estudio", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Preguntas nuevas, falladas por repasar y mínimo diario");
            nm.createNotificationChannel(ch);
        }
    }

    static void schedule(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(c, PollService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true)
                .build();
        js.schedule(job);
    }

    static String get(Context c, String path) throws Exception {
        URL u = new URL(Prefs.url(c) + path);
        HttpURLConnection con = (HttpURLConnection) u.openConnection();
        con.setConnectTimeout(10000);
        con.setReadTimeout(15000);
        String tok = Prefs.token(c);
        if (!tok.isEmpty()) con.setRequestProperty("X-Token", tok);
        int code = con.getResponseCode();
        InputStream in = code < 400 ? con.getInputStream() : con.getErrorStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while (in != null && (n = in.read(buf)) > 0) out.write(buf, 0, n);
        con.disconnect();
        if (code >= 400) throw new Exception("HTTP " + code);
        return out.toString("UTF-8");
    }

    /** Devuelve el número de avisos mostrados. */
    static synchronized int poll(Context c) {
        if (!Prefs.configured(c)) return 0;
        try {
            long since = Prefs.lastNotif(c);
            if (since < 0) {            // primera vez: no enseñar avisos antiguos
                JSONObject r = new JSONObject(get(c, "/api/notifications?since=-1"));
                Prefs.setLastNotif(c, r.optLong("last_id", 0));
                return 0;
            }
            JSONObject r = new JSONObject(get(c, "/api/notifications?since=" + since));
            JSONArray items = r.optJSONArray("items");
            if (items == null) return 0;
            ensureChannel(c);
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            long last = since;
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.getJSONObject(i);
                long id = it.getLong("id");
                last = Math.max(last, id);
                Intent open = new Intent(c, MainActivity.class)
                        .putExtra("link", it.optString("link", "#/"))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                PendingIntent pi = PendingIntent.getActivity(c, (int) id, open,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                String kind = it.optString("kind", "aviso");
                Notification n = new Notification.Builder(c, CHANNEL)
                        .setSmallIcon(R.drawable.ic_stat_opotest)
                        .setColor(0xFF1C2B4A)
                        .setContentTitle(it.optString("title"))
                        .setContentText(it.optString("body"))
                        .setStyle(new Notification.BigTextStyle().bigText(it.optString("body")))
                        .setContentIntent(pi)
                        .setAutoCancel(true)
                        .build();
                // un aviso por tipo: el de "repaso" de hoy sustituye al de ayer
                nm.notify(kind.hashCode(), n);
            }
            Prefs.setLastNotif(c, last);
            return items.length();
        } catch (Exception e) {
            return 0;   // sin Tailscale o Pi apagada: se reintenta en el siguiente ciclo
        }
    }
}
