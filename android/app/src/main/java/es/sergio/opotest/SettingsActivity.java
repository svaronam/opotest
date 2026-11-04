package es.sergio.opotest;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import org.json.JSONObject;

public class SettingsActivity extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_settings);
        if (android.os.Build.VERSION.SDK_INT >= 30) Insetter.apply(findViewById(android.R.id.content));
        EditText url = findViewById(R.id.url);
        EditText token = findViewById(R.id.token);
        TextView status = findViewById(R.id.status);
        url.setText(Prefs.configured(this) ? Prefs.url(this) : Prefs.DEFAULT_URL);
        token.setText(Prefs.token(this));

        Button test = findViewById(R.id.test);
        test.setOnClickListener(v -> {
            Prefs.save(this, normalize(url.getText().toString()), token.getText().toString());
            status.setText("Probando…");
            new Thread(() -> {
                String msg;
                try {
                    JSONObject r = new JSONObject(Poller.get(this, "/api/health"));
                    msg = r.optBoolean("ok") ? "Conectado. Servidor OpoTest " + r.optString("version") : "Respuesta inesperada";
                } catch (Exception e) {
                    msg = "No responde: " + e.getMessage() + ". ¿Tailscale activo?";
                }
                String m = msg;
                runOnUiThread(() -> status.setText(m));
            }).start();
        });
        findViewById(R.id.save).setOnClickListener(v -> {
            Prefs.save(this, normalize(url.getText().toString()), token.getText().toString());
            startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NEW_TASK));
            finish();
        });
    }

    private static String normalize(String u) {
        u = u.trim();
        if (!u.isEmpty() && !u.startsWith("http")) u = "http://" + u;
        if (u.matches("^https?://[^/:]+$")) u = u + ":8790";
        return u;
    }
}
