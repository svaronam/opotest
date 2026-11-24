package es.sergio.opotest;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

public class MainActivity extends Activity {
    private WebView web;
    private FrameLayout root;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable foregroundPoll = new Runnable() {
        @Override public void run() {
            new Thread(() -> Poller.poll(getApplicationContext())).start();
            handler.postDelayed(this, 60_000);
        }
    };

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        if (!Prefs.configured(this)) {
            startActivity(new Intent(this, SettingsActivity.class));
            finish();
            return;
        }
        root = new FrameLayout(this);
        web = new WebView(this);
        root.addView(web);
        setContentView(root);
        // Android 15 dibuja bajo las barras del sistema: dejamos hueco para ellas y para el teclado
        if (Build.VERSION.SDK_INT >= 30) Insetter.apply(root);
        // Colores de las barras del sistema: los últimos que pidió la web, para que no parpadee al abrir
        applyBars(Prefs.sp(this).getInt("bar_color", 0xFFEEF1F6), Prefs.sp(this).getBoolean("bar_dark", false));

        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(true);
        ws.setUserAgentString(ws.getUserAgentString() + " OpoTestApp/1.0");
        web.addJavascriptInterface(new Bridge(), "Android");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                Uri u = req.getUrl();
                Uri base = Uri.parse(Prefs.url(MainActivity.this));
                String path = u.getPath() == null ? "" : u.getPath();
                if (u.getHost() != null && u.getHost().equals(base.getHost()) && !path.endsWith("/pdf")) return false;
                openExternal(u.toString());
                return true;
            }
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) showOffline(err.getDescription().toString());
            }
        });
        Poller.ensureChannel(this);
        Poller.schedule(this);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        web.loadUrl(Prefs.url(this) + "/" + linkFrom(getIntent()));
    }

    private String linkFrom(Intent i) {
        String l = i != null ? i.getStringExtra("link") : null;
        return (l != null && l.startsWith("#")) ? l : "";
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String l = linkFrom(intent);
        if (web != null && !l.isEmpty()) web.evaluateJavascript("location.hash=" + org.json.JSONObject.quote(l), null);
    }

    private void showOffline(String why) {
        String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                + "<body style='font-family:sans-serif;background:#eef1f6;color:#1c2b4a;padding:32px 24px'>"
                + "<h2>No se puede conectar con la Raspberry</h2>"
                + "<p>Comprueba que Tailscale está activo en el móvil y que homelab2 está encendida.</p>"
                + "<p style='color:#7c88a3;font-size:14px'>" + android.text.Html.escapeHtml(why) + "</p>"
                + "<p><button style='padding:12px 20px;border-radius:24px;border:0;background:#1c2b4a;color:#fff;font-size:16px' onclick='Android.reload()'>Reintentar</button></p>"
                + "<p><button style='padding:12px 20px;border-radius:24px;border:1.5px solid #1c2b4a;background:none;font-size:16px' onclick='Android.openSettings()'>Cambiar servidor</button></p></body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void openExternal(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (Exception ignored) { }
    }

    @Override protected void onResume() { super.onResume(); handler.post(foregroundPoll); }
    @Override protected void onPause() {
        super.onPause();
        handler.removeCallbacks(foregroundPoll);
        OpoWidget.refreshAsync(this);      // el widget refleja lo que acabas de hacer
    }

    @Override
    public void onBackPressed() {
        if (web == null) { super.onBackPressed(); return; }
        // Si hay un test a medias, la web pregunta antes de salir
        web.evaluateJavascript("(window.opoBack && window.opoBack()) ? 'yes' : 'no'", v -> {
            if (v != null && v.contains("yes")) return;
            if (web.canGoBack()) web.goBack();
            else finish();
        });
    }

    /** Pinta la barra de estado y la de navegación del color de fondo de la web. */
    private void applyBars(int color, boolean dark) {
        if (root != null) root.setBackgroundColor(color);
        if (web != null) web.setBackgroundColor(color);
        getWindow().setStatusBarColor(color);
        getWindow().setNavigationBarColor(color);
        if (Build.VERSION.SDK_INT >= 30) {
            android.view.WindowInsetsController ic = getWindow().getInsetsController();
            int light = android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                    | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            if (ic != null) ic.setSystemBarsAppearance(dark ? 0 : light, light);
        } else {
            android.view.View d = getWindow().getDecorView();
            int f = d.getSystemUiVisibility();
            int light = android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            d.setSystemUiVisibility(dark ? (f & ~light) : (f | light));
        }
    }

    final class Bridge {
        @JavascriptInterface public void setBars(String hex, boolean dark) {
            final int c;
            try { c = android.graphics.Color.parseColor(hex.trim()); } catch (Exception e) { return; }
            Prefs.sp(MainActivity.this).edit().putInt("bar_color", c).putBoolean("bar_dark", dark).apply();
            runOnUiThread(() -> applyBars(c, dark));
        }
        @JavascriptInterface public void openSettings() {
            startActivity(new Intent(MainActivity.this, SettingsActivity.class));
        }
        @JavascriptInterface public void checkNow() {
            new Thread(() -> Poller.poll(getApplicationContext())).start();
        }
        @JavascriptInterface public void openExternal(String url) { MainActivity.this.openExternal(url); }
        @JavascriptInterface public void reload() {
            runOnUiThread(() -> web.loadUrl(Prefs.url(MainActivity.this) + "/"));
        }
        @JavascriptInterface public String version() { return "1.1.1"; }
    }
}
