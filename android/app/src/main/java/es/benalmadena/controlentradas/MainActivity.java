package es.benalmadena.controlentradas;

import android.Manifest;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.content.Intent;
import android.net.Uri;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.speech.tts.TextToSpeech;
import java.util.Locale;
import android.os.Vibrator;
import android.os.VibrationEffect;
import android.os.Build;
import android.view.WindowManager;
import androidx.core.content.FileProvider;
import android.util.Size;
import java.io.File;
import java.io.FileOutputStream;

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
import com.google.mlkit.vision.barcode.ZoomSuggestionOptions;
import com.google.mlkit.vision.common.InputImage;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.security.MessageDigest;
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
    private final AtomicBoolean analyzing = new AtomicBoolean(false); // validación de acceso en curso
    private final AtomicBoolean frameBusy = new AtomicBoolean(false); // una imagen ML Kit a la vez
    private final ExecutorService cameraExecutor = Executors.newSingleThreadExecutor();
    private final ToneGenerator feedbackTone = new ToneGenerator(AudioManager.STREAM_ALARM, 95);
    private TextToSpeech voice;
    private boolean voiceReady = false;
    private boolean ttsEnabled = true;
    private boolean continuousEnabled = true;
    private String blockedQr = "";
    private long lastQrVisibleMs = 0L;
    private androidx.camera.core.Camera activeCamera;
    private float zoomRatio = 1.0f; // Campo de visión completo: detecta códigos en todo el encuadre
    private TextView zoomLabel;
    private long lastScannerErrorMs = 0L;

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
    private boolean scannerStarted = false;
    private ActivityResultLauncher<String> permissionLauncher;
    private ActivityResultLauncher<String[]> jsonImporter;
    private ActivityResultLauncher<String> auditExporter;
    private OfflineManager offline;
    private Spinner validationMode;
    private EditText rangeFrom, rangeTo, coordinatorIp, coordinatorPin;
    private TextView offlineStatus;
    private Button ticketListButton;
    private TextView availableListView,usedListView;
    private Spinner accessOrder;
    private EditText ticketSearch;
    private LinearLayout accessListPanel;
    private int validatedSession = 0;
    private Button coordinatorButton;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        ttsEnabled = prefs.getBoolean("tts_enabled",true);
        voice = new TextToSpeech(this, status -> {
            if(status == TextToSpeech.SUCCESS && voice != null){
                int result = voice.setLanguage(new Locale("es", "ES"));
                voiceReady = result != TextToSpeech.LANG_MISSING_DATA && result != TextToSpeech.LANG_NOT_SUPPORTED;
                voice.setSpeechRate(1.0f);
            }
        });
        publicKey = prefs.getString("pubkey", "");
        offline = new OfflineManager(this);
        deviceId = prefs.getString("device", "");
        if (deviceId.isEmpty()) {
            deviceId = UUID.randomUUID().toString();
            prefs.edit().putString("device", deviceId).apply();
        }
        permissionLauncher = registerForActivityResult(new ActivityResultContracts.RequestPermission(), allowed -> {
            if (allowed) startScanner(); else showResult("PERMISO DE CÁMARA DENEGADO", Color.RED);
        });
        auditExporter=registerForActivityResult(new ActivityResultContracts.CreateDocument("application/json"),uri->{
            if(uri==null)return;
            executor.execute(()->{
                try(OutputStream out=getContentResolver().openOutputStream(uri)){
                    if(out==null)throw new Exception("No se pudo guardar el archivo");
                    JSONObject report=offline.accessAudit(deviceId);
                    out.write(report.toString(2).getBytes(StandardCharsets.UTF_8));
                    out.flush();
                    runOnUiThread(()->showResult("REGISTRO DE ACCESOS EXPORTADO\nImporta el JSON de accesos en Windows",Color.rgb(20,122,71)));
                }catch(Exception ex){runOnUiThread(()->showResult("NO SE PUDO EXPORTAR\n"+ex.getMessage(),Color.RED));}
            });
        });
        jsonImporter = registerForActivityResult(new ActivityResultContracts.OpenDocument(), uri -> {
            if(uri==null)return;
            executor.execute(()->{
                try(InputStream stream=getContentResolver().openInputStream(uri)) {
                    if(stream==null)throw new Exception("No se pudo abrir el archivo");
                    ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                    byte[] block=new byte[8192];int n;
                    while((n=stream.read(block))!=-1){bytes.write(block,0,n);if(bytes.size()>4_000_000)throw new Exception("JSON demasiado grande");}
                    String raw=bytes.toString("UTF-8");
                    String key=new JSONObject(raw).getString("public_key");
                    String prior=prefs.getString("pubkey", "");
                    if(!prior.isEmpty()&&!prior.equals(key))throw new Exception("Firma de otro ordenador. No se puede reemplazar una clave vinculada sin revisión.");
                    if(prior.isEmpty()){
                        String fp=OfflineManager.fingerprint(key);
                        runOnUiThread(()->new AlertDialog.Builder(this)
                            .setTitle("Verifica la firma de Windows")
                            .setMessage("Huella SHA-256 (16 caracteres):\n"+fp+"\n\nComprueba que coincide con la que aparece en Control de Entradas para Windows. La primera importación fija la clave de confianza de este móvil.")
                            .setNegativeButton("Cancelar",(d,w)->{})
                            .setPositiveButton("He comprobado la huella",(d,w)->importVerified(raw))
                            .show());
                    }else importVerified(raw);
                }catch(Exception ex){runOnUiThread(()->showResult("ERROR AL IMPORTAR JSON\n"+ex.getMessage(),Color.RED));}
            });
        });
        BarcodeScannerOptions options = new BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE,Barcode.FORMAT_CODE_128)
            .enableAllPotentialBarcodes()
            .setZoomSuggestionOptions(new ZoomSuggestionOptions.Builder(ratio -> {
                if(activeCamera==null || !continuousEnabled || analyzing.get())return false;
                androidx.camera.core.ZoomState cameraZoomState=activeCamera.getCameraInfo().getZoomState().getValue();
                float maximum=cameraZoomState==null?2.5f:Math.min(1.4f,cameraZoomState.getMaxZoomRatio());
                float requested=Math.max(1.0f,Math.min(maximum,ratio));
                if(requested<=zoomRatio+0.08f)return false;
                zoomRatio=requested;
                applyCameraZoom();
                return true;
            }).setMaxSupportedZoomRatio(1.4f).build())
            .build();
        scanner = BarcodeScanning.getClient(options);
        createUi();
        try {
            if(offline.hasPackage()) {
                publicKey=offline.importedKey();
                setEvents(new JSONArray().put(offline.event()));
                validationMode.setSelection(prefs.getInt("scan_mode",1));
                offlineStatus.setText("JSON firmado cargado · "+offline.ticketCount()+" entradas · sin IP de Windows");
                updateOfflineCounter();
            }else setEvents(new JSONArray(prefs.getString("events", "[]")));
        }catch (Exception ignored) { }
        if(offline.hasPackage()) cameraView.post(()->ensureContinuousScanner());
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
        layout.addView(text("Escuela Municipal de Música y Danza · v2.4 · QR y barras cercano", 12, false));
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
        TextView modeLabel=text("Modo de validación", 13, true);
        layout.addView(modeLabel);
        validationMode=new Spinner(this);
        ArrayList<String> modes=new ArrayList<>();
        modes.add("Servidor Windows (misma red)");
        modes.add("JSON offline (rangos separados)");
        modes.add("Coordinador: este móvil");
        modes.add("Lector conectado a otro móvil");
        validationMode.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,modes));
        validationMode.setSelection(prefs.getInt("scan_mode",0));
        layout.addView(validationMode);
        validationMode.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            @Override public void onItemSelected(android.widget.AdapterView<?> parent,View view,int position,long id){
                prefs.edit().putInt("scan_mode",position).apply();
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> parent){}
        });
        Button importJson=button("IMPORTAR JSON FIRMADO DE WINDOWS");
        layout.addView(importJson);
        importJson.setOnClickListener(v->jsonImporter.launch(new String[]{"application/json","text/plain","*/*"}));
        Button exportAccess=button("EXPORTAR ACCESOS PARA WINDOWS (JSON)");
        layout.addView(exportAccess);
        exportAccess.setOnClickListener(v->auditExporter.launch("Accesos_"+offline.eventId()+".json"));
        offlineStatus=text("No hay JSON offline importado",12,true);layout.addView(offlineStatus);
        CheckBox voiceToggle=new CheckBox(this);
        voiceToggle.setText("Avisos hablados TTS");
        voiceToggle.setChecked(ttsEnabled);
        voiceToggle.setOnCheckedChangeListener((v,enabled)->{
            ttsEnabled=enabled;
            prefs.edit().putBoolean("tts_enabled",enabled).apply();
            if(!enabled && voice!=null) voice.stop();
        });
        layout.addView(voiceToggle);
        ticketListButton=button("VER ENTRADAS DEL JSON Y ESTADO DE ACCESO");
        ticketListButton.setOnClickListener(v->showTicketList());
        layout.addView(ticketListButton);
        layout.addView(text("Sin red: asigna rangos de números DISTINTOS a cada móvil",11,false));
        LinearLayout ranges=new LinearLayout(this);ranges.setOrientation(LinearLayout.HORIZONTAL);
        rangeFrom=new EditText(this);rangeFrom.setHint("Desde, ej. 1");rangeFrom.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        rangeTo=new EditText(this);rangeTo.setHint("Hasta, ej. 200");rangeTo.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        rangeFrom.setText(prefs.getString("range_from",""));rangeTo.setText(prefs.getString("range_to",""));
        ranges.addView(rangeFrom,new LinearLayout.LayoutParams(0,dp(55),1));
        ranges.addView(rangeTo,new LinearLayout.LayoutParams(0,dp(55),1));
        layout.addView(ranges);
        layout.addView(text("Coordinación entre móviles: usa un hotspot o Wi-Fi común (sin ordenador).",11,false));
        coordinatorIp=new EditText(this);coordinatorIp.setSingleLine(true);
        coordinatorIp.setHint("IP del móvil coordinador (ej. 192.168.43.1)");
        coordinatorIp.setText(prefs.getString("coord_ip",""));layout.addView(coordinatorIp);
        coordinatorPin=new EditText(this);coordinatorPin.setSingleLine(true);
        coordinatorPin.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        coordinatorPin.setHint("PIN de 6 cifras");
        coordinatorPin.setText(prefs.getString("coord_pin",""));layout.addView(coordinatorPin);
        coordinatorButton=button("INICIAR COORDINADOR EN ESTE MÓVIL");
        layout.addView(coordinatorButton);
        coordinatorButton.setOnClickListener(v->toggleCoordinator());
        TextView eventLabel=text("Función que se va a controlar", 13, true);
        layout.addView(eventLabel);
        eventSpinner = new Spinner(this);
        layout.addView(eventSpinner);
        Button camera = button("PAUSAR CÁMARA");
        layout.addView(camera);
        camera.setOnClickListener(v -> {
            continuousEnabled = !continuousEnabled;
            if (continuousEnabled) {
                camera.setText("PAUSAR CÁMARA");
                ensureContinuousScanner();
            } else {
                camera.setText("REANUDAR CÁMARA");
                if(cameraProvider!=null) cameraProvider.unbindAll();
                scannerStarted=false;
                cameraView.setVisibility(View.GONE);
                getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                showResult("CÁMARA PAUSADA", Color.rgb(130,82,0));
            }
        });
        cameraView = new PreviewView(this);
        cameraView.setScaleType(PreviewView.ScaleType.FIT_CENTER);
        cameraView.setVisibility(View.GONE);
        layout.addView(cameraView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(420)));
        LinearLayout zoomRow = new LinearLayout(this);
        zoomRow.setOrientation(LinearLayout.HORIZONTAL);
        Button lessZoom = button("– ZOOM");
        Button moreZoom = button("+ ZOOM");
        zoomLabel = text("ZOOM 1.0×", 13, true);
        zoomLabel.setGravity(Gravity.CENTER);
        zoomRow.addView(lessZoom,new LinearLayout.LayoutParams(0,dp(46),1));
        zoomRow.addView(zoomLabel,new LinearLayout.LayoutParams(0,dp(46),1));
        zoomRow.addView(moreZoom,new LinearLayout.LayoutParams(0,dp(46),1));
        layout.addView(zoomRow);
        lessZoom.setOnClickListener(v -> { zoomRatio = Math.max(1.0f,zoomRatio-0.4f); applyCameraZoom(); });
        moreZoom.setOnClickListener(v -> { zoomRatio = Math.min(4.0f,zoomRatio+0.4f); applyCameraZoom(); });
        statusView = text("Listo para conectar", 21, true);
        statusView.setGravity(Gravity.CENTER);
        statusView.setPadding(dp(12), dp(18), dp(12), dp(18));
        statusView.setBackgroundColor(Color.rgb(225, 235, 243));
        layout.addView(statusView);
        counterView = text("", 14, false);
        counterView.setGravity(Gravity.CENTER);
        layout.addView(counterView);
        accessListPanel=new LinearLayout(this);
        accessListPanel.setOrientation(LinearLayout.VERTICAL);
        accessListPanel.addView(text("ENTRADAS Y CONTROL DE ACCESOS",16,true));
        ticketSearch=new EditText(this);
        ticketSearch.setSingleLine(true);
        ticketSearch.setHint("Buscar número o butaca...");
        accessListPanel.addView(ticketSearch);
        ticketSearch.addTextChangedListener(new android.text.TextWatcher(){
            public void beforeTextChanged(CharSequence v,int start,int count,int after){}
            public void onTextChanged(CharSequence v,int start,int before,int count){refreshAccessLists();}
            public void afterTextChanged(android.text.Editable e){}
        });
        accessListPanel.addView(text("DISPONIBLES (SIN VALIDAR)",14,true));
        ScrollView pendingScroll=new ScrollView(this);
        pendingScroll.setNestedScrollingEnabled(true);
        availableListView=text("Importa el JSON para ver las entradas.",13,false);
        pendingScroll.addView(availableListView);
        accessListPanel.addView(pendingScroll,new LinearLayout.LayoutParams(-1,dp(165)));
        accessListPanel.addView(text("VALIDADAS · FECHA Y HORA",14,true));
        accessOrder=new Spinner(this);
        accessOrder.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,
            new String[]{"Por número de entrada","Por orden de llegada (última primero)","Por llegada (primera primero)"}));
        accessOrder.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            public void onItemSelected(android.widget.AdapterView<?> p,View v,int n,long id){refreshAccessLists();}
            public void onNothingSelected(android.widget.AdapterView<?> p){}
        });
        accessListPanel.addView(accessOrder);
        ScrollView approvedScroll=new ScrollView(this);
        approvedScroll.setNestedScrollingEnabled(true);
        usedListView=text("Todavía no hay accesos.",13,false);
        approvedScroll.addView(usedListView);
        accessListPanel.addView(approvedScroll,new LinearLayout.LayoutParams(-1,dp(165)));
        Button resetLocal=button("RESTABLECER ACCESOS DE ESTE MÓVIL");
        resetLocal.setOnClickListener(v->new AlertDialog.Builder(this)
            .setTitle("Restablecer accesos locales")
            .setMessage("Se eliminarán las validaciones locales de esta función y sus horas. El JSON firmado no cambia, y los accesos ya comunicados a Windows u otros móviles NO se restablecen. Esta operación puede permitir reutilizar entradas: úsala solo en pruebas.")
            .setNegativeButton("Cancelar",null)
            .setPositiveButton("RESTABLECER",(d,w)->{
                try {int n=offline.resetLocalAccesses();updateOfflineCounter();showResult(n+" accesos locales restablecidos",Color.rgb(130,82,0));}
                catch(Exception ex){showResult("NO SE PUDO RESTABLECER: "+ex.getMessage(),Color.RED);}
            }).show());
        accessListPanel.addView(resetLocal);
        layout.addView(accessListPanel);
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
        // El lector y la información de la función quedan visibles SIN desplazarse
        // por todos los controles de red. Los ajustes se abren solo cuando se necesiten.
        LinearLayout fastPanel=new LinearLayout(this);
        fastPanel.setOrientation(LinearLayout.VERTICAL);
        fastPanel.setPadding(dp(10),dp(8),dp(10),dp(10));
        fastPanel.setBackgroundColor(Color.WHITE);
        View[] quick={connectionView,eventLabel,eventSpinner,modeLabel,validationMode,importJson,
                offlineStatus,voiceToggle,ticketListButton,cameraView,zoomRow,camera,statusView,counterView,accessListPanel,queueView};
        for(View view:quick) layout.removeView(view);
        LinearLayout settingsPanel=new LinearLayout(this);
        settingsPanel.setOrientation(LinearLayout.VERTICAL);
        while(layout.getChildCount()>2){
            View view=layout.getChildAt(2);
            layout.removeViewAt(2);
            settingsPanel.addView(view);
        }
        for(View view:quick) fastPanel.addView(view);
        layout.addView(fastPanel);
        Button settingsToggle=button("MOSTRAR AJUSTES DE RED Y SINCRONIZACIÓN");
        layout.addView(settingsToggle);
        settingsPanel.setVisibility(View.GONE);
        layout.addView(settingsPanel);
        settingsToggle.setOnClickListener(v->{
            boolean open=settingsPanel.getVisibility()!=View.VISIBLE;
            settingsPanel.setVisibility(open?View.VISIBLE:View.GONE);
            settingsToggle.setText(open?"OCULTAR AJUSTES":"MOSTRAR AJUSTES DE RED Y SINCRONIZACIÓN");
        });
        Button shareButton=button("COMPARTIR JSON CON OTRO MÓVIL");
        fastPanel.addView(shareButton,5);
        shareButton.setOnClickListener(v->shareSignedEvent());
        refreshPending();
    }

    private void showTicketList(){
        if(!offline.hasPackage()){
            new AlertDialog.Builder(this).setTitle("Entradas")
                .setMessage("Importa el JSON firmado de Windows para consultar las entradas.")
                .setPositiveButton("Aceptar",null).show();
            return;
        }
        JSONArray arr=offline.ticketList();
        int used=0;
        StringBuilder info=new StringBuilder();
        for(int i=0;i<arr.length();i++){
            JSONObject t=arr.optJSONObject(i);
            if(t==null)continue;
            boolean scanned=t.optBoolean("used");
            if(scanned)used++;
            info.append(String.format(java.util.Locale.US,"%04d",t.optInt("number")));
            if(!t.optString("seat").isEmpty())info.append(" · ").append(t.optString("seat"));
            info.append(scanned?" · UTILIZADA":" · PENDIENTE");
            if(t.optBoolean("print_known"))info.append(t.optBoolean("printed")?" · ENVIADA A IMPRESORA":" · SIN ENVÍO REGISTRADO");
            info.append("\n");
        }
        final int completed=used;
        new AlertDialog.Builder(this)
            .setTitle("Entradas del JSON: "+arr.length()+" · Usadas: "+completed)
            .setMessage(info.length()>0?info.toString():"El archivo no contiene entradas.")
            .setPositiveButton("Cerrar",null).show();
    }
    private void updateOfflineCounter() {
        if(!offline.hasPackage())return;
        JSONArray items=offline.ticketList();
        int used=0;
        for(int i=0;i<items.length();i++){
            JSONObject t=items.optJSONObject(i);
            if(t!=null && t.optBoolean("used"))used++;
        }
        counterView.setText("JSON importado: "+items.length()+" entradas  ·  Validadas: "+used+
                "  ·  Pendientes: "+(items.length()-used));
        refreshAccessLists();
    }

    private String accessTimeSortKey(String value){
        if(value==null)return "";
        // Local: dd/MM/yyyy HH:mm:ss; server: ISO 8601.
        if(value.length()>=19 && value.charAt(2)=='/' && value.charAt(5)=='/'){
            return value.substring(6,10)+value.substring(3,5)+value.substring(0,2)+value.substring(11,19);
        }
        return value.replace("-","").replace("T","").replace(":","");
    }
    private void refreshAccessLists(){
        if(availableListView==null || usedListView==null || offline==null || !offline.hasPackage())return;
        JSONArray items=offline.ticketList();
        String q=ticketSearch==null?"":ticketSearch.getText().toString().trim().toLowerCase(java.util.Locale.ROOT);
        StringBuilder available=new StringBuilder(),approved=new StringBuilder();
        java.util.ArrayList<JSONObject> ordered=new java.util.ArrayList<>();
        for(int i=0;i<items.length();i++){
            JSONObject row=items.optJSONObject(i);
            if(row!=null)ordered.add(row);
        }
        int order=accessOrder==null?0:accessOrder.getSelectedItemPosition();
        if(order!=0)ordered.sort((a,b)->{
            String ta=a.optString("used_at",""),tb=b.optString("used_at","");
            String ka=accessTimeSortKey(ta),kb=accessTimeSortKey(tb);
            int compared=ka.compareTo(kb);
            if(compared==0)compared=Integer.compare(a.optInt("number"),b.optInt("number"));
            return order==1?-compared:compared;
        });
        int pending=0,used=0;
        for(JSONObject t:ordered){
            String num=String.format(java.util.Locale.US,"%04d",t.optInt("number"));
            String seat=t.optString("seat","");
            if("null".equalsIgnoreCase(seat))seat="";
            if(!q.isEmpty() && !num.contains(q) && !seat.toLowerCase(java.util.Locale.ROOT).contains(q))continue;
            if(t.optBoolean("used")){
                used++;approved.append("✓ ").append(num);
                if(!seat.isEmpty())approved.append(" · ").append(seat);
                String time=t.optString("used_at","");
                if(!time.isEmpty() && !"null".equalsIgnoreCase(time))approved.append(" · ").append(time);
                else approved.append(" · Hora anterior no disponible");
                approved.append("\n");
            }else{
                pending++;available.append("○ ").append(num);
                if(!seat.isEmpty())available.append(" · ").append(seat);
                available.append(" · DISPONIBLE\n");
            }
        }
        availableListView.setText(pending==0?"No hay entradas pendientes.":available.toString());
        usedListView.setText(used==0?"Todavía no hay accesos registrados.":approved.toString());
    }
    private void shareSignedEvent(){
        try{
            if(!offline.hasPackage())throw new Exception("Importa primero un evento firmado");
            File file=new File(new File(getCacheDir(),"share"),"Evento_firmado_ControlEntradas.json");
            file.getParentFile().mkdirs();
            try(InputStream in=new java.io.FileInputStream(offline.storedPackage());
                OutputStream out=new FileOutputStream(file)){
                byte[] buf=new byte[8192];int n;
                while((n=in.read(buf))!=-1)out.write(buf,0,n);
            }
            Uri uri=FileProvider.getUriForFile(this,getPackageName()+".fileprovider",file);
            Intent intent=new Intent(Intent.ACTION_SEND);
            intent.setType("application/json");
            intent.putExtra(Intent.EXTRA_STREAM,uri);
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(Intent.createChooser(intent,"Enviar evento firmado"));
        }catch(Exception e){showResult("NO SE PUEDE COMPARTIR: "+e.getMessage(),Color.RED);}
    }

    private void ensureContinuousScanner(){
        if(!continuousEnabled || eventIds.isEmpty())return;
        if(ContextCompat.checkSelfPermission(this,Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED){
            startScanner();
        }else permissionLauncher.launch(Manifest.permission.CAMERA);
    }

    private String messageForVoice(String value) {
        String text = value == null ? "" : value.replace('\n', ' ');
        return text.length() > 110 ? text.substring(0,110) : text;
    }
    private void say(String message) {
        if(ttsEnabled && voiceReady && voice != null) voice.speak(message, TextToSpeech.QUEUE_FLUSH, null, "qr_result");
    }
    private void detectedBeep() {
        try { feedbackTone.startTone(ToneGenerator.TONE_PROP_BEEP, 220); } catch(Exception ignored) {}
    }
    private void scanFeedback(boolean accepted){
        try{feedbackTone.startTone(accepted?ToneGenerator.TONE_PROP_ACK:ToneGenerator.TONE_PROP_NACK,accepted?100:240);}catch(Exception ignored){}
        try{
            Vibrator vib=(Vibrator)getSystemService(VIBRATOR_SERVICE);
            if(vib!=null && vib.hasVibrator()){
                if(Build.VERSION.SDK_INT>=26)vib.vibrate(VibrationEffect.createOneShot(accepted?80:230,VibrationEffect.DEFAULT_AMPLITUDE));
                else vib.vibrate(accepted?80:230);
            }
        }catch(Exception ignored){}
    }

    private void importVerified(String raw){
        executor.execute(()->{
            try{
                JSONObject event=offline.load(raw,true);
                publicKey=offline.importedKey();
                prefs.edit().putString("pubkey",publicKey).apply();
                runOnUiThread(()->{
                    setEvents(new JSONArray().put(event));
                    validationMode.setSelection(1);
                    offlineStatus.setText("Archivo verificado: "+event.optString("name")+" · "+offline.ticketCount()+" entradas");
                    updateOfflineCounter();
                    showResult("JSON CARGADO · CÁMARA PREPARADA",Color.rgb(20,122,71));
                    ensureContinuousScanner();
                });
            }catch(Exception ex){runOnUiThread(()->showResult("JSON RECHAZADO\n"+ex.getMessage(),Color.RED));}
        });
    }
    private void toggleCoordinator(){
        if(offline.hosting()){
            offline.stopHost();coordinatorButton.setText("INICIAR COORDINADOR EN ESTE MÓVIL");
            showResult("COORDINADOR DETENIDO",Color.rgb(130,82,0));return;
        }
        try{
            String code=coordinatorPin.getText().toString().trim();
            if(!code.matches("[0-9]{6}"))throw new Exception("Escribe un PIN de seis cifras");
            offline.startHost(code);
            prefs.edit().putString("coord_pin",code).apply();
            validationMode.setSelection(2);
            coordinatorButton.setText("DETENER COORDINADOR");
            offlineStatus.setText("Coordinador activo · IP: "+OfflineManager.ips()+" · Puerto "+OfflineManager.PORT);
            showResult("COORDINADOR ACTIVO\nMantén esta pantalla abierta y conecta los lectores al mismo hotspot o Wi-Fi.",Color.rgb(20,122,71));
        }catch(Exception ex){showResult("NO SE PUDO INICIAR COORDINADOR\n"+ex.getMessage(),Color.RED);}
    }
    private JSONObject coordinatorRequest(String qr,String event,String host,String pin) throws Exception {
        if(!host.matches("[0-9.]+"))throw new Exception("Escribe la dirección IPv4 del coordinador");
        java.net.HttpURLConnection c=(java.net.HttpURLConnection)new URL("http://"+host+":"+OfflineManager.PORT+"/validate").openConnection();
        try{
            c.setConnectTimeout(2500);c.setReadTimeout(3500);c.setRequestMethod("POST");
            c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json; charset=utf-8");
            byte[] body=new JSONObject().put("qr",qr).put("event_id",event).put("pin",pin).put("device_id",deviceId).toString().getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(body.length);
            try(OutputStream out=c.getOutputStream()){out.write(body);}
            if(c.getResponseCode()!=200)throw new IOException("Sin respuesta del móvil coordinador");
            ByteArrayOutputStream b=new ByteArrayOutputStream();
            try(InputStream in=c.getInputStream()){byte[] block=new byte[1024];int n;while((n=in.read(block))!=-1){b.write(block,0,n);if(b.size()>20000)throw new IOException("Respuesta demasiado grande");}}
            return new JSONObject(b.toString("UTF-8"));
        }finally{c.disconnect();}
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
                if(continuousEnabled && cameraView!=null) cameraView.post(()->ensureContinuousScanner());
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
        if(offline.hasPackage()){updateOfflineCounter();return;}
        if(ev != null) counterView.setText("Accesos confirmados al conectar: " + ev.optInt("used") + " / " + ev.optInt("issued"));
    }
    private void showResult(String message, int color) {
        statusView.setText(message);
        boolean ok = color == Color.rgb(20,122,71);
        boolean denied = color == Color.RED;
        statusView.setBackgroundColor(ok?Color.rgb(216,246,222):denied?Color.rgb(255,224,224):Color.rgb(255,245,214));
        statusView.setTextColor(ok?Color.rgb(15,105,51):denied?Color.rgb(171,32,32):Color.rgb(120,75,0));
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
                String known=prefs.getString("pubkey", "");
                if(!known.isEmpty() && !known.equals(pk))throw new Exception("Clave de otro ordenador. Comprueba el organizador.");
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
    private String scanIdentity(String raw) {
        if(raw.matches("[0-9]{16}"))return raw;
        if(raw.startsWith("CE1."))try{
            String[] pieces=raw.split("\\.");
            if(pieces.length==3){
                String content=new String(Base64.decode(pieces[1],
                    Base64.URL_SAFE|Base64.NO_PADDING|Base64.NO_WRAP),StandardCharsets.UTF_8);
                String id=new JSONObject(content).optString("id","");
                if(id.matches("[0-9a-f]{32}"))
                    return String.format(java.util.Locale.US,"%016d",Long.parseLong(id.substring(0,13),16));
            }
        }catch(Exception ignored){}
        return raw;
    }
    private void applyCameraZoom(){
        if (activeCamera != null) {
            androidx.camera.core.ZoomState state = activeCamera.getCameraInfo().getZoomState().getValue();
            float min = state == null ? 1.0f : state.getMinZoomRatio();
            float max = state == null ? 1.0f : state.getMaxZoomRatio();
            zoomRatio = Math.max(min,Math.min(max,zoomRatio));
            activeCamera.getCameraControl().setZoomRatio(zoomRatio);
        }
        if(zoomLabel!=null) zoomLabel.setText(String.format(java.util.Locale.US,"ZOOM %.1f×",zoomRatio));
    }
    @androidx.camera.core.ExperimentalGetImage
    private void startScanner() {
        if(!continuousEnabled || eventIds.isEmpty() || scannerStarted)return;
        scannerStarted=true;
        cameraView.setVisibility(View.VISIBLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        ListenableFuture<ProcessCameraProvider> provider=ProcessCameraProvider.getInstance(this);
        provider.addListener(()->{
            try{
                if(!continuousEnabled){scannerStarted=false;return;}
                cameraProvider=provider.get();
                Preview preview=new Preview.Builder().build();
                preview.setSurfaceProvider(cameraView.getSurfaceProvider());
                ImageAnalysis analysis=new ImageAnalysis.Builder()
                    .setTargetResolution(new Size(1280,960))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build();
                analysis.setAnalyzer(cameraExecutor, image->{
                    if(!frameBusy.compareAndSet(false,true)){image.close();return;}
                    android.media.Image media=image.getImage();
                    if(media==null){frameBusy.set(false);image.close();return;}
                    InputImage input=InputImage.fromMediaImage(media,image.getImageInfo().getRotationDegrees());
                    scanner.process(input)
                        .addOnSuccessListener(barcodes->{
                            String candidate=null;
                            for(Barcode barcode:barcodes){
                                String value=barcode.getRawValue();
                                if(value==null || value.trim().isEmpty())continue;
                                value=value.trim();
                                if(value.startsWith("CE1.") || value.matches("[0-9]{16}")){candidate=value;break;}
                                if(candidate==null)candidate=value;
                            }
                            long now=SystemClock.elapsedRealtime();
                            if(candidate==null){
                                if(now-lastQrVisibleMs>260)blockedQr="";
                                return;
                            }
                            String scanKey=scanIdentity(candidate);
                            boolean same=scanKey.equals(blockedQr);
                            lastQrVisibleMs=now;
                            if(same || analyzing.get())return;
                            showResult("CÓDIGO DETECTADO · VALIDANDO...",Color.rgb(130,82,0));
                            detectedBeep();
                            if(!candidate.startsWith("CE1.") && !candidate.matches("[0-9]{16}")){
                                blockedQr=scanKey;
                                showResult("CÓDIGO QR/BARRAS NO VÁLIDO",Color.RED);
                                scanFeedback(false);
                                say("Código QR no válido para este espectáculo.");
                                return;
                            }
                            if(analyzing.compareAndSet(false,true)){
                                blockedQr=scanKey;
                                processQr(candidate);
                            }
                        })
                        .addOnFailureListener(error -> {
                            long now=SystemClock.elapsedRealtime();
                            if(now-lastScannerErrorMs>3000){
                                lastScannerErrorMs=now;
                                runOnUiThread(()->showResult("ERROR DEL LECTOR QR: "+error.getMessage(),Color.RED));
                            }
                        })
                        .addOnCompleteListener(task->{frameBusy.set(false);image.close();});
                });
                cameraProvider.unbindAll();
                activeCamera=cameraProvider.bindToLifecycle(this,CameraSelector.DEFAULT_BACK_CAMERA,preview,analysis);
                applyCameraZoom();
                showResult("CÁMARA ACTIVA · DETECCIÓN EN TODO EL ENCUADRE",Color.rgb(130,82,0));
            }catch(Exception e){scannerStarted=false;showResult("ERROR DE CÁMARA: "+e.getMessage(),Color.RED);}
        },ContextCompat.getMainExecutor(this));
    }
    private void processQr(String qr) {
        String event=currentEventId();
        if(event.isEmpty()){showResult("SELECCIONA UNA FUNCIÓN",Color.RED);analyzing.set(false);return;}
        int mode=validationMode.getSelectedItemPosition();
        String first=rangeFrom.getText().toString().trim(),last=rangeTo.getText().toString().trim();
        String host=coordinatorIp.getText().toString().trim(),secret=coordinatorPin.getText().toString().trim();
        prefs.edit().putString("range_from",first).putString("range_to",last)
                .putString("coord_ip",host).putString("coord_pin",secret).apply();
        if(mode==1 && (first.isEmpty()!=last.isEmpty())){
            showResult("INDICA AMBOS EXTREMOS DEL RANGO O DÉJALOS VACÍOS (SOLO UN MÓVIL)",Color.RED);
            analyzing.set(false);return;
        }
        showResult("COMPROBANDO ENTRADA...",Color.rgb(130,82,0));
        executor.execute(()->{
            try {
                JSONObject response;
                if(mode==0){
                    try{
                        JSONObject body=new JSONObject().put("qr",qr).put("event_id",event).put("device_id",deviceId);
                        response=request("/api/validate",body);
                    }catch(Exception ex){
                        if(emergencyMode.isChecked() && ex instanceof java.io.IOException){offlineAccept(qr,event);return;}
                        throw ex;
                    }
                }else if(mode==1){
                    int from=first.isEmpty()?1:Integer.parseInt(first);
                    int to=last.isEmpty()?Integer.MAX_VALUE:Integer.parseInt(last);
                    if(from<1||to<from)throw new Exception("Rango de números incorrecto");
                    response=offline.validate(qr,event,deviceId,from,to);
                }else if(mode==2){
                    if(!offline.hosting())throw new Exception("Este móvil no está actuando como coordinador");
                    response=offline.validate(qr,event,deviceId,1,Integer.MAX_VALUE);
                }else if(mode==3){
                    response=coordinatorRequest(qr,event,host,secret);
                }else throw new Exception("Modo de validación desconocido");
                String status=response.optString("status","invalid");
                String message=response.isNull("message")?"":response.optString("message","");
                String seat=response.isNull("seat")?"":response.optString("seat","");
                if("null".equalsIgnoreCase(seat))seat="";
                if(message==null || message.trim().isEmpty() || "null".equalsIgnoreCase(message.trim()))
                    message="valid".equals(status)?"ENTRADA VÁLIDA":"Entrada rechazada. Comprueba la función y el JSON importado.";
                if("valid".equals(status))message+="\nN.º "+response.optInt("number")+
                    (seat.isEmpty()?"":"\n"+seat);
                String finished=message;
                boolean accepted="valid".equals(status);
                runOnUiThread(()->{showResult((accepted?"AUTORIZADO\n":"NO AUTORIZADO\n")+finished,accepted?Color.rgb(20,122,71):Color.RED);scanFeedback(accepted);say(accepted?"Entrada autorizada.":"Entrada no autorizada. "+messageForVoice(finished));updateOfflineCounter();zoomRatio=1.0f;applyCameraZoom();});
            }catch(Exception ex){
                runOnUiThread(()->{String detail=ex.getMessage()==null?"Error de validación":ex.getMessage();showResult("NO AUTORIZADO\n"+detail,Color.RED);scanFeedback(false);say("Entrada no autorizada.");});
            }finally{runOnUiThread(()->analyzing.set(false));}
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
            runOnUiThread(() -> { showResult("ACCESO PROVISIONAL SIN RED\nN.º "+ticket.optInt("n") + (ticket.isNull("s") ? "" : "\n" + ticket.optString("s")) + "\nSOLO ESTE MÓVIL",Color.rgb(130,82,0));scanFeedback(true);say("Acceso provisional sin red.");refreshPending(); });
        } catch(Exception ex) {
            runOnUiThread(() -> {showResult("ENTRADA RECHAZADA\n"+ex.getMessage(),Color.RED);scanFeedback(false);say("Entrada rechazada.");});
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
    @Override protected void onResume(){
        super.onResume();
        if(cameraView!=null && continuousEnabled)cameraView.post(()->ensureContinuousScanner());
    }
    @Override protected void onDestroy() {
        super.onDestroy();
        if(cameraProvider!=null) cameraProvider.unbindAll();
        scanner.close();
        feedbackTone.release();
        if(voice != null){voice.stop();voice.shutdown();}
        if(offline!=null)offline.stopHost();
        cameraExecutor.shutdownNow();
        executor.shutdownNow();
    }
}