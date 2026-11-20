package es.benalmadena.controlentradas;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.FileInputStream;
import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Offline JSON package signed by Windows; optional Android coordinator in local Wi-Fi/hotspot.
 * No cloud or fixed Windows IP. All coordinator approvals share one synchronized state.
 */
public final class OfflineManager {
    public static final int PORT = 8766;
    private final Context context;
    private final SharedPreferences prefs;
    private final File stored;
    private final File eventFolder;
    private final Map<String,String> importedRaw = new LinkedHashMap<>();
    private JSONObject data;
    private String publicKey = "";
    private final Map<String,JSONObject> tickets = new HashMap<>();
    private ServerSocket server;
    private final ExecutorService threads = Executors.newCachedThreadPool();

    public OfflineManager(Context context) {
        this.context=context.getApplicationContext();
        prefs=this.context.getSharedPreferences("offline_v1",Context.MODE_PRIVATE);
        stored=new File(this.context.getFilesDir(),"signed_event_v1.json");
        eventFolder=new File(this.context.getFilesDir(),"signed_events");
        if(!eventFolder.isDirectory())eventFolder.mkdirs();
        File[] files=eventFolder.listFiles((dir,name)->name.matches("[0-9a-f]{32}\\.json"));
        if(files!=null)for(File file:files)try{
            byte[] bytes=readAll(new FileInputStream(file),4_000_000);
            load(new String(bytes,StandardCharsets.UTF_8),false);
        }catch(Exception ignored){}
        // Migración de versiones anteriores, sin borrar su archivo o accesos.
        if(stored.isFile())try{
            byte[] bytes=readAll(new FileInputStream(stored),4_000_000);
            String raw=new String(bytes,StandardCharsets.UTF_8);
            JSONObject envelope=new JSONObject(raw);
            JSONObject payload=new JSONObject(new String(
                decodeUrl(envelope.getString("payload")),StandardCharsets.UTF_8));
            String eid=payload.getJSONObject("event").getString("id");
            if(!importedRaw.containsKey(eid))load(raw,true);
        }catch(Exception ignored){}
        if(!importedRaw.isEmpty())try {
            String chosen=prefs.getString("active_event","");
            if(!importedRaw.containsKey(chosen))
                chosen=importedRaw.keySet().iterator().next();
            selectEvent(chosen);
        }catch(Exception ignored){}
    }
    private static byte[] decodeUrl(String v) {
        return Base64.decode(v,Base64.URL_SAFE|Base64.NO_PADDING|Base64.NO_WRAP);
    }
    private static byte[] readAll(InputStream in,int max) throws Exception {
        try(InputStream input=in; ByteArrayOutputStream b=new ByteArrayOutputStream()) {
            byte[] block=new byte[8192];int n;
            while((n=input.read(block))!=-1){b.write(block,0,n);if(b.size()>max)throw new Exception("Archivo demasiado grande");}
            return b.toByteArray();
        }
    }
    public static String fingerprint(String pub) throws Exception {
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(Base64.decode(pub,Base64.DEFAULT));
        StringBuilder sb=new StringBuilder();
        for(int i=0;i<8;i++)sb.append(String.format("%02X",hash[i]));
        return sb.toString();
    }
    public synchronized JSONObject load(String raw,boolean persist) throws Exception {
        if(raw.length()>4_000_000)throw new Exception("Paquete JSON demasiado grande");
        JSONObject pack=new JSONObject(raw);
        if(!"CE-OFFLINE-1".equals(pack.optString("format")))throw new Exception("No es un JSON de Control de Entradas");
        String pub=pack.getString("public_key"), encoded=pack.getString("payload");
        String old=prefs.getString("trusted_key","");
        if(!old.isEmpty() && !old.equals(pub))throw new Exception("Clave de firma diferente al equipo de confianza");
        PublicKey key=KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(Base64.decode(pub,Base64.DEFAULT)));
        Signature check=Signature.getInstance("SHA256withECDSA");
        check.initVerify(key);check.update(encoded.getBytes(StandardCharsets.US_ASCII));
        if(!check.verify(decodeUrl(pack.getString("signature"))))throw new Exception("Firma del archivo JSON inválida");
        JSONObject decoded=new JSONObject(new String(decodeUrl(encoded),StandardCharsets.UTF_8));
        if(decoded.optInt("version")!=1)throw new Exception("Versión de archivo no compatible");
        JSONObject event=decoded.getJSONObject("event");
        JSONArray array=decoded.getJSONArray("tickets");
        if(array.length()>10000 || event.optString("id").isEmpty())throw new Exception("Datos de función inválidos");
        HashMap<String,JSONObject> byId=new HashMap<>();
        for(int i=0;i<array.length();i++){
            JSONObject t=array.getJSONObject(i);
            if(t.optString("id").isEmpty() || byId.put(t.getString("id"),t)!=null)throw new Exception("Identificador de entrada inválido o duplicado");
        }
        if(persist){
            // Nunca borrar accesos locales al recibir un inventario firmado
            // actualizado de la MISMA función. Los ID todavía válidos retienen
            // su condición de utilizados, también tras una reinstalación.
            File dest=new File(eventFolder,event.getString("id")+".json");
            File temp=new File(eventFolder,event.getString("id")+".tmp");
            try(FileOutputStream out=new FileOutputStream(temp,false)){
                out.write(raw.getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            try {
                Files.move(temp.toPath(),dest.toPath(),
                    StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            }catch(java.nio.file.AtomicMoveNotSupportedException ex){
                Files.move(temp.toPath(),dest.toPath(),StandardCopyOption.REPLACE_EXISTING);
            }
            if(!prefs.edit().putString("trusted_key",pub)
                .putString("inventory_payload_"+event.getString("id"),encoded)
                .putString("active_event",event.getString("id")).commit())
                throw new Exception("No se pudieron guardar los ajustes de la función");
        }
        data=decoded;publicKey=pub;tickets.clear();tickets.putAll(byId);
        importedRaw.put(event.getString("id"),raw);
        return event;
    }
    public synchronized String importedKey(){ return publicKey; }
    public synchronized boolean hasPackage(){ return data!=null; }
    public synchronized File storedPackage() throws Exception {
        if(data==null)throw new Exception("No hay JSON firmado para compartir");
        File current=new File(eventFolder,eventId()+".json");
        if(current.isFile())return current;
        if(stored.isFile())return stored;
        throw new Exception("Archivo JSON firmado no disponible");
    }
    public synchronized boolean selectEvent(String eid) throws Exception {
        String raw=importedRaw.get(eid);
        if(raw==null)return false;
        load(raw,false);
        prefs.edit().putString("active_event",eid).apply();
        return true;
    }
    public synchronized JSONArray importedEvents() {
        java.util.ArrayList<JSONObject> ordered=new java.util.ArrayList<>();
        for(Map.Entry<String,String> pair:importedRaw.entrySet())try{
            JSONObject pack=new JSONObject(pair.getValue());
            JSONObject envelope=new JSONObject(new String(
                decodeUrl(pack.getString("payload")),StandardCharsets.UTF_8));
            ordered.add(envelope.getJSONObject("event"));
        }catch(Exception ignored){}
        ordered.sort((x,y)->x.optString("start_time").compareTo(
                                  y.optString("start_time")));
        JSONArray events=new JSONArray();
        for(JSONObject ev:ordered)events.put(ev);
        return events;
    }
    public synchronized int firstActive(){
        if(data==null)return 1;
        int minimum=Integer.MAX_VALUE;
        for(JSONObject t:tickets.values())
            minimum=Math.min(minimum,t.optInt("number",Integer.MAX_VALUE));
        int fallback=data.optInt("first_active",minimum==Integer.MAX_VALUE?1:minimum);
        int chosen=prefs.getInt("first_active_"+eventId(),fallback);
        for(JSONObject t:tickets.values())
            if(t.optInt("number")==chosen)return chosen;
        return fallback;
    }
    public synchronized void setFirstActive(int number) throws Exception {
        if(data==null)throw new Exception("Selecciona una función importada");
        boolean present=false;
        for(JSONObject t:tickets.values())
            if(t.optInt("number")==number){present=true;break;}
        if(!present)throw new Exception("El número debe estar entre los tickets importados de esta función");
        if(!prefs.edit().putInt("first_active_"+eventId(),number).commit())
            throw new Exception("No se pudo guardar el primer ticket activo");
    }
    public synchronized int nextExpected(){
        if(data==null)return -1;
        int first=firstActive(),expected=Integer.MAX_VALUE;
        String eid=eventId();
        for(JSONObject t:tickets.values()){
            int num=t.optInt("number",-1);
            if(num<first || t.optBoolean("used") ||
               prefs.getBoolean("used_"+eid+"_"+t.optString("id"),false))continue;
            expected=Math.min(expected,num);
        }
        return expected==Integer.MAX_VALUE?-1:expected;
    }
    public synchronized JSONArray inventorySummaries(){
        JSONArray result=new JSONArray();
        for(Map.Entry<String,String> entry:importedRaw.entrySet())try{
            JSONObject decoded=new JSONObject(new String(
                decodeUrl(new JSONObject(entry.getValue()).getString("payload")),
                StandardCharsets.UTF_8));
            JSONObject ev=decoded.getJSONObject("event");
            JSONArray list=decoded.getJSONArray("tickets");
            String eid=ev.getString("id");
            int used=0,min=Integer.MAX_VALUE,next=Integer.MAX_VALUE;
            for(int i=0;i<list.length();i++){
                JSONObject t=list.getJSONObject(i);
                int number=t.optInt("number");
                min=Math.min(min,number);
            }
            int first=prefs.getInt("first_active_"+eid,
                decoded.optInt("first_active",min==Integer.MAX_VALUE?1:min));
            boolean exists=false;
            for(int i=0;i<list.length();i++){
                JSONObject t=list.getJSONObject(i);
                if(t.optInt("number")==first){exists=true;break;}
            }
            if(!exists)first=decoded.optInt("first_active",
                                 min==Integer.MAX_VALUE?1:min);
            for(int i=0;i<list.length();i++){
                JSONObject t=list.getJSONObject(i);
                boolean scanned=t.optBoolean("used") ||
                    prefs.getBoolean("used_"+eid+"_"+t.optString("id"),false);
                if(scanned)used++;
                else if(t.optInt("number")>=first)
                    next=Math.min(next,t.optInt("number"));
            }
            result.put(new JSONObject()
                .put("id",eid).put("name",ev.optString("name"))
                .put("start_time",ev.optString("start_time"))
                .put("total",list.length()).put("used",used)
                .put("available",list.length()-used)
                .put("first_active",first)
                .put("next_expected",next==Integer.MAX_VALUE?-1:next));
        }catch(Exception ignored){}
        // Sin mutar la función activa ni los números pendientes.
        java.util.ArrayList<JSONObject> ordered=new java.util.ArrayList<>();
        for(int i=0;i<result.length();i++)ordered.add(result.optJSONObject(i));
        ordered.sort((x,y)->x.optString("start_time").compareTo(
                            y.optString("start_time")));
        JSONArray sorted=new JSONArray();
        for(JSONObject item:ordered)sorted.put(item);
        return sorted;
    }
    public synchronized String eventId(){ return data==null?"":data.optJSONObject("event").optString("id"); }
    public synchronized JSONObject event(){ return data==null?null:data.optJSONObject("event"); }
    public synchronized int ticketCount(){ return tickets.size(); }
    public synchronized JSONArray ticketList() {
        JSONArray rows = new JSONArray();
        if(data==null)return rows;
        java.util.ArrayList<JSONObject> ordered=new java.util.ArrayList<>(tickets.values());
        ordered.sort((a,b)->Integer.compare(a.optInt("number"),b.optInt("number")));
        String eid=eventId();
        for(JSONObject t:ordered){
            JSONObject item=new JSONObject();
            try{
                item.put("number",t.optInt("number"));
                item.put("seat",t.optString("seat",""));
                item.put("used",t.optBoolean("used") ||
                        prefs.getBoolean("used_"+eid+"_"+t.optString("id"),false));
                item.put("used_at", prefs.getString("used_time_"+eid+"_"+t.optString("id"), t.optString("used_at","")));
                item.put("reserved",t.optBoolean("reserved"));
                item.put("printed",t.optBoolean("submitted_to_printer"));
                item.put("print_known",t.has("submitted_to_printer"));
                rows.put(item);
            }catch(Exception ignored){}
        }
        return rows;
    }
    public synchronized boolean hosting(){return server!=null&&!server.isClosed();}
    private static String alternateBarcode(String id) {
        if(id==null || id.length()<13)return "";
        return String.format(java.util.Locale.US,"%016d",Long.parseLong(id.substring(0,13),16));
    }
    private synchronized JSONObject verifyQr(String qr,String event) throws Exception {
        if(data==null)throw new Exception("Importa primero un JSON firmado");
        if(qr!=null && qr.matches("[0-9]{16}")){
            JSONObject match=null;
            for(JSONObject candidate:tickets.values()){
                if(qr.equals(alternateBarcode(candidate.optString("id")))){
                    if(match!=null)throw new Exception("Código de barras duplicado");
                    match=candidate;
                }
            }
            if(match==null)throw new Exception("Código de barras no incluido en el JSON importado");
            if(!event.equals(eventId()))throw new Exception("Código de otra función");
            if(match.optBoolean("used"))throw new Exception("Entrada ya utilizada al exportar el evento");
            return new JSONObject().put("id",match.getString("id")).put("e",event)
                .put("n",match.optInt("number")).put("s",match.optString("seat",""));
        }
        String[] parts=qr.split("\\.");
        if(parts.length!=3||!parts[0].equals("CE1"))throw new Exception("QR no reconocido");
        PublicKey key=KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(Base64.decode(publicKey,Base64.DEFAULT)));
        Signature validator=Signature.getInstance("SHA256withECDSA");
        validator.initVerify(key);
        validator.update(parts[1].getBytes(StandardCharsets.US_ASCII));
        if(!validator.verify(decodeUrl(parts[2])))throw new Exception("QR falsificado");
        JSONObject d=new JSONObject(new String(decodeUrl(parts[1]),StandardCharsets.UTF_8));
        if(!event.equals(d.optString("e"))||!event.equals(eventId())){
            String other=d.optString("e");
            String label="otra función";
            String raw=importedRaw.get(other);
            if(raw!=null)try{
                JSONObject data=new JSONObject(new String(
                    decodeUrl(new JSONObject(raw).getString("payload")),
                    StandardCharsets.UTF_8));
                JSONObject ev=data.getJSONObject("event");
                label=ev.optString("name")+" · "+ev.optString("start_time");
            }catch(Exception ignored){}
            throw new Exception("ENTRADA DE OTRA FUNCIÓN: "+label+
                ". Selecciona la sesión correcta antes de validarla.");
        }
        JSONObject enrolled=tickets.get(d.optString("id"));
        if(enrolled==null||enrolled.optInt("number")!=d.optInt("n"))throw new Exception("QR no incluido en el evento importado");
        if(enrolled.optBoolean("used"))throw new Exception("Entrada ya utilizada al exportar el evento");
        return d;
    }
    public synchronized JSONObject validate(String qr,String event,String device,int start,int end) {
        return validate(qr,event,device,start,end,false);
    }
    public synchronized JSONObject validate(String qr,String event,String device,int start,int end,
                                            boolean acceptOutOfOrder) {
        try {
            JSONObject d=verifyQr(qr,event);
            int number=d.optInt("n",-1);
            if(number<start||number>end)throw new Exception("Entrada fuera del rango autorizado: "+start+"–"+end);
            String used="used_"+event+"_"+d.getString("id");
            if(prefs.getBoolean(used,false))throw new Exception("Esta entrada ya fue validada aquí");
            int expected=nextExpected();
            if(data!=null && "warn".equals(data.optString("sequence_mode","off")) &&
               !acceptOutOfOrder && number!=expected) {
                String msg=(number<firstActive()?
                    "Ticket anterior al primero activo ("+firstActive()+").":
                    "Se esperaba primero el ticket "+
                    String.format(java.util.Locale.US,"%04d",expected)+".")+
                    " Este es el "+String.format(java.util.Locale.US,"%04d",number)+
                    ". ¿Confirmar entrada fuera de orden?";
                return new JSONObject().put("status","warning").put("message",msg)
                    .put("number",number).put("expected",expected);
            }
            String accessTime=new java.text.SimpleDateFormat("dd/MM/yyyy HH:mm:ss",java.util.Locale.getDefault()).format(new java.util.Date());
            if(!prefs.edit().putBoolean(used,true).putString("used_time_"+event+"_"+d.getString("id"),accessTime).commit())throw new Exception("No se pudo guardar el acceso");
            return new JSONObject().put("status","valid").put("message","ACCESO AUTORIZADO").put("number",number)
                    .put("seat",d.optString("s","")).put("device",device);
        } catch(Exception ex) {
            JSONObject error=new JSONObject();
            try{error.put("status","invalid").put("message",ex.getMessage());}catch(Exception ignored){}
            return error;
        }
    }
    public synchronized int resetLocalAccesses() throws Exception {
        if(data==null)throw new Exception("Importa primero un JSON firmado");
        String prefix="used_"+eventId()+"_", timePrefix="used_time_"+eventId()+"_";
        SharedPreferences.Editor editor=prefs.edit();
        int count=0;
        for(String key:prefs.getAll().keySet()){
            if(key.startsWith(prefix)){editor.remove(key);count++;}
            if(key.startsWith(timePrefix))editor.remove(key);
        }
        if(!editor.commit())throw new Exception("No se pudieron restablecer los accesos");
        return count;
    }
    public synchronized JSONObject accessAudit(String deviceId) throws Exception {
        if(data==null)throw new Exception("No hay un evento importado");
        String eid=eventId();
        JSONArray used=new JSONArray();
        String prefix="used_"+eid+"_";
        for(Map.Entry<String,?> item:prefs.getAll().entrySet()){
            String k=item.getKey();
            if(k.startsWith(prefix) && Boolean.TRUE.equals(item.getValue())){
                String id=k.substring(prefix.length());
                if(tickets.containsKey(id))used.put(id);
            }
        }
        return new JSONObject().put("format","CE-ACCESS-1").put("event_id",eid)
            .put("device_id",deviceId).put("ticket_ids",used)
            .put("note","Registro administrativo; cotejar con el evento original antes de fusionar");
    }
    public synchronized void startHost(String secret) throws Exception {
        if(secret==null||!secret.matches("[0-9]{6}"))throw new Exception("El PIN de coordinación debe tener 6 cifras");
        if(data==null)throw new Exception("Primero importa un JSON firmado");
        if(hosting())return;
        server=new ServerSocket(PORT);
        threads.execute(()->{
            while(hosting()) {
                try{Socket socket=server.accept(); threads.execute(()->handle(socket,secret));}
                catch(Exception e){if(hosting())try{Thread.sleep(100);}catch(InterruptedException ignored){}}
            }
        });
    }
    public synchronized void stopHost(){
        if(server!=null)try{server.close();}catch(Exception ignored){}
        server=null;
    }
    private void handle(Socket sock,String pin){
        try(Socket socket=sock){
            socket.setSoTimeout(5000);
            InputStream input=socket.getInputStream();
            ByteArrayOutputStream b=new ByteArrayOutputStream();
            byte[] suffix=new byte[4];int count=0;int ch;
            while((ch=input.read())!=-1 && b.size()<6000){
                b.write(ch);suffix[count%4]=(byte)ch;count++;
                if(count>=4 && suffix[(count-4)%4]=='\r'&&suffix[(count-3)%4]=='\n'&&suffix[(count-2)%4]=='\r'&&suffix[(count-1)%4]=='\n')break;
            }
            String head=b.toString("UTF-8");
            if(!head.startsWith("POST /validate "))throw new Exception("Método no admitido");
            int length=-1;
            for(String line:head.split("\\r?\\n")){
                if(line.toLowerCase().startsWith("content-length:"))length=Integer.parseInt(line.split(":",2)[1].trim());
            }
            if(length<1||length>100_000)throw new Exception("Longitud no permitida");
            byte[] body=new byte[length];int off=0;
            while(off<length){int n=input.read(body,off,length-off);if(n<0)throw new Exception("Solicitud incompleta");off+=n;}
            JSONObject obj=new JSONObject(new String(body,StandardCharsets.UTF_8));
            JSONObject result;
            if(!pin.equals(obj.optString("pin")))result=new JSONObject().put("status","invalid").put("message","PIN incorrecto");
            else result=validate(obj.optString("qr"),obj.optString("event_id"),obj.optString("device_id"),1,Integer.MAX_VALUE);
            byte[] payload=result.toString().getBytes(StandardCharsets.UTF_8);
            OutputStream out=socket.getOutputStream();
            out.write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "+payload.length+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
            out.write(payload);out.flush();
        }catch(Exception ignored){}
    }
    public static String ips(){
        StringBuilder sb=new StringBuilder();
        try{
            Enumeration<NetworkInterface> nets=NetworkInterface.getNetworkInterfaces();
            while(nets.hasMoreElements()){
                NetworkInterface net=nets.nextElement();
                if(!net.isUp()||net.isLoopback())continue;
                Enumeration<java.net.InetAddress> addrs=net.getInetAddresses();
                while(addrs.hasMoreElements()){
                    java.net.InetAddress a=addrs.nextElement();
                    if(a instanceof Inet4Address && a.isSiteLocalAddress()){
                        if(sb.length()>0)sb.append("  ·  ");sb.append(a.getHostAddress());
                    }
                }
            }
        }catch(Exception ignored){}
        return sb.length()==0?"Sin IP local detectada":sb.toString();
    }
}
