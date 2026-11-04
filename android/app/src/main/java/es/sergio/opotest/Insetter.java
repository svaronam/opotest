package es.sergio.opotest;

import android.annotation.TargetApi;
import android.graphics.Insets;
import android.view.View;
import android.view.WindowInsets;

/** Reserva espacio para la barra de estado, la de navegación y el teclado (Android 11+). */
@TargetApi(30)
final class Insetter {
    static void apply(View root) {
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            Insets s = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            v.setPadding(s.left, s.top, s.right, s.bottom);
            return WindowInsets.CONSUMED;
        });
    }
}
