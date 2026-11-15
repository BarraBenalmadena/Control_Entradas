package es.benalmadena.controlentradas;

import android.Manifest;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import com.google.common.util.concurrent.ListenableFuture;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.barcode.BarcodeScanner;
import com.google.mlkit.vision.barcode.BarcodeScannerOptions;
import com.google.mlkit.vision.barcode.BarcodeScanning;
import com.google.mlkit.vision.common.InputImage;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.ArrayList;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public class MainActivity extends AppCompatActivity {
    private static final String PREFS = "control_entradas_v01";
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean analyzing = new AtomicBoolean(false);
    private EditText serverInput, pinInput;
    private TextView statusView, connectionView, counterView, queueView;
    private Spinner eventSpinner;
    private PreviewView cameraView;
    private CheckBox emergencyMode;
    private SharedPreferences prefs;
    private JSONArray events = new JSONArray();
    private ArrayList<String> eventIds = new ArrayList<>();
    private String publicKey = "", deviceId = "";
    private BarcodeScanner scanner;
    private ProcessCameraProvider cameraProvider;
    private long lastScanMs = 0L;
    private String lastScan = "";
    private boolean scannerStarted = false;
    private ActivityResultLauncher<String> permissionLauncher;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        publicKey = prefs.getString("pubkey", "");
        deviceId = prefs.getString("device", "");
        if (deviceId.isEmpty()) {
            deviceId = UUID.randomUUID().toString();
            prefs.edit().putString("device", deviceId).apply();
        }
        permissionLauncher = registerForActivityResult(new ActivityResultContracts.RequestPermission(), allowed -> {
            if (allowed) startScanner(); else showResult("PERMISO DE CÁMARA DENEGADO", Color.RED);
        });
        BarcodeScannerOptions options = new BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build();
        scanner = BarcodeScanning.getClient(options);
        createUi();
        try { setEvents(new JSONArray(prefs.getString("events", "[]"))); }
        catch (Exception ignored) { }
    }

    private int dp(int v) { return (int)(getResources().getDisplayMetrics().density * v + 0.5f); }
    private TextView text(String content, int size, boolean bold) {
        TextView t = new TextView(this);
        t.setText(content);
        t.setTextSize(size);
        t.setTextColor(Color.rgb(17, 44, 65));
        if (bold) t.setTypeface(null, android.graphics.Typeface.BOLD);
        t.setPadding(0, dp(6), 0, dp(6));
        return t;
    }
    private Button button(String label) {
        Button b = new Button(this);
        b.setAllCaps(false);
        b.setText(label);
        return b;
    }
    private void createUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(244, 248, 251));
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(18), dp(18), dp(18), dp(26));
        scroll.addView(layout);
        setContentView(scroll);
        layout.addView(text("CONTROL DE ENTRADAS", 23, true));
        layout.addView(text("Escuela Municipal de Música y Danza · v0.1", 12, false));
        connectionView = text("Sin conexión · Vincula este móvil al servidor Windows", 13, true);
        layout.addView(connectionView);
        serverInput = new EditText(this);
        serverInput.setSingleLine(true);
        serverInput.setText(prefs.getString("server", "http://192.168.1.100:8765"));
        serverInput.setHint("http://IP-DEL-ORDENADOR:8765");
        layout.addView(text("Dirección del ordenador Windows", 13, true));
        layout.addView(serverInput);
        pinInput = new EditText(this);
        pinInput.setSingleLine(true);
        pinInput.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        pinInput.setText(prefs.getString("pin", ""));
        pinInput.setHint("PIN de 6 cifras");
        layout.addView(text("PIN mostrado en Windows", 13, true));
        layout.addView(pinInput);
        Button connect = button("Conectar / actualizar funciones");
        layout.addView(connect);
        connect.setOnClickListener(v -> connectServer());
        layout.addView(text("Función que se va a controlar", 13, true));
        eventSpinner = new Spinner(this);
        layout.addView(eventSpinner);
        Button camera = button("Iniciar escáner QR");
        layout.addView(camera);
        camera.setOnClickListener(v -> {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startScanner();
            else permissionLauncher.launch(Manifest.permission.CAMERA);
        });
        cameraView = new PreviewView(this);
        cameraView.setVisibility(View.GONE);
        layout.addView(cameraView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(240)));
        statusView = text("Listo para conectar", 21, true);
        statusView.setGravity(Gravity.CENTER);
        statusView.setPadding(dp(12), dp(18), dp(12), dp(18));
        statusView.setBackgroundColor(Color.rgb(225, 235, 243));
        layout.addView(statusView);
        counterView = text("", 14, false);
        counterView.setGravity(Gravity.CENTER);
        layout.addView(counterView);
        emergencyMode = new CheckBox(this);
        emergencyMode.setText("Contingencia sin red (solo UN móvil)");
        emergencyMode.setChecked(false);
        layout.addView(emergencyMode);
        emergencyMode.setOnCheckedChangeListener((view, checked) -> {
            if (checked) {
                emergencyMode.setChecked(false);
                new AlertDialog.Builder(this)
                    .setTitle("Modo de contingencia")
                    .setMessage("Solo puede utilizarse UN móvil lector. Apaga los demás lectores. Los accesos se guardarán en este dispositivo y se sincronizarán al recuperar la conexión. Si varios móviles lo usan a la vez, podrían aceptarse entradas duplicadas.")
                    .setNegativeButton("Cancelar", (d, w) -> {})
                    .setPositiveButton("Activar", (d, w) -> { emergencyMode.setOnCheckedChangeListener(null); emergencyMode.setChecked(true); emergencyMode.setOnCheckedChangeListener((v2, c2) -> { if(c2) showResult("CONTINGENCIA: USAR SOLO ESTE MÓVIL", Color.rgb(148, 89, 0)); }); showResult("CONTINGENCIA: USAR SOLO ESTE MÓVIL", Color.rgb(148, 89, 0)); })
                    .show();
            }
        });
        queueView = text("Pendientes sin red: 0", 12, false);
        layout.addView(queueView);
        Button sync = button("Sincronizar accesos pendientes");
        layout.addView(sync);
        sync.setOnClickListener(v -> syncPending());
        refreshPending();
    }

    private void setEvents(JSONArray rows) {
        events = rows;
        eventIds.clear();
        ArrayList<String> labels = new ArrayList<>();
        String previous = prefs.getString("last_event", "");
        int selected = 0;
        for (int i=0; i<rows.length(); i++) {
            JSONObject ev = rows.optJSONObject(i);
            if (ev == null) continue;
            String id = ev.optString("id");
            eventIds.add(id);
            labels.add(ev.optString("name") + " · " + ev.optString("start_time").replace('T',' ') + " · " + ev.optString("mode"));
            if (previous.equals(id)) selected = eventIds.size()-1;
        }
        if(labels.isEmpty()) labels.add("Sin funciones disponibles");
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels);
        eventSpinner.setAdapter(adapter);
        if(!eventIds.isEmpty()) eventSpinner.setSelection(selected);
        eventSpinner.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> parent, View view, int position, long id) {
                if(position < eventIds.size()) prefs.edit().putString("last_event", eventIds.get(position)).apply();
                refreshCounter();
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> parent) {}
        });
        refreshCounter();
    }
    private String currentEventId() {
        int index = eventSpinner.getSelectedItemPosition();
        return index >= 0 && index < eventIds.size() ? eventIds.get(index) : "";
    }
    private void refreshCounter() {
        int index = eventSpinner.getSelectedItemPosition();
        if(index<0 || index>=events.length()) { counterView.setText(""); return; }
        JSONObject ev = events.optJSONObject(index);
        if(ev != null) counterView.setText("Accesos confirmados al conectar: " + ev.optInt("used") + " / " + ev.optInt("issued"));
    }
    private void showResult(String message, int color) {
        statusView.setText(message);
        statusView.setTextColor(color == Color.RED ? Color.rgb(171,32,32) : color == Color.rgb(20,122,71) ? Color.rgb(20,122,71) : Color.rgb(130,82,0));
    }
    private String baseUrl() { return serverInput.getText().toString().trim().replaceAll("/+$", ""); }
    private String pin() { return pinInput.getText().toString().trim(); }
    private JSONObject request(String path, JSONObject payload) throws Exception {
        String base = baseUrl();
        if(!base.startsWith("http://") && !base.startsWith("https://")) throw new IllegalArgumentException("Dirección del servidor inválida");
        HttpURLConnection c = (HttpURLConnection)new URL(base + path).openConnection();
        try {
            c.setConnectTimeout(3000);
            c.setReadTimeout(4000);
            c.setRequestProperty("X-Access-Pin", pin());
            c.setRequestProperty("Accept", "application/json");
            if(payload != null) {
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] data = payload.toString().getBytes(StandardCharsets.UTF_8);
                try(OutputStream stream = c.getOutputStream()) { stream.write(data); }
            }
            int code = c.getResponseCode();
            InputStream stream = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if(stream == null) throw new Exception("Servidor sin respuesta");
            StringBuilder text = new StringBuilder();
            try(BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line; while((line=reader.readLine()) != null) text.append(line);
            }
            JSONObject response = new JSONObject(text.toString());
            if(code >= 400) throw new Exception(response.optString("error", "HTTP " + code));
            return response;
        } finally { c.disconnect(); }
    }
    private void connectServer() {
        connectionView.setText("Conectando...");
        String server = baseUrl(), p = pin();
        prefs.edit().putString("server", server).putString("pin", p).apply();
        executor.execute(() -> {
            try {
                JSONObject info = request("/api/status", null);
                String pk = info.getString("public_key");
                JSONArray list = info.getJSONArray("events");
                prefs.edit().putString("pubkey",pk).putString("events", list.toString()).apply();
                publicKey = pk;
                runOnUiThread(() -> { setEvents(list); connectionView.setText("CONECTADO · " + list.length() + " funciones"); showResult("LECTOR PREPARADO", Color.rgb(20,122,71)); });
                syncPendingInternal();
            } catch (Exception e) {
                runOnUiThread(() -> { connectionView.setText("SIN CONEXIÓN · " + e.getMessage()); showResult("NO CONECTADO",Color.RED); });
            }
        });
    }
    @androidx.camera.core.ExperimentalGetImage
    private void startScanner() {
        if(scannerStarted) { cameraView.setVisibility(View.VISIBLE); return; }
        scannerStarted = true;
        cameraView.setVisibility(View.VISIBLE);
        ListenableFuture<ProcessCameraProvider> provider = ProcessCameraProvider.getInstance(this);
        provider.addListener(() -> {
            try {
                cameraProvider = provider.get();
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(cameraView.getSurfaceProvider());
                ImageAnalysis analysis = new ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build();
                analysis.setAnalyzer(ContextCompat.getMainExecutor(this), image -> {
                    if (analyzing.get()) { image.close(); return; }
                    android.media.Image media = image.getImage();
                    if(media == null) { image.close(); return; }
                    InputImage input = InputImage.fromMediaImage(media, image.getImageInfo().getRotationDegrees());
                    scanner.process(input).addOnSuccessListener(barcodes -> {
                        for(Barcode barcode : barcodes) {
                            String raw = barcode.getRawValue();
                            if(raw != null && raw.startsWith("CE1.")) {
                                long now = SystemClock.elapsedRealtime();
                                if(raw.equals(lastScan) && now-lastScanMs<4000) break;
                                if(analyzing.compareAndSet(false,true)) {
                                    lastScan=raw; lastScanMs=now;
                                    processQr(raw);
                                }
                                break;
                            }
                        }
                    }).addOnCompleteListener(task -> image.close());
                });
                cameraProvider.unbindAll();
                cameraProvider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis);
                showResult("APUNTA AL CÓDIGO QR", Color.rgb(130,82,0));
            } catch(Exception e) { scannerStarted=false; showResult("ERROR DE CÁMARA: " + e.getMessage(),Color.RED); }
        }, ContextCompat.getMainExecutor(this));
    }
    private void processQr(String qr) {
        String event = currentEventId();
        if(event.isEmpty()) { showResult("SELECCIONA UNA FUNCIÓN",Color.RED); analyzing.set(false); return; }
        showResult("COMPROBANDO ENTRADA...",Color.rgb(130,82,0));
        executor.execute(() -> {
            try {
                JSONObject body = new JSONObject().put("qr",qr).put("event_id",event).put("device_id",deviceId);
                JSONObject response = request("/api/validate",body);
                String status = response.optString("status");
                String result = response.optString("message", status);
                if("valid".equals(status)) result += "\nN.º " + response.optInt("number") + (response.isNull("seat")? "" : "\n" + response.optString("seat"));
                String finalMessage = result;
                int color = "valid".equals(status) ? Color.rgb(20,122,71) : Color.RED;
                runOnUiThread(() -> showResult(finalMessage,color));
            } catch(Exception ex) {
                if(emergencyMode.isChecked() && ex instanceof java.io.IOException) offlineAccept(qr,event);
                else runOnUiThread(() -> showResult("SIN CONEXIÓN: NO VALIDADO\n"+ex.getMessage(),Color.RED));
            } finally {
                runOnUiThread(() -> analyzing.set(false));
            }
        });
    }
    private JSONObject verifyLocal(String qr) throws Exception {
        if(publicKey.isEmpty()) throw new Exception("Este móvil aún no está vinculado al ordenador");
        String[] parts = qr.split("\\.");
        if(parts.length != 3 || !parts[0].equals("CE1")) throw new Exception("Formato incorrecto");
        byte[] key = Base64.decode(publicKey,Base64.DEFAULT);
        PublicKey pub = KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(key));
        Signature verifier = Signature.getInstance("SHA256withECDSA");
        verifier.initVerify(pub);
        verifier.update(parts[1].getBytes(StandardCharsets.US_ASCII));
        if(!verifier.verify(Base64.decode(parts[2],Base64.URL_SAFE|Base64.NO_PADDING|Base64.NO_WRAP))) throw new Exception("Firma QR no válida");
        JSONObject data = new JSONObject(new String(Base64.decode(parts[1],Base64.URL_SAFE|Base64.NO_PADDING|Base64.NO_WRAP), StandardCharsets.UTF_8));
        if(data.optInt("v")!=1) throw new Exception("Formato no admitido");
        return data;
    }
    private void offlineAccept(String qr,String event) {
        try {
            JSONObject ticket = verifyLocal(qr);
            if(!ticket.optString("e").equals(event)) throw new Exception("Entrada de otra función");
            String ticketId = ticket.getString("id");
            String usedKey = "local_used_" + ticketId;
            if(prefs.getBoolean(usedKey,false)) throw new Exception("Entrada ya utilizada en este móvil");
            JSONArray pending = new JSONArray(prefs.getString("pending","[]"));
            pending.put(new JSONObject().put("qr",qr).put("event_id",event).put("device_id",deviceId));
            prefs.edit().putString("pending",pending.toString()).putBoolean(usedKey,true).commit();
            runOnUiThread(() -> { showResult("ACCESO PROVISIONAL SIN RED\nN.º "+ticket.optInt("n") + (ticket.isNull("s") ? "" : "\n" + ticket.optString("s")) + "\nSOLO ESTE MÓVIL",Color.rgb(130,82,0)); refreshPending(); });
        } catch(Exception ex) {
            runOnUiThread(() -> showResult("ENTRADA RECHAZADA\n"+ex.getMessage(),Color.RED));
        }
    }
    private void refreshPending() {
        try { queueView.setText("Accesos sin sincronizar: " + new JSONArray(prefs.getString("pending","[]")).length()); }
        catch(Exception ex) { queueView.setText("Registro pendiente no legible"); }
    }
    private void syncPending() { executor.execute(this::syncPendingInternal); }
    private void syncPendingInternal() {
        JSONArray pending;
        try { pending = new JSONArray(prefs.getString("pending","[]")); }
        catch(Exception e) { return; }
        if(pending.length()==0) { runOnUiThread(() -> showResult("NO HAY ACCESOS PENDIENTES",Color.rgb(20,122,71))); return; }
        JSONArray unsent = new JSONArray();
        int synced=0,conflicts=0;
        for(int i=0;i<pending.length();i++) {
            JSONObject item = pending.optJSONObject(i);
            if(item==null) continue;
            try {
                JSONObject res = request("/api/validate",item);
                if("valid".equals(res.optString("status"))) synced++;
                else conflicts++;
            } catch(Exception ex) { unsent.put(item); }
        }
        prefs.edit().putString("pending",unsent.toString()).apply();
        final int s=synced,c=conflicts,left=unsent.length();
        runOnUiThread(() -> { refreshPending(); showResult("SINCRONIZADOS: "+s+" · CONFLICTOS: "+c+" · PENDIENTES: "+left,c>0||left>0?Color.RED:Color.rgb(20,122,71)); });
    }
    @Override protected void onDestroy() {
        super.onDestroy();
        if(cameraProvider!=null) cameraProvider.unbindAll();
        scanner.close();
        executor.shutdownNow();
    }
}
